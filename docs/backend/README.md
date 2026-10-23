# Local operation guide

The local backend serves the vanilla website at `/`, with source refresh, durable tasks, private artifacts and the complete Phase 4 Resume Studio. Employer application preparation/submission remains unfinished.

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

Source refresh and profile/JD extraction need no browser. Resume PDF rendering, browser tests and feasibility probes use Chromium in ignored `data/playwright/`; install it with the [README test command](../../README.md#tests).

## Configuration

Copy `.env.example` only if no populated `.env` already exists, then edit locally with owner-only permissions. Never commit `.env`, session files, databases, PDFs, browser state or private reports. These paths are excluded by `.gitignore`.

| Variable | Purpose / default |
| --- | --- |
| `GROQ_API_KEY` | Local Groq credential for consented resume wording; never returned by the API |
| `GROQ_MODEL` | Primary stays `openai/gpt-oss-120b`; only the bounded Groq 20B fallback below is permitted |
| `CAREERLENS_DATA_DIR` | Shared API/worker directory; default `data/backend` |
| `CAREERLENS_ALLOWED_ORIGINS` | Explicit local origins, normally `http://127.0.0.1:8000,http://localhost:8000`; no wildcard |
| `CAREERLENS_LEASE_SECONDS` | Worker lease, default 15 seconds |
| `CAREERLENS_HEARTBEAT_SECONDS` | Heartbeat interval, default 2 seconds; must be less than half the lease |
| `CAREERLENS_POLL_SECONDS` | Worker queue poll interval, default 0.5 seconds |
| `CAREERLENS_RETRY_SECONDS` | Safe-read retry base interval, default 5 seconds |

Groq is called only after explicit Resume Studio consent, or by opt-in synthetic probes. Discovery, profile review and normal tests do not call it. Live probes require confirmation of a Free-plan organization with no paid billing. The script cannot enforce the external billing tier; a chat subscription does not establish API quota.

## Browser sessions and stored listings

Opening the page establishes a separate opaque **HttpOnly, SameSite=Strict** cookie, scoped to `/api/v1`, with a 12-hour lifetime. JavaScript cannot read it; no credentials go into URLs, localStorage, sessionStorage or frontend assets. Pairing requires a loopback peer, the exact allowed origin including port, browser fetch metadata and a JSON request with a custom header. Cookie API requests enforce the same origin; mutations enforce the JSON/header guard. Different websites and local ports cannot pair or reuse this session. API restart revokes its in-memory sessions; page reload reconnects automatically. Disconnect revokes and clears the current capability. The persistent API token is never returned by pairing.

FastAPI serves only `web/` as static frontend content, using a restrictive Content Security Policy. The UI uses HTML, CSS and small JavaScript modules with no npm installation or build. External job content uses text nodes and validated Lever destinations, and employer links open with `noopener noreferrer`. Opening a link does not prepare or submit an application.

Explore filters apply to loaded listings. Resume Studio separately searches persisted current snapshots against a confirmed profile and explicit role/filters. Explore details contain summary metadata; Studio shows the complete pinned JD and its evidence. Stored listings may have closed; check the employer website for current availability. Resume previews and downloads use protected API routes.

Refresh double clicks produce one logical request. Retrying a lost response reuses its key and exact payload. The UI displays backend progress and stops polling at terminal outcomes, slows checks while hidden, and pauses after 150 checks or three connection failures. Use **Check status** to resume. Failed refreshes keep and label earlier stored listings. Network/server errors preserve loaded results. Activity tracks the current page's task IDs; after reload, look up a known ID to retrieve persisted status and events.

## Start two processes

Resume Studio is available with either the combined launcher or these manual processes. The API and worker must share the same database, private session identity and Groq configuration.

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

### Resume Studio data and verification

Upload via the website's Resume Studio. Multipart upload is the sole exception to the browser JSON mutation rule; exact Origin, loopback peer, fetch metadata and `X-CareerLens-Local` remain required. The actual stream is bounded before multipart parsing (5 MiB plus 64 KiB overhead); the PDF itself is limited to 5 MiB/10 pages. Corrupt, encrypted, scanned-only, active-script and embedded-file PDFs are rejected. No OCR is applied. Originals stay in the private ArtifactStore and failed parsing creates no usable profile.

Ordinary internal opening destinations, GoTo/page-navigation actions, and explicit clickable HTTP(S)/email/phone links are supported. The action inspector follows additional/chained actions and rejects JavaScript, launch actions, automatic external links, external-file actions, attachments and unsupported interactive features with specific actionable error codes. It does not execute actions or rewrite originals. A benign `/OpenAction [page /Fit]` is not executable content.

PDF extraction runs in a disposable process with CPU, stream-decoding, page, text and wall-clock limits. The parent samples process-tree RSS every 0.2 seconds and kills over-budget processing (512 MiB extraction/preview, 1 GiB Chromium rendering). macOS rejects some memory rlimits, so this is monitored process isolation, not a hard kernel memory sandbox. Resource-monitor failure fails closed. Native Windows/Linux behavior remains unverified.

Local line-based extraction keeps all page text and validates each extracted fact's page/offset/source text. Unknown contact fields remain null. Review wrapped lines and section assignments. Corrections create a new immutable version with stable logical fact IDs, new version-specific row IDs and `user` provenance; untouched facts retain `extracted` evidence. Optimistic revisions reject stale edits, and every new version needs confirmation. Search/generation requires the latest confirmed profile. Historical versions remain readable; changing a profile never silently updates an old PDF.

Profile parsing defaults to `local`, without a model call. Upload can explicitly choose `parsing_mode=groq` with `ai_consent=true` and `consent_version=groq-profile-v1`. After Python validates/extracts the PDF, Groq receives only bounded text/page offsets (at most 18,000 serialized characters including candidate spans), with identified contacts masked without shifting offsets. Other personal information may remain, as the consent states. Strict `GroqProfileDraft` output selects section kinds and exact spans; the server builds `ProfileDraft`, validates bounds/text against both original and masked pages, rejects overlaps and omitted qualification context, and preserves uncovered local facts. Contact extraction stays local. Each fact records `extraction_method` (`local`, `groq` or `user`); all extracted facts still require review and confirmation.

The optional step makes one primary request and at most one eligible 20B fallback under the existing policy. Model/quota/schema/grounding failures return a clearly labelled `local_fallback` draft with no accepted model facts; text is never silently truncated. Consent, actual model, prompt/schema versions, safe diagnostics and validated stage output persist privately in the task/profile records. Stored output can recover without another request; an uncertain interrupted call falls back locally without replay. Profile and generation quota cooldowns are shared. PDF validation/extraction, default profile parsing, JD analysis and matching remain local; only opted-in profile structuring and separately consented wording/semantic verification call Groq.

Searches store the requested role, explicit optional filters and advisory role decisions. They inspect current memberships from enabled configured boards, deduplicate canonical jobs and return at most five. An empty search is successful. Snapshots carry fetch times; availability is unverified. JD analysis pins the immutable snapshot/hash and stores required/preferred skills, exact evidence spans, responsibilities, separate eligibility observations, uncertainties and pipeline version. It uses a finite reviewed vocabulary, without Groq. Unclassified requirements remain visible in the raw JD. Java/JavaScript and React/React Native remain distinct; a project is not professional experience.

Coverage is `100 × supported explicit required skills / extracted explicit required skills`; a zero denominator yields null with `no_explicit_required_skills`. Original and tailored assessments use identical confirmed qualifications and requirements. Coverage is not an ATS score or hiring probability, and eligibility is not inferred.

The Groq consent version `groq-resume-v2` identifies both permitted models and the data sent. Identified name/email/phone/profile-link facts are omitted, and embedded contact patterns are redacted. Other qualifications, such as school/employer names, can remain in the non-contact facts described by consent. No raw prompt/provider body, PDF text or private candidate data enters general logs.

AI output is a bounded patch of up to eight existing project/experience facts, with exact before/after records and supporting IDs. Conservative verb/article substitutions and section reordering are allowed; substantive token order, qualifications, technologies, numbers and qualifiers must survive. Deterministic checks complement semantic review. At most one repair is allowed; unsupported individual bullets restore exact original wording, while invalid essential statements or traces block publication. All other confirmed facts remain in the renderer.

The escaped Jinja2/Chromium template renders with scripts/network disabled. Re-parsing checks every expected fact/contact, section order, selectable text and character bounds; generated output is limited to 5 MiB/25 pages. Automated visual layout review is explicitly `not_assessed`. Downloads verify ownership/SHA-256 and use PDF attachment content types; preview is an authorized PNG raster of a verified generated page. Browser reload and backend restart restore pinned versions/history without new AI calls. Lists are bounded to 20 per page; the API supports offsets for older records.

### Groq limits and the single model fallback

Primary remains `openai/gpt-oss-120b`, using the existing key and fixed official Groq endpoint. SDK retries are disabled; each request has a 35-second timeout and bounded output (2,304 draft/repair tokens, 768 verification tokens). Verification sends only the referenced fact subset. There are at most four logical stages, one repair and one extra fallback request, for at most five HTTP attempts per generation.

Fallback is deliberately narrow: a 429 must explicitly identify the primary model, positively establish a model-specific scope (merely mentioning the model is insufficient), and identify its **requests-per-minute** limit, provide a retry-after of at most two seconds, and have sufficient reported daily requests/token capacity for a conservative byte-based input/output bound. The worker records the fallback boundary, waits the reported interval, then tries `openai/gpt-oss-20b` once. Remaining stages stay on 20B. Unknown/project-wide/organization-wide/shared limits, token limits, daily quotas, insufficient budgets, absent retry times and longer cooldowns fail without switching. Missing keys, authentication/schema errors and factual/safety failures never trigger fallback. A second model failure stops the task.

Allowlisted numeric/duration rate headers, parsed limiting metric/scope/counts and token usage are retained privately as diagnostics. Raw error messages, organization IDs, credentials and candidate data are discarded. A reported cooldown is persisted; new generation commands return 429 with `Retry-After` until it expires, including after restart. Provider failures do not automatically retry. Each successful stage records its actual model; the PDF record identifies the final draft/repair model and whether fallback occurred. Previous consent records/PDFs remain historical evidence.

Groq documents [rate-limit headers and current baseline limits](https://console.groq.com/docs/rate-limits), [project limits below organization ceilings](https://console.groq.com/docs/projects), and [strict-schema support for both models](https://console.groq.com/docs/structured-outputs). Actual headers and account settings take precedence over published defaults. The app cannot independently enforce the external account's billing plan.

The first three migrations create the original 18 domain/operational tables, add history/terminal guards, then add complete structured snapshot metadata and preservation guards. Old v1 snapshots retain their original content/hash and empty unassessed metadata; the v2 source pipeline writes new complete snapshots instead of rewriting history. The fourth additive migration (`0004_resume_studio`) adds upload, JD analysis and generation records plus durable task input/search metadata. It retains all earlier tables, snapshots and task history.

The worker takes a singleton lease and claims tasks inside short `BEGIN IMMEDIATE` transactions. Its separate heartbeat renews ownership during expensive operations. No write transaction remains open during network calls, parsing or rendering. Source transient failures use bounded WAITING retries (at most three claims); schema/destination errors fail without retry. Expired parsing/search/analysis leases can recover, and fenced transactions publish a resource and successful task together. Exhausted recovery marks the resource failed too. Groq stage outputs are persisted: a stored output can be reused, but an interrupted `_SENDING` stage fails with `PROVIDER_OUTCOME_UNKNOWN` instead of automatically repeating the call. Expired possible employer-send tasks retain the original OUTCOME_UNKNOWN barrier. The worker has no submit handler.

Ctrl+C/SIGTERM stops new claims, lets the current bounded safe read finish and marks the worker stopped. A hard kill leaves persisted ownership until expiry. Wait up to the configured lease duration before a replacement worker takes over. Health readiness is false for stopped/expired workers; database/API readiness is reported separately.

## Tests and diagnostics

```bash
pytest -q
python -m app.tools.export_contracts
# After staging intended files:
python -m scripts.feasibility.check_repository_safety
```

The full suite uses temporary databases, synthetic fixtures and mocked source calls, including a process-kill recovery test. It requires no paid services or employer form. Phase 1 live smoke tools remain opt-in. `contracts/openapi.json` must match the implementation; regeneration does not make planned endpoints implemented.

`contracts/openapi.json` is exported from the implemented app. Phase 4 uses the evidence/AI schemas and exports their actual local/Groq implementation status; example records remain synthetic. See [contract status](../contracts/implementation-status.md). The safety utility scans staged bytes and all reachable Git history for Groq patterns and the configured Groq/local-session credentials, without printing their values.

The recorded Phase 3 baseline is 118 passing tests: all 84 Phase 1–2 regressions and 34 additional checks, including 19 controlled Chromium UI scenarios. There were zero failures/skips and one existing Starlette TestClient deprecation warning. The separate live Chrome run refreshed 35 real Lever listings through the API, SQLite and worker; desktop/mobile layouts and automatic session reload passed. These are recorded observations, not guarantees of current listing availability. Earlier results remain in the [Phase 1 report](../feasibility/README.md), [Phase 2 report](phase-2-report.md) and their linked JSON evidence.

Phase 4 on 23 October 2026 passed **195 tests**, zero failures/skips, including the complete earlier suite, 27 controlled browser scenarios, actual worker-process kills during parsing/provider boundaries, strict Groq HTTP fixtures, cooldown persistence, model-fallback decisions, fabricated claims, PDF tamper/ownership and long-content retention. Two warnings remain: the existing Starlette TestClient warning and pypdf's deprecated test-only `add_js` helper.

The subsequent PDF/specification-alignment fix adds navigation/executable-action regressions, two-column/wrapped/ambiguous profile fixtures, exact-span/contact/privacy checks, consent/local-fallback/recovery tests and browser upload coverage. The expanded suite has 250 tests. A representative real resume with a benign page-fit opening destination passed local browser upload and original SHA verification without any AI call. One separate synthetic live Groq 120B profile-structuring run returned three grounded facts; the profile-specific 20B transition is covered by HTTP fixtures, not a forced live 429. No private resume text or new technical handoff file was added to Git.

The separate live Chrome run used only a synthetic candidate: 35 real Lever listings, two matching internships, correction/confirmation, pinned JD analysis, actual Groq 120B draft/verification/one repair, private PDF preview/download, unchanged coverage, browser reload and normal backend restart all passed. The one-page PDF was also visually inspected. No employer page was opened or application submitted. The initial generation hit 429 at the fourth request; its original headers were not retained, so its exact limiting dimension cannot be proved retrospectively. Later single-request diagnostics succeeded for **both 120B and 20B**, reporting 8,000 TPM and 1,000 RPD. This supports a minute-limit explanation, not a claim of daily exhaustion. 20B's live check was a small strict-schema verification probe; the fallback transition and complete 20B pipeline were tested with controlled HTTP fixtures, without deliberately exhausting live quota.

Private evidence is under ignored `data/phase4/`: `tests.xml`, `live-studio.json`, browser screenshots, synthetic PDFs and `groq-gpt-oss-{120b,20b}-limits.json`. These files contain local identifiers and stay outside Git. To reproduce the optional synthetic workflow against a running local instance:

```bash
python -m scripts.backend.demo_studio --chrome --confirm-free-plan
# After restarting app.dev with the same data directory; no new model calls:
python -m scripts.backend.demo_studio --chrome --check-restart
# Exactly one small synthetic call, with retries/fallback disabled:
python -m scripts.backend.probe_groq_limits --model openai/gpt-oss-20b --confirm-free-plan
```

The demo accepts `--base-url` for another plain loopback origin and never substitutes fixture jobs/provider output. A provider or empty-source blocker is reported as blocked. The probe accepts either permitted model; do not run it repeatedly to induce a rate-limit error.

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
