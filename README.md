# CareerLens

CareerLens is a planned job application assistant for students and freshers.

The initial prototype will support uploading and confirming a resume, discovering jobs on one supported company careers board, preparing a truthful tailored PDF, and reviewing an application before explicitly approving submission.

## Project status

Planning and repository setup. Application implementation has not started.

This repository does not yet contain a runnable application. The stack and workflow below describe the intended prototype.

## Planned workflow

1. Upload a text-based PDF resume and enter a preferred job title.
2. Review and confirm the extracted candidate facts.
3. Discover up to five live jobs from a configured company careers board and select one.
4. Analyse the job description and show supported skills and missing requirements.
5. Generate a tailored PDF using only confirmed facts, with a change log.
6. Prepare the supported application form and ask the candidate for missing answers.
7. Review the exact PDF and answers, then explicitly approve submission.
8. Submit once and show confirmed receipt, a clear rejection or an unknown outcome.

## Initial scope

- One local candidate and one supported job board.
- Resume parsing, fact confirmation, job discovery and job description analysis.
- Resume improvements supported by confirmed candidate facts.
- Application preparation, missing-answer handling and explicit approval.
- Submission tracking with destination confirmation or an explicit unknown outcome.

## Proposed stack

Python, FastAPI, Pydantic, SQLAlchemy with SQLite, one local worker, Playwright, pdfplumber, Jinja2 and one validated AI provider.

## First prototype priorities

Validate a live job board, its hosted application form and an available AI account first. Then build the API and worker, resume pipeline, application preparation, approval and outcome tracking. Add a minimal local interface after the backend flow works.

Multiple portals, bulk applications, recruiter outreach, a browser extension and production hosting are outside the first prototype.

## Project documentation

The planning set contains six documents:

| Document | Purpose |
| --- | --- |
| Product requirements | Product goals, user journey and release scope |
| Software requirements | Testable behaviour and acceptance criteria |
| Architecture and UML | Modules, data relationships and workflow states |
| API and AI specifications | Endpoints, model contracts and approval rules |
| Tech stack and setup | Proposed dependencies and setup validation |
| Implementation plan | Build sequence, checkpoints, tests and demo fallback |

These documents are maintained separately and have not been included in this repository. Public copies should be reviewed before being added. The referenced OpenAPI and AI schema files also need to be checked before implementation.

Installation and run instructions will be added when the application exists and the commands have been verified.

## Collaboration

See [CONTRIBUTING.md](CONTRIBUTING.md) for the team workflow. Never commit API keys, personal resumes, application answers or browser session data.
