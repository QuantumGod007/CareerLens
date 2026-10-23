from concurrent.futures import ThreadPoolExecutor
import json
from uuid import uuid4
import pytest

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import identity
from app.main import create_app
from app.persistence.models import Task, WorkerHeartbeat, utcnow
from app.services.tasks import Queue
from app.tools.init_db import BOARD_ID
from app.worker import Worker
from conftest import synthetic_job

REFRESH = f"/api/v1/source-boards/{BOARD_ID}/refresh"


def test_health_reports_worker_start_stop_and_staleness(client, database):
    health = client.get("/health").json()
    assert health["database_ready"] is True
    assert health["worker"]["ready"] is False
    queue = Queue(database, uuid4())
    queue.start()
    assert client.get("/health").json()["worker"]["ready"] is True
    queue.stop()
    assert client.get("/health").json()["worker"]["ready"] is False
    queue.start()
    with database.write() as session:
        heartbeat = session.get(WorkerHeartbeat, "primary")
        heartbeat.lease_expires_at = utcnow()
    assert client.get("/health").json()["worker"]["ready"] is False


def test_validation_envelopes_and_correlation(client, headers):
    correlation = str(uuid4())
    response = client.post(REFRESH, json={"expected_revision": "secret-invalid-value"},
                           headers={**headers, "X-Correlation-ID": correlation})
    assert response.status_code == 422
    assert response.json()["correlation_id"] == correlation
    assert response.headers["X-Correlation-ID"] == correlation
    assert "secret-invalid-value" not in response.text
    assert client.post(REFRESH, json={}, headers={"X-CareerLens-Token": headers["X-CareerLens-Token"]}).status_code == 422
    assert client.post(REFRESH, json={"unexpected": True}, headers=headers).status_code == 422
    assert client.get("/api/v1/tasks/not-a-uuid", headers=headers).status_code == 422
    assert client.get(f"/api/v1/tasks/{uuid4()}", headers=headers).status_code == 404


def test_local_security(client, headers):
    assert client.get("/api/v1/source-boards").status_code == 401
    assert client.post(REFRESH, json={}, headers={**headers, "Origin": "https://evil.example"}).status_code == 403
    assert client.get("/health", headers={"Host": "evil.example"}).status_code == 403
    assert client.get("/api/v1/source-boards", headers={**headers, "Sec-Fetch-Site": "cross-site"}).status_code == 403
    good = client.options(REFRESH, headers={"Origin": "http://localhost:8000"})
    assert good.headers["access-control-allow-origin"] == "http://localhost:8000"


def test_idempotent_commands_survive_restart(client, headers, settings, database):
    first = client.post(REFRESH, json={}, headers=headers)
    assert first.status_code == 202
    assert client.post(REFRESH, json={}, headers=headers).json() == first.json()
    assert client.post(REFRESH, json={"expected_revision": 1}, headers=headers).status_code == 409
    with TestClient(create_app(settings)) as restarted:
        assert restarted.post(REFRESH, json={}, headers=headers).json() == first.json()
    # A different key still coalesces an active refresh for the same board.
    assert client.post(REFRESH, json={}, headers={**headers, "Idempotency-Key": str(uuid4())}).json() == first.json()
    with database.read() as session:
        assert session.scalar(select(func.count()).select_from(Task)) == 1


@pytest.mark.parametrize("different_keys", [False, True])
def test_concurrent_identical_requests(client, headers, database, different_keys):
    def request(_):
        command_headers = {**headers, "Idempotency-Key": str(uuid4())} if different_keys else headers
        return client.post(REFRESH, json={}, headers=command_headers)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(request, range(2)))
    assert [r.status_code for r in responses] == [202, 202]
    assert responses[0].json() == responses[1].json()
    with database.read() as session:
        assert session.scalar(select(func.count()).select_from(Task)) == 1


def test_source_api_worker_database_pipeline(client, headers, database, settings):
    reference = client.post(REFRESH, json={}, headers=headers).json()
    status_url = reference["status_url"]
    assert client.get(status_url, headers=headers).json()["status"] == "QUEUED"
    assert client.get(f"/api/v1/source-boards/{BOARD_ID}/jobs", headers=headers).json()["total"] == 0
    Worker(database, fetcher=lambda board: ([synthetic_job()], 0)).run(once=True)
    result = client.get(status_url, headers=headers).json()
    assert result["status"] == "SUCCEEDED"
    assert result["attempts"] == 1
    assert result["progress"] == 100
    assert result["result"]["listing_count"] == 1
    assert result["result"]["data_origin"] == "fixture"
    assert [e["kind"] for e in client.get(status_url + "/events", headers=headers).json()] == ["QUEUED", "CLAIMED", "SUCCEEDED"]
    with TestClient(create_app(settings)) as restarted:
        stored = restarted.get(f"/api/v1/source-boards/{BOARD_ID}/jobs", headers=headers).json()
    assert stored["total"] == 1
    assert stored["items"][0]["title"] == "Engineering Intern"
    assert stored["last_refreshed_at"] is not None
    assert client.post(REFRESH, json={"expected_revision": 1},
        headers={**headers, "Idempotency-Key": str(uuid4())}).status_code == 409


def test_task_ownership_and_read_routes_do_not_fetch(client, headers, database, monkeypatch):
    reference = client.post(REFRESH, json={}, headers=headers).json()
    from uuid import UUID
    with database.write() as session:
        session.get(Task, UUID(reference["task_id"])).session_id = uuid4()
    assert client.get(reference["status_url"], headers=headers).status_code == 404
    monkeypatch.setattr("app.worker.fetch_board", lambda board: (_ for _ in ()).throw(AssertionError("GET must not fetch")))
    assert client.get(f"/api/v1/source-boards/{BOARD_ID}/jobs", headers=headers).status_code == 200
    assert client.get(f"/api/v1/source-boards/{BOARD_ID}/jobs?limit=101", headers=headers).status_code == 422


def test_logs_omit_request_values(client, headers, caplog):
    import logging
    with caplog.at_level(logging.INFO, logger="careerlens"):
        client.post(REFRESH, json={"secret": "SYNTHETIC_PRIVATE_MARKER"}, headers=headers)
    assert "SYNTHETIC_PRIVATE_MARKER" not in caplog.text
    assert headers["X-CareerLens-Token"] not in caplog.text


def test_unexpected_errors_do_not_expose_private_exception_text(client, headers, monkeypatch, caplog):
    def broken_read(*args):
        raise RuntimeError("SYNTHETIC_PRIVATE_EXCEPTION_MARKER")
    monkeypatch.setattr("app.services.artifacts.ArtifactStore.read", broken_read)
    response = client.get(f"/api/v1/artifacts/{uuid4()}", headers=headers)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "SYNTHETIC_PRIVATE_EXCEPTION_MARKER" not in response.text
    assert "SYNTHETIC_PRIVATE_EXCEPTION_MARKER" not in caplog.text


def test_health_reports_database_failure_truthfully(client, monkeypatch):
    monkeypatch.setattr(client.app.state.database, "ping", lambda: False)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["database_ready"] is False
    assert response.json()["ready"] is False
    assert response.json()["groq_key_present"] is False
