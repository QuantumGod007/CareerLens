# Phase 2 execution report

Historical results from the end of Phase 2, before the web interface. The recorded test results and technical limitations are preserved; see the [operation guide](README.md) and [current contract status](../contracts/implementation-status.md) for later changes.

Executed 23 October 2026, India Standard Time. Phase 2 backend foundation is implemented and tested. Phase 3 has not started. No employer application, CAPTCHA action, AI resume processing or UI was implemented or executed.

## Baseline and environment

Fetched `main` and confirmed merged Phase 1 at `9eadb15`. The original 41 tests passed before implementation. Work is isolated on `codex/phase-2-backend-foundation`; original scripts/fixtures remain intact. The repository-safety utility was extended to scan the new configured local session token as well as Groq credentials.

The existing Python 3.12.14/macOS ARM64 environment was retained. Added only Uvicorn 0.54.0 and Alembic 1.20.1, plus Click/Mako transitive dependencies. Existing Phase 1 package versions did not change. Locked installation and `pip check` succeeded. Other platforms were not separately validated.

## Implemented backend and endpoints

FastAPI has startup/schema validation, configuration, local-session authorization, strict commands, typed responses, correlated structured errors, metadata-only logging and shutdown cleanup. Persistence, queue, workflow, artifacts and the Lever adapter are separate modules.

Seven actual endpoints are implemented: health; board listing; board refresh; persisted board jobs; task status; task events; and owned artifact download. See [contract status](../contracts/implementation-status.md) for exact paths. Planned resume/search/application endpoints are deliberately absent. Generated OpenAPI matches the actual app in an automated comparison. AI schemas are reconstructed definitions, not implemented services.

## Database and migrations

Three Alembic revisions create and upgrade 18 tables:

Candidate, ProfileVersion, Fact, SourceBoard, JobSnapshot, SourceListing, Search, SearchResult, ResumeVersion, Application, PreparationRun, QuestionAnswer, Approval, Task, Event, Artifact, IdempotencyRecord and WorkerHeartbeat.

SQLite uses foreign keys, WAL and a 5000 ms busy timeout. UUIDs, UTC timestamps, unique keys and revision fields establish versioned foundations. Job/Resume/Fact history and profile content cannot be overwritten; historical versions cannot be deleted through normal writes. Events are append-only. Terminal preparation runs cannot be changed. Confirmation metadata is distinct from immutable profile content.

Fresh migrations, repeat initialization and upgrade of a previously initialized database were tested without destructive recreation. The real development database also upgraded additively: 35 old snapshots were preserved, and the v2 pipeline created 35 complete metadata snapshots, with 35 current memberships and 70 historical rows. Old records were not silently rewritten.

## Worker and workflow reliability

The separate process obtains a singleton lease, claims tasks atomically, renews heartbeats during external work and publishes results only with current ownership. Short write transactions serialize commands; no HTTP call holds a database transaction. Safe transient source failures wait/retry within a three-claim maximum. Permanent schema/destination errors fail explicitly. Empty source results publish an empty current generation while retaining history.

Expired safe tasks recover; stale owners cannot publish. A separate child process was killed during a controlled source-read stage and a new worker completed the task after expiry on attempt two. A handler that outlives its initial lease verifies heartbeat renewal. Graceful shutdown finishes the current bounded safe read and stops new claims.

Controlled domain tests cover state transitions, stale revisions, cancellation races, payload-bound approval, owner checks and approval invalidation. A terminal dry-run run permits a later explicit review run under the same canonical application. A possible-send crash changes the run/application to OUTCOME_UNKNOWN, blocks automatic retry and requires evidence for reconciliation. There is no live submit route or handler, and no external send occurred in those simulations.

## Real end-to-end demonstration

The separate Uvicorn API and `python -m app.worker` processes ran on the local machine. A real HTTP refresh request returned 202 and persisted a task. The worker fetched the configured public Lever feed and committed genuine snapshots. Polling returned SUCCEEDED on attempt one with 35 listings; the jobs endpoint returned those stored records. Replaying the same key returned the original task.

