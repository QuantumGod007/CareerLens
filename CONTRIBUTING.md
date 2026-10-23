# Contributing to CareerLens

Phase 1 feasibility tools, the Phase 2 backend and Phase 3 local website are implemented. Full resume/application services are pending. CareerLens currently has one owner; keep changes focused and easy to run locally.

## Development workflow

1. Start from the latest `main` on a descriptive branch, normally `codex/<change>` for agent work.
2. Preserve existing code, tests and useful documentation. Implement and test the complete change.
3. Check the staged diff and credentials, make meaningful commits and push verified work.
4. Keep the README consistent with what runs. PRs and review are optional when useful; no formal handoff or draft PR is required for every phase. Do not force-push or overwrite unrelated work.

## Candidate facts and application approval

- Generated resume claims must be supported by confirmed candidate facts.
- Missing required answers must be requested from the candidate.
- Any change to the reviewed resume or answers requires fresh approval.
- Tests and rehearsals should use synthetic data and a controlled application receiver.
- A real employer application requires the candidate's explicit approval for that exact application.
- Report uncertain submission outcomes honestly and do not retry a possible submission automatically.

## Public repository hygiene

Do not commit credentials, `.env` files, personal resumes, application answers, local databases, browser cookies, saved sessions or private screenshots and traces. Use placeholders in configuration examples and synthetic records in fixtures. Review the staged diff before committing.

## Validation

Run `.venv/bin/python -m pytest -q` for offline checks and the relevant smoke commands in the README. After staging intended files, run `.venv/bin/python -m scripts.feasibility.check_repository_safety` before committing or pushing. Live Groq tests require confirmation that the organization has no paid billing. Default tests never call Groq or load your key. Distinguish live, controlled-browser and mocked results in pull requests.

Use the API/worker commands in `docs/backend/README.md`. Normal tests use isolated databases and synthetic/mocked data, including a child-process crash test; they do not contact employers or Groq. Real source-refresh demonstrations are explicitly invoked separately. Regenerate contracts with `python -m app.tools.export_contracts` after intentional endpoint/schema changes.

Start locally with `python -m app.dev`. Stop after the requested phase; do not start another phase or merge branches automatically.
