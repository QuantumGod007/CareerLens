# Local operation guide

This local backend implements source refresh, persistent tasks, polling, migrations and private artifacts. Phase 3 serves the vanilla website at `/`; full resume/application workflows remain unfinished.

For everyday development, run **`python -m app.dev`** after [installing dependencies](../../README.md#getting-started). It initializes/upgrades the database, owns the API and separate worker, and stops both on Ctrl+C. Open [CareerLens](http://127.0.0.1:8000/); browser pairing is automatic, without copying the private API token. The manual commands below remain supported.

## Setup

Use Python 3.12 and the locked dependencies. The validated Mac uses the existing Codex-bundled Python 3.12.14 environment; `python3.12` was not on its PATH. After the README setup, activate the environment if using the shorter commands below:

```bash
source .venv/bin/activate
python -m pip check
python -m app.tools.init_db
```

Initialization runs all Alembic upgrades, preserves existing data, seeds the supported board once and creates a persistent owner-only local-session file. Re-running it is safe. It does not delete/recreate the database. `.env` and `data/` are ignored; copy the placeholder `.env.example` only if no populated local file already exists.

Initialization is optional when using `app.dev`, which performs it automatically. The launcher binds only to `127.0.0.1`, disables proxy-header trust and refuses an occupied port or an already running worker. Use `python -m app.dev --port 8001` to choose another port; it configures matching local browser origins for its API and worker. Ctrl+C or SIGTERM closes the API and lets the worker finish its bounded safe read before stopping. After a hard kill, wait for the old worker lease to expire.

The source-refresh worker needs no browser. Browser tests and feasibility probes use Chromium in ignored `data/playwright/`; install it with the [README test command](../../README.md#tests).

## Configuration

Copy `.env.example` only if no populated `.env` already exists, then edit locally with owner-only permissions. Never commit `.env`, session files, databases, PDFs, browser state or private reports. These paths are excluded by `.gitignore`.

| Variable | Purpose / default |
| --- | --- |
| `GROQ_API_KEY` | Optional local Groq credential; never returned by the API |
| `GROQ_MODEL` | Fixed to `openai/gpt-oss-120b`; no model/provider fallback or Gemini integration |
| `CAREERLENS_DATA_DIR` | Shared API/worker directory; default `data/backend` |
| `CAREERLENS_ALLOWED_ORIGINS` | Explicit local origins, normally `http://127.0.0.1:8000,http://localhost:8000`; no wildcard |
| `CAREERLENS_LEASE_SECONDS` | Worker lease, default 15 seconds |
| `CAREERLENS_HEARTBEAT_SECONDS` | Heartbeat interval, default 2 seconds; must be less than half the lease |
| `CAREERLENS_POLL_SECONDS` | Worker queue poll interval, default 0.5 seconds |
| `CAREERLENS_RETRY_SECONDS` | Safe-read retry base interval, default 5 seconds |

Groq is not called by the website, source worker or normal tests. Its live Phase 1 smoke test is opt-in and requires confirmation of a Free-plan organization with no paid billing. The script cannot enforce the external billing tier; a chat subscription does not establish API quota.

## Browser sessions and stored listings

Opening the page establishes a separate opaque **HttpOnly, SameSite=Strict** cookie, scoped to `/api/v1`, with a 12-hour lifetime. JavaScript cannot read it; no credentials go into URLs, localStorage, sessionStorage or frontend assets. Pairing requires a loopback peer, the exact allowed origin including port, browser fetch metadata and a JSON request with a custom header. Cookie API requests enforce the same origin; mutations enforce the JSON/header guard. Different websites and local ports cannot pair or reuse this session. API restart revokes its in-memory sessions; page reload reconnects automatically. Disconnect revokes and clears the current capability. The persistent API token is never returned by pairing.

FastAPI serves only `web/` as static frontend content, using a restrictive Content Security Policy. The UI uses HTML, CSS and small JavaScript modules with no npm installation or build. External job content uses text nodes and validated Lever destinations, and employer links open with `noopener noreferrer`. Opening a link does not prepare or submit an application.

Filters apply to loaded listings rather than AI/candidate matching. Details contain persisted summary metadata, not a fabricated full description. Stored listings may have closed; check the employer website for current availability. Private artifacts remain API-only until resume workflows exist.

Refresh double clicks produce one logical request. Retrying a lost response reuses its key and exact payload. The UI displays backend progress and stops polling at terminal outcomes, slows checks while hidden, and pauses after 150 checks or three connection failures. Use **Check status** to resume. Failed refreshes keep and label earlier stored listings. Network/server errors preserve loaded results. Activity tracks the current page's task IDs; after reload, look up a known ID to retrieve persisted status and events.

## Start two processes

Terminal 1, after activation:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
```

Terminal 2, from the same root after activation:

```bash
python -m app.worker
```

Open [the API docs](http://127.0.0.1:8000/docs). `/health` is public to the local boundary. Protected routes accept `X-CareerLens-Token` for scripts/Swagger, or the guarded browser cookie for the website. The token and stable local session ID are stored privately in `data/backend/local-session.json`; use that token locally in Swagger's Authorize dialog. Never commit, share, paste into chat or put it in a URL. Browser pairing never returns this persistent token. There is no multi-user login or cloud auth system.

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
# After staging intended files:
python -m scripts.feasibility.check_repository_safety
```

The full suite uses temporary databases, synthetic fixtures and mocked source calls, including a process-kill recovery test. It requires no paid services or employer form. Phase 1 live smoke tools remain opt-in. `contracts/openapi.json` must match the implementation; regeneration does not make planned endpoints implemented.

`contracts/openapi.json` is exported from the implemented app. AI schemas are defined-only and example records are synthetic; see [contract status](../contracts/implementation-status.md). The safety utility scans staged bytes and all reachable Git history for Groq patterns and the configured Groq/local-session credentials, without printing their values.

The recorded Phase 3 baseline is 118 passing tests: all 84 Phase 1–2 regressions and 34 additional checks, including 19 controlled Chromium UI scenarios. There were zero failures/skips and one existing Starlette TestClient deprecation warning. The separate live Chrome run refreshed 35 real Lever listings through the API, SQLite and worker; desktop/mobile layouts and automatic session reload passed. These are recorded observations, not guarantees of current listing availability. Earlier results remain in the [Phase 1 report](../feasibility/README.md), [Phase 2 report](phase-2-report.md) and their linked JSON evidence.

With CareerLens running, reproduce the browser-to-live-source check using:

```bash
python -m scripts.backend.demo_web --chrome
```

It uses installed Google Chrome in an isolated context; omit `--chrome` for test Chromium. It clicks Refresh, checks live completion and stored cards, verifies session reload, and captures sanitized desktop/mobile screenshots under ignored `data/phase3/`, alongside `live-browser.json`. It never opens an employer form or submits an application. Normal UI tests use controlled fixtures and do not contact Lever or Groq.

The original feasibility utilities remain under `scripts/feasibility/`. Run the [PDF probe](../feasibility/pdf-validation.md) before the controlled form; both use synthetic data:

```bash
python -m scripts.feasibility.check_environment
python -m scripts.feasibility.test_pdf_pipeline
python -m scripts.feasibility.test_controlled_form
```

Common issues: missing session/schema means initialization is needed; 401 means the local token is missing/wrong; 403 indicates origin/host rejection; 409 indicates stale revision/idempotency conflict; a non-ready worker may be stopped, expired or using another data directory. Source outage/timeouts appear in task polling with safe error codes. Do not blindly delete a stuck task or possible-send record.

In the browser, use **Connect** after a 401, open the correct local address after a 403, and reload the source before a new action after a 409. If the API is unreachable or the worker is stopped, start the combined `app.dev` command after stopping any conflicting instance.

Private artifacts have opaque IDs, ownership checks, atomic file writes and hash verification. The utility cleans abandoned temporary writes only. Final orphan-file reconciliation after a crash between rename and DB commit is not implemented; do not manually remove referenced files. No reset endpoint or destructive reset command exists.

macOS ARM64 was tested. These shell commands target macOS/Linux; Linux was not separately validated in this run. Native Windows is not validated: owner permissions, `O_NOFOLLOW` and process semantics need a separate review; WSL is the practical starting point. This remains a single-user local prototype, not a hardened multi-tenant service.
