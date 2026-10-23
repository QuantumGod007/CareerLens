# Contract implementation status

Version 0.3.0, 23 October 2026. Phase 3 adds the local browser session routes below; existing domain contracts and database migrations are unchanged. The original machine-readable companions were unavailable. The Phase 2 contracts were reconstructed from document 04, the six reviewed project documents and Phase 1 architecture decisions.

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
| POST | /api/v1/browser-session | Exact-origin loopback browser pairing with a separate HttpOnly cookie; no persistent token disclosure |
| POST | /api/v1/browser-session/disconnect | Revoke and clear the browser capability |

UUIDs and UTC timestamps are serialized explicitly. Unknown values remain null. Domain commands reject extra fields and type coercion. Source refresh requires Idempotency-Key. OpenAPI describes alternative persistent header-token or browser-cookie authorization. Cookie access additionally requires loopback peer and same-origin browser metadata; cookie mutations and pairing require the exact Origin, JSON and X-CareerLens-Local header. Errors use the existing common envelope; invalid request values are never reflected. Static `/` and `/web/` routes are excluded from the API schema; `/docs` remains available. Artifact downloads are still API-only in this phase.

## Defined future contracts

`contracts/ai_schemas.json` contains named JSON Schema definitions for ProfileDraft, StructuredJD, TailoredContent and VerificationResult, marked `defined-only`. Refer to the named definitions under `$defs`. Source spans, unknown values, source fact IDs, before/after reasons and uncertainty are represented. The schemas do not prove source-span accuracy, entailment or factual correctness; those checks belong to future services. The current typed Groq smoke-test boundary remains in Phase 1 and is not duplicated.

`contracts/examples.json` contains synthetic examples. IDs in examples do not imply existing tasks or candidate records.

The following document-04 endpoints remain planned and are deliberately absent from the running OpenAPI: profile upload/read/correction/confirmation, searches/read/role decisions, application creation/list/detail, answers/resume/approval/cancel/reconcile. No application-submission route or handler exists.

## Original product specifications

The six original Word documents remain external in `CareerLens_Documentation/`. They define the product vision and requirements. This status page distinguishes implemented routes from future contract definitions; neither replaces the originals:

- `01_PRD.docx` — product requirements.
- `02_SRS.docx` — software requirements.
- `03_Architecture_and_UML.docx` — architecture and UML.
- `04_API_and_AI_Specifications.docx` — API and AI specifications.
- `05_Tech_Stack_and_Setup.docx` — technology choices and setup.
- `06_Saturday_Implementation_Plan.docx` — original implementation plan.

Their absence from Git does not make them obsolete. Historical validation and implementation results are retained in the [Phase 1 report](../feasibility/README.md) and [Phase 2 report](../backend/phase-2-report.md).

## Contract changes and unresolved requirements

- One canonical Application owns multiple PreparationRuns. A terminal dry run does not block a later explicit review run. Possible live sends remain an irreversible application-level barrier.
- Safe retries are implemented only for source refresh. A future application preparation retry command still needs its final payload/endpoint definition.
- Workflow/approval/reconciliation guards exist as domain foundations for controlled tests. They are not a complete application review or employer receipt implementation.
- Profile content is immutable; confirmation metadata can change. Job/Resume/Fact content and terminal preparation runs are protected by SQLite triggers. Historical versions cannot be deleted through normal writes.
- A separate SourceListing membership table represents the latest board generation while immutable JobSnapshots retain history. Failed refreshes preserve the previous generation; a successful empty refresh publishes an honest empty generation.
- Real resume extraction, complete AI payload evaluation, candidate search ranking, browser preparation, manual CAPTCHA intervention and destination receipt semantics remain later-phase services.
