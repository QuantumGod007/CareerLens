"""Exercise an already-running local API and separate worker, using the real source."""
import argparse
import json
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from app.core.config import identity, load_settings
from app.persistence.models import utcnow


def run(base_url: str):
    parsed = urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.path not in {"", "/"}:
        raise ValueError("Demo accepts only a loopback HTTP API, never a remote token destination")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Invalid local API address")
    local = identity(load_settings())
    headers = {"X-CareerLens-Token": local.token, "Idempotency-Key": str(uuid4())}
    with httpx.Client(base_url=base_url, headers=headers, timeout=5, follow_redirects=False) as client:
        health = client.get("/health")
        health.raise_for_status()
        if not health.json()["worker"]["ready"]:
            raise RuntimeError("Start the separate worker before running this demo")
        boards = client.get("/api/v1/source-boards")
        boards.raise_for_status()
        board = next(board for board in boards.json() if board["slug"] == "drivetrain")
        response = client.post(f"/api/v1/source-boards/{board['id']}/refresh", json={})
        response.raise_for_status()
        assert response.status_code == 202
        reference = response.json()
        assert client.post(f"/api/v1/source-boards/{board['id']}/refresh", json={}).json() == reference
        deadline = time.monotonic() + 65
        while time.monotonic() < deadline:
            polled = client.get(reference["status_url"])
            polled.raise_for_status()
            task = polled.json()
            if task["status"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("Source task did not finish before the demo timeout")
        if task["status"] != "SUCCEEDED":
            raise RuntimeError(f"Source refresh stopped with safe code {task['error_code']}")
        stored = client.get(f"/api/v1/source-boards/{board['id']}/jobs?limit=5")
        stored.raise_for_status()
        jobs = stored.json()
        return {"status": "PASS", "observed_at": utcnow().isoformat(),
                "target": "Real local HTTP API and separate worker; live Lever source",
                "task_id": reference["task_id"], "task_status": task["status"],
                "attempts": task["attempts"], "result": task["result"],
                "persisted_total": jobs["total"],
                "example_titles": [job["title"] for job in jobs["items"]],
                "idempotent_replay": "PASS", "worker_ready_before": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    result = run(args.base_url)
    destination = load_settings().data_dir / "phase2-live-demo.json"
    destination.write_text(json.dumps(result, indent=2) + "\n")
    destination.chmod(0o600)
    print(json.dumps(result, indent=2))
