"""Persisted domain foundations only. Nothing here sends an employer application."""
from uuid import UUID

from sqlalchemy import select, update

from app.core.errors import DomainError
from app.persistence.models import Application, PreparationRun, Approval, Candidate, utcnow
from app.services.events import append_event

TERMINAL = {"SUBMITTED", "NOT_SUBMITTED", "CANCELLED", "DRY_RUN_READY"}
ALLOWED = {
    "CREATED": {"PREPARING", "CANCELLED"},
    "PREPARING": {"NEEDS_INPUT", "NEEDS_LOGIN", "READY_FOR_APPROVAL", "DRY_RUN_READY", "FAILED", "CANCELLED"},
    "NEEDS_INPUT": {"PREPARING", "CANCELLED"}, "NEEDS_LOGIN": {"PREPARING", "CANCELLED"},
    "READY_FOR_APPROVAL": {"SUBMITTING", "PREPARING", "CANCELLED"},
    "SUBMITTING": {"SUBMITTED", "NEEDS_INPUT", "OUTCOME_UNKNOWN", "FAILED"},
    "OUTCOME_UNKNOWN": {"SUBMITTED", "NOT_SUBMITTED"},
    "FAILED": {"PREPARING", "CANCELLED"},
}


def get_run(session, run_id, expected_revision):
    run = session.get(PreparationRun, run_id)
    if run is None:
        raise DomainError("NOT_FOUND", "Preparation run not found.", 404)
    if run.revision != expected_revision:
        raise DomainError("STALE_REVISION", "Refresh the current revision.")
    return run


def transition(session, run_id, expected_revision, target, correlation_id, *,
               step=None, approved=False, evidence=False, proven_no_send=False):
    run = get_run(session, run_id, expected_revision)
    application = session.get(Application, run.application_id)
    previous = run.state
    if target not in ALLOWED.get(previous, set()) or application.active_run_id != run.id:
        raise DomainError("INVALID_STATE", "The requested transition is not allowed.")
    if target == "SUBMITTING" and (not approved or run.mode != "review" or application.send_started_at):
        raise DomainError("APPROVAL_REQUIRED", "A current approved review is required.")
    if target == "SUBMITTING":
        approval = session.scalar(select(Approval).where(Approval.run_id == run.id,
            Approval.payload_hash == run.payload_hash, Approval.approved_revision == run.revision,
            Approval.invalidated_at.is_(None)))
        if approval is None:
            raise DomainError("APPROVAL_REQUIRED", "A persisted current approval is required.")
    if target == "DRY_RUN_READY" and run.mode != "dry_run":
        raise DomainError("INVALID_STATE", "Only a dry run can reach this state.")
    if target == "READY_FOR_APPROVAL" and (run.mode != "review" or not run.payload_hash):
        raise DomainError("REVIEW_REQUIRED", "A complete review payload is required.")
    if previous == "OUTCOME_UNKNOWN" and not evidence:
        raise DomainError("EVIDENCE_REQUIRED", "Outcome reconciliation requires evidence.")
    if target == "SUBMITTED" and not evidence:
        raise DomainError("EVIDENCE_REQUIRED", "Confirmed receipt evidence is required.")
    if previous == "SUBMITTING" and target in {"FAILED", "NEEDS_INPUT"} and not proven_no_send:
        raise DomainError("OUTCOME_UNKNOWN", "A possible send must be reconciled.")
    # Compare-and-swap remains necessary even if a caller omits the write lock.
    changed = session.execute(update(PreparationRun).where(
        PreparationRun.id == run.id, PreparationRun.revision == expected_revision,
        PreparationRun.state == previous).values(state=target, revision=expected_revision + 1,
        current_step=step, payload_hash=None if target == "PREPARING" else run.payload_hash))
    if changed.rowcount != 1:
        raise DomainError("STALE_REVISION", "The run changed concurrently.")
    application.state = target
    application.revision += 1
    if target == "SUBMITTING":
        application.send_started_at = utcnow()
    if target in {"PREPARING", "CANCELLED"}:
        session.execute(update(Approval).where(Approval.run_id == run.id,
            Approval.invalidated_at.is_(None)).values(invalidated_at=utcnow()))
    append_event(session, "preparation_run", run.id, correlation_id, "STATE_CHANGED",
                 from_state=previous, to_state=target, revision=expected_revision + 1)
    session.flush()
    session.refresh(run)
    return run


def start_run(session, application_id, expected_revision, mode, correlation_id):
    application = session.get(Application, application_id)
    if application is None:
        raise DomainError("NOT_FOUND", "Application not found.", 404)
    if application.revision != expected_revision:
        raise DomainError("STALE_REVISION", "Refresh the application revision.")
    if mode not in {"review", "dry_run"}:
        raise DomainError("INVALID_MODE", "Unsupported preparation mode.", 422)
    if application.send_started_at or application.state in {"SUBMITTED", "OUTCOME_UNKNOWN", "NOT_SUBMITTED"}:
        raise DomainError("DUPLICATE_SUBMISSION", "A live send is already recorded or unresolved.")
    previous = session.get(PreparationRun, application.active_run_id) if application.active_run_id else None
    if previous and previous.state not in TERMINAL:
        raise DomainError("RUN_ACTIVE", "An existing preparation run is still active.")
    run = PreparationRun(application_id=application.id, mode=mode, state="CREATED")
    session.add(run)
    session.flush()
    changed = session.execute(update(Application).where(Application.id == application.id,
        Application.revision == expected_revision).values(active_run_id=run.id, state="CREATED",
        revision=expected_revision + 1))
    if changed.rowcount != 1:
        raise DomainError("STALE_REVISION", "The application changed concurrently.")
    append_event(session, "preparation_run", run.id, correlation_id, "RUN_CREATED", mode=mode, revision=1)
    return run


def approve_controlled_run(session, run_id, expected_revision, payload_hash, actor, correlation_id):
    """Domain-level guard for synthetic tests, with no API route or send handler."""
    run = get_run(session, run_id, expected_revision)
    application = session.get(Application, run.application_id)
    candidate = session.get(Candidate, application.candidate_id)
    if candidate.session_id != actor:
        raise DomainError("FORBIDDEN", "This local session does not own the application.", 403)
    if run.state != "READY_FOR_APPROVAL" or not payload_hash or run.payload_hash != payload_hash:
        raise DomainError("STALE_REVIEW", "Review the current payload before approving.")
    session.add(Approval(run_id=run.id, payload_hash=payload_hash, actor_session_id=actor,
                         approved_revision=run.revision))
    return transition(session, run.id, run.revision, "SUBMITTING", correlation_id, approved=True)
