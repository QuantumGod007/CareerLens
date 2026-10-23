# Contributing to CareerLens

The project is currently in planning and repository setup. Agree on module interfaces before splitting implementation work.

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

Run the checks relevant to your change and describe the results in the pull request. Installation, startup and test commands will be documented after they have been implemented and verified; there are no application checks to run yet.
