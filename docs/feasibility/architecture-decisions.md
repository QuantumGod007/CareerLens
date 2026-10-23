# Architecture decisions after Phase 1

Historical decision record. “Still unimplemented” and proposed changes describe the Phase 1 checkpoint. Later backend and browser work is tracked in [contract status](../contracts/implementation-status.md); the rationale and remaining product requirements here are retained.

Evidence supports continuing with the proposed local modular backend. Import/connection probes do not establish implemented production guarantees.

| Area | Decision | Still unimplemented |
| --- | --- | --- |
| API | FastAPI with validated Pydantic contracts | Routes, origin/session controls and errors |
| Database | SQLite/SQLAlchemy for one local candidate | Schema, immutable versions, WAL/foreign keys and concurrency checks |
| Worker | One separate durable process | Leasing, checkpoints, heartbeat and recovery |
| Discovery | Validated Drivetrain public feed | Closure/re-fetch checks, snapshots and broader matching evaluation |
| AI | Groq only, typed boundary, no fallback | Provenance, extraction/enhancement, semantic verification and caching |
| Browser | Known hosted form in dedicated context | Missing answers, verification intervention, uploads and receipt signals |
| Files | Private local storage and network-disabled renderer | Opaque downloads, ownership checks, atomic writes and reset |
| Submission | Exact-payload approval and OUTCOME_UNKNOWN | Consent, unique send ownership, duplicate and crash tests |

## Dry run and live run lifecycle

The original unique application plus terminal dry-run state can block a later real application. Recommended contract amendment: keep one canonical application per candidate and destination posting, with separate preparation runs. A dry run can finish terminally without claiming a live send. An explicit later review/live run under the same canonical application re-fetches the job/form and needs fresh approval. Enforce at most one live submit owner. Possible sends block automatic replay until reconciliation.

This is a proposed contract change, not an implemented schema. Define the final entities/endpoints before Phase 2. Do not delete or re-key an application to escape duplicate protection.

## Recovery and approval

Define a safe-step retry command with expected revision, failed step, limits and an event reason. Document `/resume` separately for answered questions/manual intervention; it must not imply retrying a possible submission. Crashes at or after sending become `OUTCOME_UNKNOWN`. Cancellation and approval need concurrency guards.

Bind approval to profile version, JD snapshot/hash, exact PDF bytes, answers and form metadata. Changes invalidate consent. Exclude transient browser tokens from business hashes; do not send those tokens or credentials to the model.

## Future AI support

Keep SDK calls behind typed inputs/results and classified errors. A future authorized provider can implement the same schemas with output normalization, cooldowns and versioned cache keys. Introduce routing only after cost/privacy rules exist. No Gemini, provider switching or key rotation is implemented. Models never gain submission authority or unrestricted executable selectors.

## Contract and external limits

The six Word documents were reviewed earlier in the conversation. The repository initially contained only README, CONTRIBUTING and gitignore. No OpenAPI/AI contracts existed. Explicit checks of `contracts/openapi.json`, `contracts/ai_schemas.json`, `contracts/examples.json` and `REFERENCES.md` at the expected documentation-handoff paths returned FileNotFoundError. Obtain or reconstruct/review these in Phase 2; no schema parity is claimed.

hCaptcha is present on the inspected employer form, so autonomous submission remains unresolved. Plan manual intervention and retain the controlled receiver for rehearsals. Public job reads do not authorize employer submission APIs.

[SQLAlchemy's SQLite documentation](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html) identifies transaction/foreign-key details requiring configuration and tests. [FastAPI's background tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/) do not establish durable recovery; retain the persisted separate-worker design.

Phase 2 begins only after this report is reviewed. No production API, schema, worker or frontend was created.
