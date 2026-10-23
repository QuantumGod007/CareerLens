from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import delete, or_, select

from app.core.errors import DomainError
from app.persistence.models import (SourceBoard, Task, WorkerHeartbeat, IdempotencyRecord,
                                    JobSnapshot, SourceListing, PreparationRun, utcnow)
from app.services.events import append_event
from app.services.idempotency import canonical_hash, previous_response
from app.services.workflow import transition
from scripts.feasibility.test_job_source import check_job_url

ACTIVE = {"QUEUED", "RUNNING", "WAITING"}
SAFE_RETRY = {"SOURCE_TIMEOUT", "SOURCE_NETWORK_ERROR", "SOURCE_UNAVAILABLE", "SOURCE_RATE_LIMITED"}


def enqueue_refresh(database, board_id, local_id, correlation_id, key, expected_revision):
    route = f"/api/v1/source-boards/{board_id}/refresh"
    digest = canonical_hash({"board_id": str(board_id), "expected_revision": expected_revision})
    with database.write() as session:
        previous = previous_response(session, local_id, route, key, digest)
        if previous is not None:
            return previous
        board = session.get(SourceBoard, board_id)
        if board is None:
            raise DomainError("NOT_FOUND", "Source board not found.", 404)
        if not board.enabled:
            raise DomainError("SOURCE_DISABLED", "This source is disabled.", 400)
        if expected_revision is not None and expected_revision != board.revision:
            raise DomainError("STALE_REVISION", "Refresh the source revision.")
        business_key = f"source_refresh:{board.id}"
        task = session.scalar(select(Task).where(Task.business_key == business_key, Task.status.in_(ACTIVE)))
        if task is None:
            task = Task(session_id=local_id, kind="source_refresh", entity_type="source_board",
                        entity_id=board.id, business_key=business_key, correlation_id=correlation_id)
            session.add(task)
            session.flush()
            append_event(session, "task", task.id, correlation_id, "QUEUED", step="QUEUED", attempt=0)
        result = {"task_id": str(task.id), "entity_type": "source_board", "entity_id": str(board.id),
                  "status_url": f"/api/v1/tasks/{task.id}"}
        session.add(IdempotencyRecord(session_id=local_id, route=route, key=key, request_hash=digest,
                                      status_code=202, response_json=result))
        return result


