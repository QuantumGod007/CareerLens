# Phase 1 execution report

The checks below ran on 23 October 2026, India Standard Time, on local macOS ARM64. Phase 1 tooling is ready for review; Phase 2 has not started.

| Check | Status | Actual evidence |
| --- | --- | --- |
| Environment | PASS | Python 3.12.14; imports, SQLite/SQLAlchemy queries and Chromium 156.0.8078.4 startup |
| Dependencies | PASS | Exact versions locked; locked install and pip check succeeded |
| Live discovery | PASS | 35 Drivetrain jobs; two India title matches; stable IDs across two reads |
| Empty/source-failure handling | PASS | Live nonexistent-role check plus offline duplicate, outage, timeout, redirect and schema fixtures |
| Live employer form inspection | PASS | HTTP 200; controls inspected without entry, upload or submission |
| Employer upload/submission | NOT TESTED | Intentionally excluded from Phase 1 |
| Human verification | NOT TESTED | hCaptcha integration observed; manual-intervention feasibility remains unresolved |
| Groq structured inference | PASS | Real gpt-oss-120b call; schema/facts valid; 410 tokens; 1.211 seconds |
| Billing tier | User confirmed | Free plan/no paid billing confirmed in conversation; not independently inspected |
| Missing key/provider errors | PASS | Offline missing-key probe and mocked SDK error tests |
| PDF pipeline | PASS | Two pages, exact page spans, critical values and Latin Unicode retained |
| Invalid PDFs | PASS | Empty, blank, malformed, truncated, encrypted, oversized and excess-page fixtures |
| Controlled form | PASS | Synthetic fields/upload, missing-answer pause, ready-before-submit and one local receipt |
| Offline suite | PASS | 41 tests; no external service calls; JUnit evidence kept locally |
| Machine-readable contract parity | BLOCKED | Referenced OpenAPI/AI schema companions unavailable at checked paths |

Detailed evidence: [environment](environment-validation.md), [source](job-source-validation.md), [form](application-form-validation.md), [Groq](groq-validation.md), [PDF](pdf-validation.md) and [architecture](architecture-decisions.md). Raw reports and screenshots stay in ignored `data/feasibility/`. Public reports summarize only public or synthetic information.

One controlled-form run initially failed because its dropdown's implicit label included option text. An explicit label fixed it; the corrected run passed. No failed result was represented as a pass.

The next phase can build API/persistence/worker foundations after reviewing these results and resolving the contract/dry-run lifecycle decisions. Durable approval, duplicate prevention, restart recovery, candidate provenance and employer receipt verification remain unimplemented.

Work is isolated on `codex/phase-1-feasibility`. See `git-handoff.md` for the commit/push record once verification finishes. No product frontend, production schema or Phase 2 implementation is included.
