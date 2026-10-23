# Contract implementation status

Version 0.2.0, 23 October 2026. The original machine-readable companions were unavailable. These contracts were reconstructed from document 04, the six previously reviewed project documents and the Phase 1 architecture decisions.

`contracts/openapi.json` is exported from the actual FastAPI application using `python -m app.tools.export_contracts`. An automated comparison prevents drift. It contains only these implemented operations:

| Method | Endpoint | Implemented behaviour |
| --- | --- | --- |
| GET | /health | Database availability, API readiness, live worker lease/readiness and safe config presence |
| GET | /api/v1/source-boards | Configured sources, revisions and actual refresh/validation timestamps |
| POST | /api/v1/source-boards/{board_id}/refresh | Transactional durable enqueue with Idempotency-Key and optional expected_revision |
| GET | /api/v1/source-boards/{board_id}/jobs | Bounded/paginated current stored listings; no network fetch |
| GET | /api/v1/tasks/{task_id} | Persisted state, attempts, progress, lease, error code and result reference/statistics |
| GET | /api/v1/tasks/{task_id}/events | Up to 100 chronological redacted task events |
| GET | /api/v1/artifacts/{artifact_id} | Owned, hash-verified bytes downloaded as an attachment |

UUIDs and UTC timestamps are serialized explicitly. Unknown values remain null. Commands reject extra fields and type coercion. All implemented mutations require Idempotency-Key. Local session token protection is described in the OpenAPI security scheme. Errors use a common code/message/retryable/details/correlation_id envelope; invalid request values are never reflected.

## Defined future contracts

`contracts/ai_schemas.json` contains named JSON Schema definitions for ProfileDraft, StructuredJD, TailoredContent and VerificationResult, marked `defined-only`. Refer to the named definitions under `$defs`. Source spans, unknown values, source fact IDs, before/after reasons and uncertainty are represented. The schemas do not prove source-span accuracy, entailment or factual correctness; those checks belong to future services. The current typed Groq smoke-test boundary remains in Phase 1 and is not duplicated.

`contracts/examples.json` contains synthetic examples. IDs in examples do not imply existing tasks or candidate records.

The following document-04 endpoints remain planned and are deliberately absent from the running OpenAPI: profile upload/read/correction/confirmation, searches/read/role decisions, application creation/list/detail, answers/resume/approval/cancel/reconcile. No application-submission route or handler exists.

## Contract changes and unresolved requirements

- One canonical Application owns multiple PreparationRuns. A terminal dry run does not block a later explicit review run. Possible live sends remain an irreversible application-level barrier.
- Safe retries are implemented only for source refresh. A future application preparation retry command still needs its final payload/endpoint definition.
- Workflow/approval/reconciliation guards exist as domain foundations for controlled tests. They are not a complete application review or employer receipt implementation.
- Profile content is immutable; confirmation metadata can change. Job/Resume/Fact content and terminal preparation runs are protected by SQLite triggers. Historical versions cannot be deleted through normal writes.
- A separate SourceListing membership table represents the latest board generation while immutable JobSnapshots retain history. Failed refreshes preserve the previous generation; a successful empty refresh publishes an honest empty generation.
- Real resume extraction, complete AI payload evaluation, candidate search ranking, browser preparation, manual CAPTCHA intervention and destination receipt semantics remain later-phase services.
