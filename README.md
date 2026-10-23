# CareerLens

CareerLens is a local job application assistant being built for students and freshers. The intended workflow preserves candidate facts and requires approval before submission.

## Current status

Phase 2 backend foundation is implemented. It runs FastAPI, SQLite migrations and a separate durable worker. A real API request has been processed through SQLite and the worker into the live Drivetrain Lever feed, with 35 jobs persisted and served back through the API.

**The complete product is not implemented.** Resume upload/extraction, candidate-specific matching, AI resume tailoring, employer form preparation/submission and the website remain later phases. No employer application was submitted. Phase 3 has not started.

Phase 1 is merged through PR #1. Its scripts, fixtures and 41 tests are preserved. The combined suite currently passes **84 tests**: 41 Phase 1 and 43 backend tests, with zero failures/skips. A Starlette test-client deprecation warning remains; runtime checks pass.

## Run locally

Use Python 3.12 and create a local `.venv` with that interpreter. This Mac uses the existing environment created with Codex's bundled Python 3.12.14; `python3.12` was not on its PATH. Then, from the repository root:

```bash
source .venv/bin/activate
python -m pip install --cache-dir data/pip-cache -r requirements.lock.txt
python -m app.tools.init_db
```

Start the API in one activated terminal:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Start the worker in another activated terminal:

```bash
python -m app.worker
```

Open [API documentation](http://127.0.0.1:8000/docs). The private local session token in `data/backend/local-session.json` authorizes protected routes; never share or commit it. The demo below reads it internally without displaying it:

```bash
python -m scripts.backend.demo_refresh
pytest -q
```

See [the full backend guide](docs/backend/README.md) for setup, polling, migration/recovery behaviour, security and troubleshooting.

## Implemented endpoints

| Method | Path | Behaviour |
| --- | --- | --- |
| GET | `/health` | Real API/database/worker readiness and safe config presence |
| GET | `/api/v1/source-boards` | Configured sources and validation/refresh state |
| POST | `/api/v1/source-boards/{board_id}/refresh` | Durable, idempotent task creation |
| GET | `/api/v1/source-boards/{board_id}/jobs` | Stored current jobs with bounded pagination |
| GET | `/api/v1/tasks/{task_id}` | Persisted status, step, attempts, lease, errors and result |
| GET | `/api/v1/tasks/{task_id}/events` | Redacted task history |
| GET | `/api/v1/artifacts/{artifact_id}` | Owned, integrity-verified private bytes |

All mutations require Idempotency-Key. Repeated keys replay the original response; changed requests conflict. Different keys cannot create duplicate active refreshes for one board. Read routes do not fetch live data.

The worker is singleton by default, uses persisted leases/heartbeats, retries only bounded safe reads and recovers abandoned safe tasks. Possible-send simulations become OUTCOME_UNKNOWN and never retry automatically. No live submission handler exists.

## Configuration and credentials

Copy `.env.example` only if no populated `.env` already exists, then edit locally with owner-only permissions. Keep `.env`, session files, databases, browser state, PDFs and private reports out of Git.

- `GROQ_API_KEY`: local Groq credential, never returned by the API.
- `GROQ_MODEL`: fixed to `openai/gpt-oss-120b`; no fallback or Gemini integration.
- `CAREERLENS_DATA_DIR`: shared local API/worker data directory, default `data/backend`.
- `CAREERLENS_ALLOWED_ORIGINS`: explicit permitted local origins; no wildcard.
- Lease/heartbeat/poll/retry intervals are documented in `.env.example`.

Groq is not called by Phase 2 task processing or normal tests. Its Phase 1 live smoke test remains opt-in and requires confirmation of a Free-plan organization with no paid billing. Never assume a chat subscription provides API quota.

## Evidence and contracts

- [Phase 2 execution report](docs/backend/phase-2-report.md)
- [Backend operation guide](docs/backend/README.md)
- [Implemented and planned contract status](docs/contracts/implementation-status.md)
- [Phase 1 feasibility report](docs/feasibility/README.md)

`contracts/openapi.json` comes from the implemented app. AI schemas are explicitly marked defined-only; example records are synthetic. Original Word documents remain external.

To regenerate and check:

```bash
python -m app.tools.export_contracts
python -m scripts.feasibility.check_repository_safety
```

The safety check scans staged files and reachable history for Groq patterns and configured Groq/local-session secrets. It never prints credential values.

## Phase 1 tooling and limits

The original `scripts/feasibility/` probes remain available for environment, public feed, read-only form, Groq and PDF checks. Browser setup on a fresh machine:

```bash
PLAYWRIGHT_BROWSERS_PATH="$PWD/data/playwright" python -m playwright install chromium
```

No browser is needed for the Phase 2 source-refresh worker. Real employer form submission and hCaptcha handling remain unverified. This is one local candidate/source and one worker, not multi-user production hosting. macOS ARM64 was validated; other platforms need their own checks.

Review Phase 2 before starting the next phase. UI appearance and frontend work remain deferred until the backend workflows are operational. See [CONTRIBUTING.md](CONTRIBUTING.md) for collaboration.
