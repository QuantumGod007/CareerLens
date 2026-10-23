# CareerLens

CareerLens is a local job-search and resume assistant for students and early-career candidates. Discover real jobs, review facts extracted from your PDF, and generate a verified resume for a selected role. Reviewed employer applications remain a future phase.

## What works

- Overview with actual API, database and worker status.
- Stored jobs from Drivetrain’s public Lever feed, with search over loaded listings, type/location filters and incremental loading.
- Job details and validated links to official employer pages.
- Durable listing refreshes with idempotency, task progress, retries and event history.
- Private PDF upload, local extraction or separately consented Groq structuring, traceable facts, immutable corrections and explicit confirmation.
- Preferred-role searches, JD evidence and explainable required/preferred skill coverage.
- Consented Groq wording, factual verification, private PDF preview/download and saved versions.
- Automatic private browser sessions and one command to start the API and separate worker.

## Stack

Python 3.12, FastAPI, Pydantic, SQLite, SQLAlchemy and Alembic; vanilla HTML, CSS and JavaScript. Playwright and pytest cover browser and backend behavior. Dependencies are pinned in [requirements.lock.txt](requirements.lock.txt). No frontend build or Node.js setup is needed.

## Getting started

For a fresh checkout, create a Python 3.12 environment and install dependencies from the repository root:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --cache-dir data/pip-cache -r requirements.lock.txt
```

The existing `.venv` on the development Mac can be reused. Discovery and local PDF extraction need no API key. AI wording uses the existing private `GROQ_API_KEY` in `.env`; see [.env.example](.env.example), and never overwrite a populated local file. Install Chromium once with the command under Tests; PDF rendering uses it too.

## Run locally

```bash
.venv/bin/python -m app.dev
```

Open [CareerLens](http://127.0.0.1:8000/). The command safely initializes/upgrades the database and starts the API and worker. Browser connection is automatic; no token copying is needed. Ctrl+C stops both processes. Use `--port 8001` if port 8000 is occupied.

See the [local operation guide](docs/backend/README.md) for configuration, sessions, manual API/worker commands, recovery and troubleshooting.

In **Explore jobs**, refresh the source. In **Resume Studio**, upload a text PDF, correct and confirm its facts, enter your role and optional filters, then analyse a matching job. Review the Groq consent before generating; compare the wording and download the verified PDF. Originals remain unchanged.

## Tests

Install the test browser once, then run the suite:

```bash
PLAYWRIGHT_BROWSERS_PATH="$PWD/data/playwright" .venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q
```

The suite has **250 tests**, preserving the 118-test Phase 3 baseline. Tests use isolated databases and synthetic/mocked data; live services are opt-in. See [validation commands and recorded results](docs/backend/README.md#tests-and-diagnostics) for browser-to-PDF evidence, live source/model diagnostics, contract checks and credential scanning.

## Limitations and roadmap

This is a single-user, loopback-only application with one configured job board and one worker. Stored postings may have closed; verify availability on the employer website. Uploads are text PDFs up to 5 MiB/10 pages, with no OCR. Local-only parsing is the default; optional Groq parsing receives bounded extracted text with identified contacts masked, never PDF bytes. All model spans must match the original text. Quota or grounding failures retain a labelled local draft. Every mode needs review/confirmation. Matching uses a finite reviewed skill vocabulary; coverage is neither eligibility nor an ATS/hiring score. Wording changes are deliberately conservative and never add qualifications.

Groq defaults to `openai/gpt-oss-120b`. An explicitly eligible model request-rate limit can permit one `openai/gpt-oss-20b` attempt; token/shared/unclear quotas require waiting. Both use the existing Free-plan key and identical verification. No paid or external-provider fallback exists. Free quota may interrupt generation; reported cooldowns persist across restart.

Employer preparation/submission and CAPTCHA handling remain unverified and unimplemented in the website. Missing answers require candidate input, each real submission needs approval for its exact payload, and uncertain sends must never retry automatically. No employer application has been submitted. Native Windows/Linux validation remains pending.

## Technical references

- [Local operation, security and recovery](docs/backend/README.md)
- [Implemented APIs, future contracts and original specifications](docs/contracts/implementation-status.md)
- [Architecture decisions](docs/feasibility/architecture-decisions.md)
- Historical evidence: [feasibility checks](docs/feasibility/README.md) and [backend implementation](docs/backend/phase-2-report.md)
- [Development guide](CONTRIBUTING.md)
