# CareerLens

CareerLens is a planned job application assistant for students and freshers. It will discover jobs, prepare truthful tailored resumes and complete applications after explicit candidate approval.

## Current status

Phase 1 feasibility tooling is implemented and has been executed locally. The production API, database schema, durable worker, resume enhancement workflow and website are **not implemented**. Phase 2 has not started.

On 23 October 2026, the checks verified:

- Python 3.12, dependency imports, SQLite/SQLAlchemy queries and Chromium startup.
- Live Drivetrain Lever retrieval: 35 postings, two India engineering-intern title matches, stable IDs across two reads and an empty-match case.
- Read-only live form inspection. It includes hCaptcha; upload, verification and submission remain unverified.
- One real Groq `openai/gpt-oss-120b` structured-output request with synthetic facts, Pydantic validation and factual checks.
- Jinja2/Chromium PDF generation, page-specific text extraction, Latin Unicode and invalid-input rejection.
- Local synthetic form filling, attachment, missing-answer checks and one controlled receipt. This is not an employer submission or durable duplicate protection.
- 41 offline automated tests. Live and browser probes are separate commands.

See [the Phase 1 report](docs/feasibility/README.md) for evidence and limitations.

## Setup

Use Python 3.12 and create a project-local `.venv` with that interpreter. On the validated machine, Codex's bundled Python 3.12.14 created the environment; `python3.12` was not on PATH. A fresh machine needs its own Python 3.12 executable. Windows and Linux have not been tested.

From the repository root, after creating `.venv`:

```bash
.venv/bin/python -m pip install --cache-dir data/pip-cache -r requirements.lock.txt
PLAYWRIGHT_BROWSERS_PATH="$PWD/data/playwright" .venv/bin/python -m playwright install chromium
.venv/bin/python -m scripts.feasibility.check_environment
```

`requirements.in` lists direct dependencies; `requirements.lock.txt` records exact tested versions and transitive dependencies. The lock was tested on macOS ARM64.

If `.env` does not exist, copy `.env.example` to `.env`, restrict it to owner access (`chmod 600 .env`) and edit it locally. Do not overwrite an existing populated file.

| Variable | Value |
| --- | --- |
| `GROQ_API_KEY` | Your local Groq key; never commit it |
| `GROQ_MODEL` | `openai/gpt-oss-120b` |

Only Groq and this model are supported. There is no automatic fallback, key rotation or paid upgrade. The live AI probe requires explicit confirmation that the organization has no paid billing; it cannot independently inspect billing.

## Run the checks

These commands have been executed on the validation machine:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.feasibility.check_environment
.venv/bin/python -m scripts.feasibility.test_job_source --location India
.venv/bin/python -m scripts.feasibility.inspect_application_form
.venv/bin/python -m scripts.feasibility.test_groq --without-credentials
.venv/bin/python -m scripts.feasibility.test_groq --confirm-free-plan
.venv/bin/python -m scripts.feasibility.test_pdf_pipeline
.venv/bin/python -m scripts.feasibility.test_controlled_form
.venv/bin/python -m scripts.feasibility.check_repository_safety
```

Run the PDF probe before the controlled-form probe. Employer inspection makes GET/HEAD requests only, never fills fields and never submits. The separate controlled form operates locally with networking disabled.

Reports, synthetic PDFs, browser downloads and screenshots stay in ignored `data/`. Probes print sanitized results and exit nonzero on failures; they do not dump SDK exceptions, headers or credentials. Results can change after the recorded run.

## Intended workflow

Upload resume → confirm profile → discover/select job → analyse JD → truthful resume enhancement → generate PDF → prepare application → collect missing answers → review → approve → submit → verify receipt.

The initial product serves one local candidate, one board, one PDF layout and one application at a time. Its proposed stack is FastAPI, Pydantic, SQLite/SQLAlchemy, one durable worker, Playwright, pdfplumber, Jinja2 and Groq. Backend functionality comes before UI. The initial future website will use vanilla HTML, CSS and JavaScript; visual redesign is deferred.

## Next phase

Review Phase 1 before starting Phase 2: API/persistence/worker foundation and versioned contracts. See [architecture decisions](docs/feasibility/architecture-decisions.md) for dry-run/live-run lifecycle and safe retries.

The six original Word documents remain outside this repository. Their referenced OpenAPI and AI schema companions were not found in the repository or expected handoff paths, so no machine-readable contract parity is claimed.

## Collaboration and private data

See [CONTRIBUTING.md](CONTRIBUTING.md). Never commit credentials, real resumes, application answers, databases, browser sessions or private traces. Run the repository-safety check after staging intended files; it scans the index and reachable history without printing credentials.
