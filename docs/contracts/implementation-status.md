# Contract implementation status

Version 0.4.0, 23 October 2026. Phase 4 adds private profile review, confirmed-role searches, pinned JD analysis and verified resume generation to the existing Phase 3 browser sessions. The original machine-readable companions were unavailable. The Phase 2 contracts were reconstructed from document 04, the six reviewed project documents and Phase 1 architecture decisions.

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
| POST / GET | /api/v1/profiles | Bounded multipart PDF upload/parse task; owned paginated profile versions |
| GET / PATCH | /api/v1/profiles/{profile_id} | Traceable profile read; corrections create an immutable new version |
| POST | /api/v1/profiles/{profile_id}/confirm | Confirm the latest saved version with expected_revision |
| POST / GET | /api/v1/searches | Confirmed-profile preferred-role search task; owned paginated search history |
| GET | /api/v1/searches/{search_id} | Persisted results, explicit filters, role advisory/decision and fetch timestamps |
| POST | /api/v1/searches/{search_id}/decision | Persist an explicit continue/change-role decision and queue search |
| POST | /api/v1/searches/{search_id}/selection | Validate current result membership and queue pinned JD analysis |
| GET | /api/v1/job-analyses/{analysis_id} | Raw JD, structured evidence, skill coverage and separate eligibility observations |
| POST / GET | /api/v1/resume-generations | Consent-gated verified PDF task; owned paginated generation history |
| GET | /api/v1/resume-generations/{generation_id} | Exact profile/analysis/resume links, actual models, changes, verification, PDF checks and safe quota diagnostics |
| GET | /api/v1/resume-generations/{generation_id}/preview/{page} | Authorized PNG raster of a verified, hash-checked generated PDF page |
| GET | /api/v1/studio/tasks | Recent owned Studio task references for browser reload recovery |

UUIDs and UTC timestamps are serialized explicitly. Unknown values remain null. Commands reject extra fields and inappropriate coercion; command UUIDs accept their normal JSON string representation. Every mutation except browser pairing/disconnect requires Idempotency-Key; same-key replay returns the exact original response. OpenAPI describes alternative persistent header-token or browser-cookie authorization. Cookie access additionally requires loopback peer and same-origin browser metadata; mutations require exact Origin and X-CareerLens-Local. Upload alone uses bounded multipart; other browser commands/pairing use JSON. Errors use the common envelope; invalid values are not reflected. A persisted provider cooldown returns 429 with Retry-After. Static `/` and `/web/` routes are excluded from the schema; `/docs` remains available. PDFs are private attachments and raster previews, linked from the authenticated website.

## Evidence and AI contracts

`contracts/ai_schemas.json` contains named definitions for ProfileDraft, StructuredJD, TailoredContent and VerificationResult under `$defs`, now marked implemented with per-service status. ProfileDraft and StructuredJD are used by local deterministic services; they do not imply AI extraction. TailoredContent and VerificationResult use strict-schema Groq calls plus local provenance, protected-value and fail-closed publication checks. Schema validation alone does not establish factual correctness. The Phase 1 smoke probe is retained, while `app/adapters/groq_resume.py` is the runtime adapter.

Resume Studio's `groq-resume-v2` consent discloses primary 120B and the single eligible Groq 20B fallback. The same strict schema, Pydantic validation, fact IDs, repair limit and verification apply to both. Each stage records its actual model; the final PDF record identifies the model that supplied its final wording. Token/shared/unclear quotas do not authorize switching. See [limits and recovery](../backend/README.md#groq-limits-and-the-single-model-fallback) for the exact conservative policy. No paid/external-provider fallback exists.

`contracts/examples.json` contains synthetic examples. IDs in examples do not imply existing tasks or candidate records.

The following document-04 endpoints remain planned and deliberately absent from OpenAPI: application creation/list/detail, answers/resume/approval/cancel/reconcile. Dedicated standalone resume-generation routes serve Phase 4 without falsely creating application/submission records. No application-submission route or handler exists.

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
- Source refresh has bounded transient retries; local Studio stages can recover expired leases. A possibly completed Groq call is never replayed automatically. A future application preparation retry command still needs its final payload/endpoint definition.
- Workflow/approval/reconciliation guards exist as domain foundations for controlled tests. They are not a complete application review or employer receipt implementation.
- Profile content is immutable; confirmation metadata can change. Job/Resume/Fact content and terminal preparation runs are protected by SQLite triggers. Historical versions cannot be deleted through normal writes.
- A separate SourceListing membership table represents the latest board generation while immutable JobSnapshots retain history. Failed refreshes preserve the previous generation; a successful empty refresh publishes an honest empty generation.
- Real PDF extraction, confirmed-profile matching and verified Groq wording are implemented. Extraction is line-based; skill analysis has a finite vocabulary and conservative wording allows only limited changes. Rich semantic ranking, browser preparation, manual CAPTCHA intervention and destination receipt semantics remain future services. Automated visual layout review is explicitly unassessed; native Windows/Linux validation and final orphan-artifact reconciliation remain pending.
