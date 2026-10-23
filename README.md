# CareerLens

CareerLens is a local job application assistant being built for students and freshers. The intended workflow preserves candidate facts and requires approval before submission.

## Current status

Phase 3 adds a working local website to the FastAPI, SQLite and separate-worker backend. **Overview** shows real readiness and source counts; **Explore Jobs** supports stored listings, filters, incremental loading, details and official employer links; **Activity** shows actual task progress and events. The Chrome → API → worker → live Drivetrain Lever workflow completed with **35 real listings**.

**Resume upload, candidate matching, AI tailoring and employer preparation/submission remain unfinished.** Their navigation labels say Coming Soon. No employer application was submitted; Phase 4 has not started. Filters search loaded listings only. Details show stored summary metadata; full descriptions remain on the employer website. Private artifact downloads remain API-only until resume workflows exist.

The suite passes **118 tests**: all 84 existing regressions plus 34 Phase 3 checks, including 19 controlled Chromium UI scenarios. Zero failures/skips; one existing Starlette test-client deprecation warning remains. No frontend framework, npm build, cloud service or paid API was added. Historical Phase 1–2 reports are preserved below.

## Run locally

Use Python 3.12 to create `.venv`. This Mac already has the environment made with Codex's bundled Python 3.12.14. From the repository root:

```bash
source .venv/bin/activate
python -m pip install --cache-dir data/pip-cache -r requirements.lock.txt
python -m app.dev
```

Open [CareerLens](http://127.0.0.1:8000/). The command safely initializes/upgrades the existing database, starts the API and separate worker, and connects the browser automatically. **Ctrl+C stops both processes.** For everyday use on this Mac, activation is optional:

```bash
.venv/bin/python -m app.dev
```

If port 8000 is occupied, stop the existing instance or use `python -m app.dev --port 8001`. The launcher refuses to interfere with another running worker. After a hard kill, wait for its lease to expire before restarting. It binds only to `127.0.0.1` and disables proxy-header trust.

The original separate-process commands remain available:

```bash
python -m app.tools.init_db
# Terminal 1
uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
# Terminal 2
python -m app.worker
```

## Browser connection and security

Opening the page establishes a separate opaque **HttpOnly, SameSite=Strict** cookie, scoped to `/api/v1`, with a 12-hour lifetime. JavaScript cannot read it; no credentials go into URLs, browser storage or frontend assets. Pairing requires a loopback peer, the exact allowed origin including port, browser fetch metadata and a JSON request with a custom header. Cookie API requests enforce the same origin; mutations enforce the JSON/header guard. Different websites and local ports cannot pair or reuse this session. API restart revokes its in-memory sessions; page reload reconnects automatically. Disconnect revokes and clears the current capability.

The persistent token in private `data/backend/local-session.json` still authorizes scripts and [API documentation](http://127.0.0.1:8000/docs) through `X-CareerLens-Token`. Browser pairing never returns it. Keep this single-user workspace on loopback. Existing host/origin checks, artifact ownership, idempotency and worker leases remain in force.

Refresh double clicks produce one logical request. Retrying a lost response reuses its key and exact payload. Polling stops on terminal outcomes, slows while the page is hidden and pauses after 150 checks or three connection failures. Use **Check status** to resume. Failed refreshes keep and label earlier stored listings. Activity tracks this page's task IDs; after reload, look up a known ID to retrieve persisted status and events.

## Verify

Install Chromium once for browser tests on a fresh machine:

```bash
PLAYWRIGHT_BROWSERS_PATH="$PWD/data/playwright" python -m playwright install chromium
```

Run offline regressions, including controlled UI fixtures:

```bash
pytest -q
```

With CareerLens running, opt into the genuine public-source demos separately:

```bash
python -m scripts.backend.demo_refresh
python -m scripts.backend.demo_web --chrome
```

The second command uses installed Google Chrome in an isolated context; omit `--chrome` for test Chromium. It clicks Refresh, verifies live completion and stored cards, tests session reload, and captures sanitized desktop/mobile screenshots under ignored `data/phase3/`. It never opens an employer form or submits an application. Normal tests use fixtures and do not contact Lever or Groq.

See [the backend guide](docs/backend/README.md) for manual API use, migrations and recovery. If the API is unreachable or Worker says Stopped, start `app.dev`. A 401 needs Connect; a 403 needs the correct local address; a 409 needs source reload before a new action. Network/server errors preserve loaded results.

## Implemented endpoints

| Method | Path | Behaviour |
| --- | --- | --- |
| GET | `/health` | Real API/database/worker readiness and safe config presence |
| GET | `/api/v1/source-boards` | Configured sources and validation/refresh state |
| POST | `/api/v1/source-boards/{board_id}/refresh` | Durable, idempotent task creation |
| GET | `/api/v1/source-boards/{board_id}/jobs` | Stored current jobs with bounded pagination |
| GET | `/api/v1/tasks/{task_id}` | Persisted task status, progress and result |
| GET | `/api/v1/tasks/{task_id}/events` | Redacted task history |
| GET | `/api/v1/artifacts/{artifact_id}` | Owned, integrity-verified private bytes |
| POST | `/api/v1/browser-session` | Same-origin loopback pairing; never returns the API token |
| POST | `/api/v1/browser-session/disconnect` | Revoke and clear the browser session |

Source refresh requires Idempotency-Key. Repeated keys replay the original response; changed requests conflict. Different keys cannot create duplicate active refreshes for one board. Read routes do not fetch live data.

The worker is singleton, uses persisted leases/heartbeats, retries only bounded safe reads and recovers abandoned safe tasks. Possible-send simulations become OUTCOME_UNKNOWN and never retry automatically. No live submission handler exists.

## Configuration and credentials

Copy `.env.example` only if no populated `.env` already exists, then edit locally with owner-only permissions. Keep `.env`, session files, databases, browser state, PDFs and private reports out of Git.

- `GROQ_API_KEY`: local Groq credential, never returned by the API.
- `GROQ_MODEL`: fixed to `openai/gpt-oss-120b`; no fallback or Gemini integration.
- `CAREERLENS_DATA_DIR`: shared local API/worker data directory, default `data/backend`.
- `CAREERLENS_ALLOWED_ORIGINS`: explicit permitted local origins; no wildcard.
- Lease/heartbeat/poll/retry intervals are documented in `.env.example`.

Groq is not called by the website, source worker or normal tests. Its Phase 1 live smoke test remains opt-in and requires confirmation of a Free-plan organization with no paid billing. Never assume a chat subscription provides API quota.

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

The website lives in `web/` as HTML, CSS and small JavaScript modules, served only by FastAPI with a restrictive Content Security Policy. External content uses text nodes and validated Lever destinations. No frontend build is needed. See [CONTRIBUTING.md](CONTRIBUTING.md) for the lightweight development workflow.
