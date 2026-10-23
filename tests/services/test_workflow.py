from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import identity
from app.core.errors import DomainError
from app.persistence.models import Application, Candidate, PreparationRun, Approval, Task, utcnow
from app.services.tasks import Queue
from app.services.workflow import start_run, transition, approve_controlled_run


def make_application(database, mode="review"):
    with database.write() as session:
        candidate = session.scalar(select(Candidate))
        application = Application(candidate_id=candidate.id, canonical_job_key="controlled:synthetic-job")
        session.add(application)
        session.flush()
        run = start_run(session, application.id, application.revision, mode, uuid4())
        return application.id, run.id


def move(database, run_id, target, **kwargs):
    with database.write() as session:
        run = session.get(PreparationRun, run_id)
        return transition(session, run.id, run.revision, target, uuid4(), **kwargs)


def ready(database, run_id):
    move(database, run_id, "PREPARING")
    with database.write() as session:
        session.get(PreparationRun, run_id).payload_hash = "a" * 64
    move(database, run_id, "READY_FOR_APPROVAL")


def test_dry_run_terminal_does_not_prevent_later_review(database):
    application_id, run_id = make_application(database, "dry_run")
    move(database, run_id, "PREPARING")
    move(database, run_id, "DRY_RUN_READY")
    with database.write() as session:
        application = session.get(Application, application_id)
        new = start_run(session, application.id, application.revision, "review", uuid4())
        assert new.id != run_id and new.state == "CREATED"
    with database.read() as session:
        assert session.get(PreparationRun, run_id).state == "DRY_RUN_READY"
    with pytest.raises(IntegrityError):
        with database.write() as session:
            session.get(PreparationRun, run_id).state = "PREPARING"


def test_invalid_and_stale_transitions(database):
    _, run_id = make_application(database)
    with pytest.raises(DomainError, match="INVALID_STATE"):
        move(database, run_id, "SUBMITTED")
    move(database, run_id, "PREPARING")
    with pytest.raises(DomainError, match="STALE_REVISION"):
        with database.write() as session:
            transition(session, run_id, 1, "CANCELLED", uuid4())
    move(database, run_id, "NEEDS_INPUT")
    move(database, run_id, "PREPARING")
    move(database, run_id, "CANCELLED")
    with pytest.raises(DomainError):
        move(database, run_id, "PREPARING")


def test_approval_is_bound_to_revision_payload_and_owner(database):
    _, run_id = make_application(database)
    ready(database, run_id)
    with pytest.raises(DomainError, match="APPROVAL_REQUIRED"):
        move(database, run_id, "SUBMITTING", approved=True)
    with pytest.raises(DomainError, match="STALE_REVIEW"):
        with database.write() as session:
            run = session.get(PreparationRun, run_id)
            approve_controlled_run(session, run.id, run.revision, "b" * 64, identity(database.settings).id, uuid4())
    with pytest.raises(DomainError, match="FORBIDDEN"):
        with database.write() as session:
            run = session.get(PreparationRun, run_id)
            approve_controlled_run(session, run.id, run.revision, "a" * 64, uuid4(), uuid4())


def test_changed_payload_invalidates_approval_foundation(database):
    _, run_id = make_application(database)
    ready(database, run_id)
    with database.write() as session:
        run = session.get(PreparationRun, run_id)
        approval = Approval(run_id=run.id, payload_hash=run.payload_hash,
            actor_session_id=identity(database.settings).id, approved_revision=run.revision)
        session.add(approval)
    move(database, run_id, "PREPARING")
    with database.read() as session:
        assert session.get(Approval, approval.id).invalidated_at is not None
        assert session.get(PreparationRun, run_id).payload_hash is None


def test_cancellation_race_has_one_winner(database):
    _, run_id = make_application(database)
    def cancel(_):
        try:
            with database.write() as session:
                transition(session, run_id, 1, "CANCELLED", uuid4())
            return "won"
        except DomainError:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(cancel, range(2))) == ["conflict", "won"]


def test_possible_send_crash_becomes_unknown_and_never_requeues(database):
    application_id, run_id = make_application(database)
    ready(database, run_id)
    correlation = uuid4()
    with database.write() as session:
        run = session.get(PreparationRun, run_id)
        approve_controlled_run(session, run.id, run.revision, run.payload_hash,
                               identity(database.settings).id, correlation)
        task = Task(session_id=identity(database.settings).id, kind="controlled_submit",
            entity_type="preparation_run", entity_id=run.id, run_id=run.id, correlation_id=correlation,
            status="RUNNING", attempts=1, possible_send_at=utcnow(), lease_owner=uuid4(),
            lease_expires_at=utcnow() - timedelta(seconds=1))
        session.add(task)
    with pytest.raises(DomainError, match="EVIDENCE_REQUIRED"):
        move(database, run_id, "SUBMITTED")
    queue = Queue(database, uuid4())
    queue.start()
    assert queue.claim() is None
    with database.read() as session:
        assert session.get(Task, task.id).status == "FAILED"
        assert session.get(Task, task.id).error_code == "OUTCOME_UNKNOWN"
        assert session.get(PreparationRun, run_id).state == "OUTCOME_UNKNOWN"
        application = session.get(Application, application_id)
    with pytest.raises(DomainError, match="DUPLICATE_SUBMISSION"):
        with database.write() as session:
            start_run(session, application_id, application.revision, "review", uuid4())
    with pytest.raises(DomainError, match="EVIDENCE_REQUIRED"):
        move(database, run_id, "NOT_SUBMITTED")
    move(database, run_id, "NOT_SUBMITTED", evidence=True)
    with pytest.raises(IntegrityError):
        with database.write() as session:
            session.get(Application, application_id).send_started_at = None
    queue.stop()
