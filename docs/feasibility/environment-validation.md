# Environment validation

Executed 23 October 2026, India Standard Time. Status: PASS on the local macOS 27.0.1 ARM64 machine.

System Python was 3.13, so a dedicated `.venv` was created using Codex's bundled Python 3.12.14. No global packages or system configuration were modified. Official Playwright browser downloads are stored in ignored `data/playwright/`.

| Component | Tested version |
| --- | --- |
| Python | 3.12.14 |
| SQLite | 3.53.1 |
| Chromium | 156.0.8078.4 |
| FastAPI | 0.161.1 |
| Pydantic | 2.14.1 |
| SQLAlchemy | 2.1.6 |
| httpx | 0.28.1 |
| Groq SDK | 0.37.1 |
| Playwright | 1.64.1 |
| pdfplumber | 0.11.10 |
| Jinja2 | 3.1.6 |
| python-dotenv | 1.2.4 |
| pypdf | 6.21.2 |
| pytest | 9.1.1 |

Every direct dependency imported. Chromium launched and read a page title. SQLite and SQLAlchemy executed queries. Installing from the frozen lock succeeded, and `pip check` found no broken requirements. These are local checks, not proof of compatibility across operating systems or future updates.

The local `.env` is ignored, untracked and has filesystem mode 0600. Only placeholder configuration is public. Billing status is based on the user's Free-plan/no-paid-billing confirmation, not account inspection.

Reproduce: `.venv/bin/python -m scripts.feasibility.check_environment`. Local evidence: `data/feasibility/environment.json`. Full versions are in `requirements.lock.txt`.

The production API, schema, WAL/foreign-key settings, concurrent writes and worker recovery are not validated by this connection probe. Windows and Linux are NOT TESTED. Platform prerequisites are documented in the [official Playwright installation guide](https://playwright.dev/python/docs/intro).
