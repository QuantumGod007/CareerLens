# Job source validation

Executed 23 October 2026, India Standard Time. Status: PASS for one live discovery source.

Python/httpx retrieved [Drivetrain's public Lever feed](https://api.lever.co/v0/postings/drivetrain?mode=json): 35 postings, no duplicate external IDs, and equal ID sets across two sequential reads. Later availability is not guaranteed.

The JSON response is an array. Observed fields include `id`, `text`, `categories`, `descriptionPlain`, `lists`, `additionalPlain`, `hostedUrl`, `applyUrl` and `workplaceType`. The probe combines introduction, list sections and closing text, retains missing metadata as null, and records a content hash and fetch time. Canonical keys use source, board and external ID rather than cosmetic URLs.

For explicit title `Software Engineer Intern` and explicit location `India`, these two postings matched:

| Public listing | External ID | Type |
| --- | --- | --- |
| [Engineering Intern – Gen AI for FP&A Platform](https://jobs.lever.co/drivetrain/bc1c17bc-86ac-4f00-a1e3-0eb85aae4fdc) | bc1c17bc-86ac-4f00-a1e3-0eb85aae4fdc | Internship |
| [Quality Assurance Engineering (QAE) - Intern](https://jobs.lever.co/drivetrain/edb8a8f7-16ac-4177-bf2e-99c36ab47d5f) | edb8a8f7-16ac-4177-bf2e-99c36ab47d5f | Internship |

Matching requires every normalized title token; engineering/developer map to engineer, internship to intern, and generic software is omitted when engineer is present. This broad heuristic can return QA and does not determine eligibility. Results are capped at five. No location default is silently inferred. Distinct IDs with identical titles remain separate because titles alone do not establish duplicate destinations.

A nonexistent role returned zero matches. Offline tests exercise duplicate IDs, unknown locations, outages, timeouts, rate limits, invalid JSON, oversized responses and unexpected redirects/hosts. These failures are simulated, not claims that the live source suffered an outage.

Selected source is suitable for the first discovery adapter; application feasibility is separate. [Lever's official documentation](https://github.com/lever/postings-api) distinguishes public listing access from submission APIs requiring employer authorization. No such credentials were obtained or used.

Reproduce: `.venv/bin/python -m scripts.feasibility.test_job_source --location India`. Local evidence: `data/feasibility/job-source.json`. Limitations: one board, title heuristic, bounded response size, no eligibility decision, no cross-board alias reconciliation and no automatic retry in this probe.
