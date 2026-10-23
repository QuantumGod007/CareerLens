"""Single durable worker for source refresh and private Resume Studio tasks."""
from __future__ import annotations

import argparse
import logging
import os
import signal
import threading
import time
from uuid import uuid4

from app.adapters.lever import fetch_board
from app.core.config import identity, load_settings
from app.core.errors import DomainError
from app.core.logging import record
from app.persistence.database import Database
from app.persistence.models import SourceBoard
from app.services.tasks import Queue
from scripts.feasibility.common import ProbeError


class Worker:
    def __init__(self, database, fetcher=fetch_board, provider=None):
        self.db, self.fetcher = database, fetcher
        self.provider = provider
        self.queue = Queue(database, uuid4())
        self.stop_event = threading.Event()
        self.heartbeat_stop = threading.Event()
        self.lease_lost = threading.Event()
        self.task_id = None

    def heartbeat_loop(self):
        while not self.heartbeat_stop.wait(self.db.settings.heartbeat_seconds):
            try:
                self.queue.heartbeat(self.task_id)
            except Exception:
                # Losing ownership must fence this process off from result publication.
                self.lease_lost.set()
                self.stop_event.set()

    def run_once(self):
        task = self.queue.claim()
        if task is None:
            return False
        self.task_id = task.id
        started = time.perf_counter()
        try:
            from app.services.studio_worker import HANDLERS
            if task.kind in HANDLERS:
                HANDLERS[task.kind](self, task)
                return True
            if task.kind != "source_refresh":
                raise DomainError("HANDLER_NOT_ALLOWED", "No submission handler is enabled.")
            with self.db.read() as session:
                board = session.get(SourceBoard, task.entity_id)
                session.expunge(board)
            # The read session is closed before making the external request.
            jobs, duplicates = self.fetcher(board)
            if self.lease_lost.is_set():
                raise DomainError("LEASE_LOST", "Worker ownership lost.")
            self.queue.complete_refresh(task.id, jobs, duplicates,
                                        data_origin="live" if self.fetcher is fetch_board else "fixture")
        except (ProbeError, DomainError) as error:
            if getattr(error, "code", None) != "LEASE_LOST":
                self.queue.fail(task.id, error.code, getattr(error, "retry_after", None))
            record("task_error", task_id=task.id, correlation_id=task.correlation_id, error_code=error.code)
        except Exception:
            self.queue.fail(task.id, "UNEXPECTED_WORKER_ERROR")
            record("task_error", task_id=task.id, correlation_id=task.correlation_id, error_code="UNEXPECTED_WORKER_ERROR")
        finally:
            self.task_id = None
            record("task_finished", task_id=task.id, correlation_id=task.correlation_id,
                   attempt=task.attempts, duration_ms=round((time.perf_counter() - started) * 1000))
        return True

    def run(self, *, once=False):
        self.queue.start()
        heartbeat = threading.Thread(target=self.heartbeat_loop, daemon=True)
        heartbeat.start()
        try:
            while not self.stop_event.is_set():
                worked = self.run_once()
                if once:
                    break
                if not worked:
                    self.stop_event.wait(self.db.settings.poll_seconds)
        finally:
            self.stop_event.set()
            self.heartbeat_stop.set()
            heartbeat.join(timeout=self.db.settings.heartbeat_seconds + 1)
            self.queue.stop()


def main():
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Process at most one due task, then exit")
    args = parser.parse_args()
    settings = load_settings()
    identity(settings)  # Refuse an uninitialized local environment.
    database = Database(settings)
    worker = Worker(database)
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: worker.stop_event.set())
    try:
        worker.run(once=args.once)
    except DomainError as error:
        record("worker_stopped", error_code=error.code)
        raise SystemExit(1)
    finally:
        database.close()


if __name__ == "__main__":
    main()
