# CareerLens

CareerLens is a local job-search and application assistant for students and early-career candidates. It aims to bring job discovery, factual resume tailoring and reviewed applications into one workspace. Today, job discovery and source monitoring work; resume and application workflows are still planned.

## What works

- Overview with actual API, database and worker status.
- Stored jobs from Drivetrain’s public Lever feed, with search over loaded listings, type/location filters and incremental loading.
- Job details and validated links to official employer pages.
- Durable listing refreshes with idempotency, task progress, retries and event history.
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

The existing `.venv` on the development Mac can be reused. No external API key is needed for job discovery: Groq is not called by the website or source worker. If configuring it for an opt-in probe, use [.env.example](.env.example) and never overwrite an existing populated `.env`.

## Run locally

```bash
.venv/bin/python -m app.dev
```

Open [CareerLens](http://127.0.0.1:8000/). The command safely initializes/upgrades the database and starts the API and worker. Browser connection is automatic; no token copying is needed. Ctrl+C stops both processes. Use `--port 8001` if port 8000 is occupied.

See the [local operation guide](docs/backend/README.md) for configuration, sessions, manual API/worker commands, recovery and troubleshooting.

## Tests

Install the test browser once, then run the suite:

```bash
PLAYWRIGHT_BROWSERS_PATH="$PWD/data/playwright" .venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q
```

The baseline is **118 passing tests**, including 19 browser scenarios. Tests use isolated databases and synthetic/mocked data; live services are opt-in. See [validation commands and recorded results](docs/backend/README.md#tests-and-diagnostics) for live source demos, contract checks and credential scanning.

## Limitations and roadmap

This is a single-user, loopback-only application with one configured job board and one worker. Filters cover loaded listings, not candidate matching. Stored postings may have closed; verify availability on the employer website. Details contain summary metadata; private artifacts remain API-only.

Resume upload, profile confirmation, candidate matching, AI tailoring, PDF generation and reviewed application preparation/submission are planned. Generated claims must preserve confirmed candidate facts, missing answers require candidate input, and each real submission needs approval for its exact payload. Employer submission and CAPTCHA handling are unverified; uncertain sends must never retry automatically. No employer application has been submitted. Native Windows/Linux validation remains pending.

## Technical references

- [Local operation, security and recovery](docs/backend/README.md)
- [Implemented APIs, future contracts and original specifications](docs/contracts/implementation-status.md)
- [Architecture decisions](docs/feasibility/architecture-decisions.md)
- Historical evidence: [feasibility checks](docs/feasibility/README.md) and [backend implementation](docs/backend/phase-2-report.md)
- [Development guide](CONTRIBUTING.md)
