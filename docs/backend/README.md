# Running the Phase 2 backend

This local backend implements source refresh, persistent tasks, polling, migrations and private artifacts. It does not implement full resume/application workflows or a website.

## Setup

Use Python 3.12. On a fresh machine with a Python 3.12 executable, create `.venv` with that interpreter. The validated Mac uses the existing Codex-bundled Python 3.12.14 environment; `python3.12` was not on its PATH. The commands below run from the repository root after `.venv` exists:

```bash
source .venv/bin/activate
python -m pip install --cache-dir data/pip-cache -r requirements.lock.txt
python -m pip check
python -m app.tools.init_db
```

Initialization runs all Alembic upgrades, preserves existing data, seeds the supported board once and creates a persistent owner-only local-session file. Re-running it is safe. It does not delete/recreate the database. `.env` and `data/` are ignored; copy the placeholder `.env.example` only if no populated local file already exists.

Phase 1 browser smoke tools still need their existing Chromium download. It is not needed by the Phase 2 source-refresh worker. For a fresh browser setup use the Phase 1 README command with `PLAYWRIGHT_BROWSERS_PATH` pointing at `data/playwright`.

## Start two processes

Terminal 1, after activation:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Terminal 2, from the same root after activation:

```bash
python -m app.worker
```

Open [the API docs](http://127.0.0.1:8000/docs). `/health` is public to the local boundary. Other routes require `X-CareerLens-Token`. The token and stable local session ID are stored privately in `data/backend/local-session.json`; use that token locally in Swagger's Authorize dialog. Never commit, share, paste into chat or put it in a URL. There is no public token-issuing endpoint, multi-user login or cloud auth system.

The default host is loopback. Only localhost/127.0.0.1 hosts and explicitly configured local origins are accepted; cross-site browser requests are rejected. The data directory can be changed using `CAREERLENS_DATA_DIR`, but API and worker must use the same value. Do not run the prototype on a public network interface.

## Execute the real integration

With both processes running:

```bash
python -m scripts.backend.demo_refresh
```

The script reads the local token without printing it, lists configured boards, POSTs a refresh with a new idempotency key, verifies replay of that key, polls the returned task and reads stored jobs. It accepts only a loopback HTTP API destination. The worker fetches the real configured Lever board; there is no automatic fixture fallback. Sanitized local evidence is written to `data/backend/phase2-live-demo.json`.

For manual execution in Swagger:

1. GET `/api/v1/source-boards` and copy the supported board ID/revision.
2. POST its `/refresh` route with a new Idempotency-Key and `{}` or `{"expected_revision": 1}` using the actual current revision.
3. Poll the returned `status_url`; inspect `/events` for queue, claim, recovery and outcome events.
4. GET the board's `/jobs` route. It returns stored rows only, with a total, offset, limit and last refresh time. Old data may remain during a failed refresh; inspect the board's last_error_code and timestamp.

Same key/same request always replays the original response, even after completion or restart. Reusing a key with different content returns 409. Different keys coalesce the same active board refresh. To explicitly refresh again after completion, use a new key. The worker's `--once` option processes at most one due task; it is not a substitute for a continuously running worker.

## Migrations and recovery

The three migrations create the 18 domain/operational tables, add history/terminal guards, then add complete structured snapshot metadata and preservation guards. Old v1 snapshots retain their original content/hash and empty unassessed metadata; the v2 pipeline writes new complete snapshots instead of rewriting history.

The worker takes a singleton lease and claims tasks inside short `BEGIN IMMEDIATE` transactions. Its separate heartbeat renews ownership during network reads. No DB transaction remains open during the remote fetch. Safe transient failures use bounded WAITING retries (at most three claims); schema/destination errors fail without retry. An expired safe lease can recover. Expired possible-send tasks instead become OUTCOME_UNKNOWN with no automatic retry. The real worker has no submit handler.

Ctrl+C/SIGTERM stops new claims, lets the current bounded safe read finish and marks the worker stopped. A hard kill leaves persisted ownership until expiry. Wait up to the configured lease duration before a replacement worker takes over. Health readiness is false for stopped/expired workers; database/API readiness is reported separately.

## Tests and diagnostics

```bash
pytest -q
python -m app.tools.export_contracts
python -m scripts.feasibility.check_repository_safety
```

The full suite uses temporary databases, synthetic fixtures and mocked source calls, including a process-kill recovery test. It requires no paid services or employer form. Phase 1 live smoke tools remain opt-in. `contracts/openapi.json` must match the implementation; regeneration does not make planned endpoints implemented.

Common issues: missing session/schema means initialization is needed; 401 means the local token is missing/wrong; 403 indicates origin/host rejection; 409 indicates stale revision/idempotency conflict; a non-ready worker may be stopped, expired or using another data directory. Source outage/timeouts appear in task polling with safe error codes. Do not blindly delete a stuck task or possible-send record.

Private artifacts have opaque IDs, ownership checks, atomic file writes and hash verification. The utility cleans abandoned temporary writes only. Final orphan-file reconciliation after a crash between rename and DB commit is not implemented; do not manually remove referenced files. No reset endpoint or destructive reset command exists.

macOS ARM64 was tested. These shell commands target macOS/Linux; Linux was not separately validated in this run. Native Windows is not validated: owner permissions, `O_NOFOLLOW` and process semantics need a separate review; WSL is the practical starting point. This remains a single-user local prototype, not a hardened multi-tenant service.
