# CareerLens

CareerLens is a planned job application assistant for students and freshers.

The initial prototype will support uploading and confirming a resume, discovering jobs on one supported company careers board, preparing a truthful tailored PDF, and reviewing an application before explicitly approving submission.

## Project status

Planning and repository setup. Application implementation has not started.

## Initial scope

- One local candidate and one supported job board.
- Resume parsing, fact confirmation, job discovery and job description analysis.
- Resume improvements supported by confirmed candidate facts.
- Application preparation, missing-answer handling and explicit approval.
- Submission tracking with destination confirmation or an explicit unknown outcome.

## Proposed stack

Python, FastAPI, Pydantic, SQLAlchemy with SQLite, one local worker, Playwright, pdfplumber, Jinja2 and one validated AI provider.

## Collaboration

Keep changes focused and use pull requests for review. Never commit API keys, personal resumes, application answers or browser session data. Setup and contribution instructions will be added as implementation begins.
