from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import threading
import time
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import identity
from app.core.errors import DomainError
from app.persistence.models import Task, JobSnapshot, SourceListing, utcnow
from app.services.tasks import Queue, enqueue_refresh
from app.tools.init_db import BOARD_ID
from app.worker import Worker
from conftest import synthetic_job
from scripts.feasibility.common import ProbeError


def enqueue(database):
    result = enqueue_refresh(database, BOARD_ID, identity(database.settings).id, uuid4(), str(uuid4()), None)
    return UUID(result["task_id"])


def test_claim_is_atomic_and_worker_leadership_is_exclusive(database):
    task_id = enqueue(database)
    queue = Queue(database, uuid4())
    queue.start()
    with pytest.raises(DomainError, match="WORKER_ALREADY_RUNNING"):
        Queue(database, uuid4()).start()
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: queue.claim(), range(2)))
    assert len([task for task in claims if task]) == 1
    assert [task.id for task in claims if task] == [task_id]


def test_no_transaction_held_during_fetch_and_heartbeat_continues(database):
    task_id = enqueue(database)
    entered = threading.Event()
    database.settings.lease_seconds = 1

    def fetch(board):
        # An independent write must succeed while the external handler executes.
        with database.write() as session:
            pass
        entered.set()
        # The handler outlives the original lease, so renewal is required to publish.
        time.sleep(1.15)
        return [synthetic_job()], 0

    worker = Worker(database, fetcher=fetch)
    worker.run(once=True)
    assert entered.is_set()
    with database.read() as session:
        task = session.get(Task, task_id)
        assert task.status == "SUCCEEDED"
        assert task.heartbeat_at > task.created_at + timedelta(seconds=0.5)


def test_unchanged_snapshots_reused_changed_versions_retained_and_empty_is_honest(database):
    for title, expected in [("Engineering Intern", 1), ("Engineering Intern", 1), ("New Engineering Intern", 2)]:
        task_id = enqueue(database)
        Worker(database, fetcher=lambda board: ([synthetic_job(title=title)], 0)).run(once=True)
        with database.read() as session:
            assert session.get(Task, task_id).status == "SUCCEEDED"
            assert session.scalar(select(func.count()).select_from(JobSnapshot)) == expected
    with database.read() as session:
        first = session.scalar(select(JobSnapshot).order_by(JobSnapshot.created_at))
        assert first.title == "Engineering Intern"
        assert first.structured_json["workplace_type"] == "remote"
        assert first.pipeline_version == "lever-v2"
    with pytest.raises(IntegrityError):
        with database.write() as session:
            session.get(JobSnapshot, first.id).title = "Overwritten"
    task_id = enqueue(database)
    Worker(database, fetcher=lambda board: ([], 0)).run(once=True)
    with database.read() as session:
        assert session.get(Task, task_id).result_json["listing_count"] == 0
        assert session.scalar(select(func.count()).select_from(SourceListing)) == 0
        assert session.scalar(select(func.count()).select_from(JobSnapshot)) == 2


def test_transient_errors_retry_but_remain_bounded(database):
    task_id = enqueue(database)
    def timeout(board):
        raise ProbeError("SOURCE_TIMEOUT")
    for attempt in range(1, 4):
        Worker(database, fetcher=timeout).run(once=True)
        with database.read() as session:
            task = session.get(Task, task_id)
            assert task.attempts == attempt
            assert task.status == ("WAITING" if attempt < 3 else "FAILED")
    Worker(database, fetcher=lambda board: (_ for _ in ()).throw(AssertionError("Exhausted task ran again"))).run(once=True)
    with database.read() as session:
        assert session.get(Task, task_id).attempts == 3


@pytest.mark.parametrize("code", ["SOURCE_SCHEMA_INVALID", "UNEXPECTED_JOB_DESTINATION"])
def test_permanent_errors_do_not_retry(database, code):
    task_id = enqueue(database)
    def bad(board):
        raise ProbeError(code)
    Worker(database, fetcher=bad).run(once=True)
    with database.read() as session:
        assert session.get(Task, task_id).status == "FAILED"


def test_expired_safe_task_recovers_and_old_owner_is_fenced(database):
    task_id = enqueue(database)
    old = Queue(database, uuid4())
    old.start()
    old.claim()
    with database.write() as session:
        task = session.get(Task, task_id)
        task.lease_expires_at = utcnow() - timedelta(seconds=1)
    old.stop()
    Worker(database, fetcher=lambda board: ([synthetic_job()], 0)).run(once=True)
    with pytest.raises(DomainError, match="LEASE_LOST"):
        old.complete_refresh(task_id, [], 0)
    with database.read() as session:
        task = session.get(Task, task_id)
        assert task.status == "SUCCEEDED" and task.attempts == 2


def test_unconfigured_source_and_destination_are_rejected(database):
    task_id = enqueue(database)
    bad = synthetic_job().model_copy(update={"apply_url": "http://127.0.0.1/private"})
    Worker(database, fetcher=lambda board: ([bad], 0)).run(once=True)
    with database.read() as session:
        assert session.get(Task, task_id).error_code == "UNEXPECTED_JOB_DESTINATION"
        assert session.scalar(select(func.count()).select_from(JobSnapshot)) == 0


def test_clean_shutdown_finishes_current_safe_read(database):
    task_id = enqueue(database)
    def fetch(board):
        worker.stop_event.set()
        return [synthetic_job()], 0
    worker = Worker(database, fetcher=fetch)
    worker.run()
    with database.read() as session:
        assert session.get(Task, task_id).status == "SUCCEEDED"