class Queue:
    def __init__(self, database, owner: UUID):
        self.db, self.owner = database, owner

    def deadline(self):
        return utcnow() + timedelta(seconds=self.db.settings.lease_seconds)

    def start(self):
        with self.db.write() as session:
            heartbeat = session.get(WorkerHeartbeat, "primary")
            if heartbeat and heartbeat.running and heartbeat.lease_expires_at > utcnow() and heartbeat.owner != self.owner:
                raise DomainError("WORKER_ALREADY_RUNNING", "Another worker owns the local lease.")
            if heartbeat is None:
                session.add(WorkerHeartbeat(name="primary", owner=self.owner, heartbeat_at=utcnow(),
                                           lease_expires_at=self.deadline(), running=True))
            else:
                heartbeat.owner, heartbeat.running = self.owner, True
                heartbeat.heartbeat_at, heartbeat.lease_expires_at = utcnow(), self.deadline()

    def assert_owner(self, session):
        heartbeat = session.get(WorkerHeartbeat, "primary")
        if not heartbeat or heartbeat.owner != self.owner or not heartbeat.running or heartbeat.lease_expires_at <= utcnow():
            raise DomainError("LEASE_LOST", "Worker ownership expired.")

    def heartbeat(self, task_id=None):
        with self.db.write() as session:
            self.assert_owner(session)
            heartbeat = session.get(WorkerHeartbeat, "primary")
            heartbeat.heartbeat_at, heartbeat.lease_expires_at = utcnow(), self.deadline()
            if task_id:
                task = session.get(Task, task_id)
                # Completion can race this thread; a finished task needs no renewal.
                if task and task.status == "RUNNING":
                    task = self.owned(session, task_id)
                    task.heartbeat_at, task.lease_expires_at = utcnow(), self.deadline()

    def stop(self):
        with self.db.write() as session:
            heartbeat = session.get(WorkerHeartbeat, "primary")
            if heartbeat and heartbeat.owner == self.owner:
                heartbeat.running, heartbeat.lease_expires_at = False, utcnow()

    def recover(self, session):
        for task in session.scalars(select(Task).where(Task.status == "RUNNING",
                or_(Task.lease_expires_at <= utcnow(), Task.lease_expires_at.is_(None)))):
            if task.possible_send_at is not None or task.kind != "source_refresh":
                if task.run_id:
                    run = session.get(PreparationRun, task.run_id)
                    if run and run.state == "SUBMITTING":
                        transition(session, run.id, run.revision, "OUTCOME_UNKNOWN", task.correlation_id,
                                   step="RECONCILIATION_REQUIRED")
                task.status, task.error_code = "FAILED", "OUTCOME_UNKNOWN"
                task.finished_at = utcnow()
            elif task.attempts >= task.max_attempts:
                task.status, task.error_code = "FAILED", "RETRY_EXHAUSTED"
                task.finished_at = utcnow()
            else:
                task.status, task.current_step = "QUEUED", "RECOVERED"
            task.lease_owner, task.lease_expires_at, task.updated_at = None, None, utcnow()
            append_event(session, "task", task.id, task.correlation_id, "LEASE_RECOVERY",
                         step=task.current_step, error_code=task.error_code, attempt=task.attempts)

    def claim(self):
        with self.db.write() as session:
            self.assert_owner(session)
            self.recover(session)
            session.flush()
            task = session.scalar(select(Task).where(or_(Task.status == "QUEUED",
                (Task.status == "WAITING") & (Task.retry_at <= utcnow()))).order_by(Task.created_at, Task.id).limit(1))
            if task is None:
                return None
            task.status, task.current_step = "RUNNING", "FETCHING_SOURCE"
            task.attempts += 1
            task.progress = 10
            task.lease_owner, task.lease_expires_at = self.owner, self.deadline()
            task.heartbeat_at, task.updated_at, task.retry_at = utcnow(), utcnow(), None
            append_event(session, "task", task.id, task.correlation_id, "CLAIMED",
                         step=task.current_step, attempt=task.attempts)
            session.flush()
            return task

    def owned(self, session, task_id):
        self.assert_owner(session)
        task = session.get(Task, task_id)
        if (not task or task.status != "RUNNING" or task.lease_owner != self.owner
                or task.lease_expires_at is None or task.lease_expires_at <= utcnow()):
            raise DomainError("LEASE_LOST", "Task ownership expired.")
        return task

    def complete_refresh(self, task_id, jobs, duplicates, *, data_origin="live"):
        # Atomically publish a full board generation and the task outcome.
        with self.db.write() as session:
            task = self.owned(session, task_id)
            if task.kind != "source_refresh":
                raise DomainError("HANDLER_NOT_ALLOWED", "No live submission handler exists.")
            board = session.get(SourceBoard, task.entity_id)
            if not board or not board.enabled or board.slug != "drivetrain" or board.family != "lever":
                raise DomainError("SOURCE_NOT_ALLOWED", "Source configuration changed.")
            session.execute(delete(SourceListing).where(SourceListing.source_board_id == board.id))
            seen, created, reused = set(), 0, 0
            for job in jobs:
                check_job_url(job.source_url, job.external_id)
                check_job_url(job.apply_url, job.external_id)
                if job.external_id in seen:
                    duplicates += 1
                    continue
                seen.add(job.external_id)
                data = job.model_dump(exclude={"fetched_at", "content_sha256"})
                content_hash = canonical_hash({"pipeline_version": "lever-v2", "job": data})
                snapshot = session.scalar(select(JobSnapshot).where(JobSnapshot.source_board_id == board.id,
                    JobSnapshot.external_id == job.external_id, JobSnapshot.content_hash == content_hash))
                if snapshot is None:
                    from datetime import datetime
                    snapshot = JobSnapshot(source_board_id=board.id, external_id=job.external_id,
                        canonical_job_key=job.canonical_job_key, content_hash=content_hash,
                        fetched_at=datetime.fromisoformat(job.fetched_at), title=job.title, employer=job.employer,
                        location=job.location, employment_type=job.employment_type, raw_text=job.description,
                        structured_json=data, source_url=job.source_url, apply_url=job.apply_url)
                    session.add(snapshot)
                    session.flush()
                    created += 1
                else:
                    reused += 1
                session.add(SourceListing(source_board_id=board.id, external_id=job.external_id,
                                          job_snapshot_id=snapshot.id))
            board.refreshed_at, board.validated_at, board.last_error_code = utcnow(), utcnow(), None
            board.revision += 1
            task.status, task.current_step, task.progress = "SUCCEEDED", "PERSISTED_JOBS", 100
            task.result_json = {"entity_type": "source_board", "entity_id": str(board.id),
                "listing_count": len(seen), "new_snapshots": created, "reused_snapshots": reused,
                "duplicates_removed": duplicates, "data_origin": data_origin}
            task.error_code, task.lease_owner, task.lease_expires_at = None, None, None
            task.updated_at, task.finished_at = utcnow(), utcnow()
            append_event(session, "task", task.id, task.correlation_id, "SUCCEEDED", count=len(seen), attempt=task.attempts)

    def fail(self, task_id, code, retry_after=None):
        with self.db.write() as session:
            task = self.owned(session, task_id)
            safe = task.kind == "source_refresh" and task.possible_send_at is None
            if not safe:
                run = session.get(PreparationRun, task.run_id) if task.run_id else None
                if run and run.state == "SUBMITTING":
                    transition(session, run.id, run.revision, "OUTCOME_UNKNOWN", task.correlation_id)
                if task.possible_send_at:
                    code = "OUTCOME_UNKNOWN"
            if safe and code in SAFE_RETRY and task.attempts < task.max_attempts:
                delay = self.db.settings.retry_seconds * 2 ** (task.attempts - 1)
                if retry_after:
                    try:
                        delay = max(delay, min(float(retry_after), 300))
                    except ValueError:
                        pass
                task.status = "WAITING"
                task.retry_at = utcnow() + timedelta(seconds=delay)
            else:
                task.status, task.finished_at = "FAILED", utcnow()
            task.error_code = code
            task.current_step = "SOURCE_ERROR"
            task.updated_at = utcnow()
            task.lease_owner, task.lease_expires_at = None, None
            board = session.get(SourceBoard, task.entity_id) if safe else None
            if board:
                board.last_error_code = code
            append_event(session, "task", task.id, task.correlation_id, task.status,
                         error_code=code, attempt=task.attempts)
