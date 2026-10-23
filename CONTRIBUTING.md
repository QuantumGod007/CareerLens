# Contributing to CareerLens

Phase 1 feasibility tools and the Phase 2 backend foundation are implemented. Full resume/application services and UI are pending. Agree on module interfaces before splitting implementation work.

## Team workflow

1. Create or choose an issue describing a small, concrete task and its expected result.
2. Branch from the latest `main`. Use descriptive names such as `feature/resume-parser`, `fix/job-filter` or `docs/setup`.
3. Keep changes focused and coordinate before editing a module another teammate owns.
4. Open a pull request to `main`, describing what changed, how it was checked and any remaining limitations.
5. Ask a teammate to review before merging. Keep the README consistent with what actually runs.

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

Do not begin the next phase or merge the Phase 2 draft PR automatically. Review the execution report first.
