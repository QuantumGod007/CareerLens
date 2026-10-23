"""Kill a separate worker process during a fixture read; no live site is involved."""
import multiprocessing
from pathlib import Path
import time
from uuid import UUID, uuid4

from sqlalchemy import select

from app.core.config import Settings, identity
from app.persistence.database import Database
from app.persistence.models import Task, WorkerHeartbeat
from app.services.tasks import enqueue_refresh
from app.tools.init_db import BOARD_ID
from app.worker import Worker
from conftest import synthetic_job


def crash_child(data_directory, marker):
    settings = Settings(data_dir=Path(data_directory), heartbeat_seconds=0.1, lease_seconds=1,
                        retry_seconds=0)
    database = Database(settings)

    def pause_during_read(board):
        Path(marker).write_text("Inside synthetic external-read stage, outside a DB transaction")
        time.sleep(30)
        return [], 0

    Worker(database, fetcher=pause_during_read).run(once=True)


def test_real_process_kill_and_safe_restart(database, settings, tmp_path):
    reference = enqueue_refresh(database, BOARD_ID, identity(settings).id, uuid4(), str(uuid4()), None)
    task_id = UUID(reference["task_id"])
    marker = tmp_path / "claimed.txt"
    process = multiprocessing.get_context("spawn").Process(target=crash_child, args=(str(settings.data_dir), str(marker)))
    process.start()
    try:
        deadline = time.monotonic() + 8
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.exists(), "Child worker did not reach the controlled read stage"
        process.kill()
        process.join(timeout=5)
        assert not process.is_alive()
        with database.read() as session:
            assert session.get(Task, task_id).status == "RUNNING"
            deadline = session.get(WorkerHeartbeat, "primary").lease_expires_at.timestamp()
        time.sleep(max(0, deadline - time.time()) + 0.15)
        Worker(database, fetcher=lambda board: ([synthetic_job()], 0)).run(once=True)
        with database.read() as session:
            task = session.get(Task, task_id)
            assert task.status == "SUCCEEDED"
            assert task.attempts == 2
            assert task.result_json["listing_count"] == 1
    finally:
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