Final v2 run task: `2c4cc6d0-5ba4-4595-ada5-bce5730b22ab`. Evidence: [execution-evidence.json](execution-evidence.json). API and worker were stopped and the API restarted; 35 jobs remained available and health correctly reported the stopped worker as not ready. Services were subsequently stopped cleanly.

Reproduce after activating `.venv`:

```bash
python -m app.tools.init_db
# Terminal 1
uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
# Terminal 2
python -m app.worker
# Terminal 3: trigger, poll, verify replay and read persisted results
python -m scripts.backend.demo_refresh
```

The helper reads the local token internally and never prints it. Detailed manual API instructions are in [the operation guide](README.md).

## Security and tests

Persistent idempotency handles identical replays, payload conflicts, concurrent identical requests, concurrent different-key business duplicates and API restart. Revision guards reject stale writes. Configured source identities/hosts are checked, arbitrary caller URLs are not accepted, and GET jobs never fetches remotely.

Protected routes require a private persistent local token. Host/origin/cross-site checks reject untrusted browser requests. No wildcard write origin is enabled. Artifact IDs are opaque; ownership, path, symlink, size and hash checks precede download. Writes use private temporary files and atomic rename. Known credential-like content is rejected. Errors/logs omit request bodies, exception messages, answers, tokens and keys. Health reports key presence only.

The full suite has 84 tests: 41 existing Phase 1 regressions and 43 backend checks. All passed, with zero failures/errors/skips. No automated check is blocked or depends on paid/live employer services. One Starlette TestClient deprecation warning remains; no dependency replacement was needed. JUnit is retained locally under `data/backend/phase2-tests.xml`. The separate live source demonstration also passed.

## Delivery and limitations at this checkpoint

The branch is pushed for draft review; exact commits/PR status are recorded in [the delivery record](#delivery-record). It is not merged automatically. Populated `.env`, local tokens, databases, browser state and raw artifacts are excluded from Git. Index/history scanning runs before publication without printing credentials.

Limitations: one local user/source/worker; no production auth, cloud hosting, full candidate services, AI resume pipeline, application form adapter, CAPTCHA handling or employer submission. Approval/reconciliation tests exercise domain guards, not complete real form/receipt semantics. Final orphan-file reconciliation after a file/DB crash is pending; only aged temporary writes are cleaned. Native Windows/Linux runtime validation is pending. Live listings and quota availability can change.

A temporary vanilla interface could immediately connect to health, board refresh, stored listings, task/events and authorized artifacts. Resume upload, matching, enhancement and application screens require later backend services. At this checkpoint, frontend work was deferred under the backend-first decision until Phase 2 review. Phase 3 subsequently delivered the local web interface; the resume and application services still require later implementation.

## Delivery record

Historical publication notes, preserved from the original handoff. PR status and next-phase statements below describe that checkpoint, not the current repository. Both PRs were subsequently merged; see the current [README](../../README.md).

Recorded 23 October 2026, India Standard Time.

- Baseline: merged Phase 1 on `main`, commit `9eadb15f87a753511f3a62014d6c333084d20f45`.
- Branch: `codex/phase-2-backend-foundation`.
- Backend/test/report implementation commit: `866bda17ad58ba54f450beea392929fcd52c5d0d`.
- Push succeeded and established the branch upstream. No force push or branch deletion occurred.
- [Draft pull request 2](https://github.com/QuantumGod007/CareerLens/pull/2) targets `main`. It remains unmerged.
- Verification: 84 tests passed (41 original, 43 backend), no failures/errors/skips; live source API/worker/persistence and restart checks passed. One TestClient deprecation warning is documented.
- Credential scan: staged files and reachable history passed before publication, including checks for configured Groq and local-session credentials. No credential values were printed.
- Excluded from Git: populated `.env`, local session file, SQLite/WAL files, PDFs, browser state, private raw reports and virtual environment.

This handoff note is recorded in a separate documentation commit after the verified backend push and PR creation. Services were stopped cleanly after the demonstrations. Phase 3 has not started.
