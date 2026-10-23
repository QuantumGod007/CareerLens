# Groq validation

Executed 23 October 2026, India Standard Time. Status: PASS for one live synthetic inference and offline error-path tests.

Provider: Groq only. Model: `openai/gpt-oss-120b`. SDK: 0.37.1. Model/provider fallback and automatic retries are disabled. The user confirmed Free-plan/no-paid-billing status; billing and exact remaining organization quotas were not independently inspected.

The credential was loaded locally, never included in reports. Model listing confirmed access. One inference used strict JSON Schema, temperature 0, low reasoning effort and a 1024 completion-token cap. [Groq's documentation](https://console.groq.com/docs/structured-outputs) lists this model as supporting strict output. The actual response also passed local Pydantic validation and deterministic evidence checks.

| Measurement | Observed |
| --- | --- |
| Returned model | openai/gpt-oss-120b |
| Model-list plus completion latency | 1.211 seconds |
| Prompt tokens | 274 |
| Completion tokens | 136 |
| Total tokens | 410 |
| Schema/factual validation | PASS / PASS |

Synthetic candidate skills: Python, FastAPI, SQL, Git. Requirements: Python, SQL, Docker, AWS. The response matched Python/SQL, marked Docker/AWS as not evidenced and preserved all candidate skills. No real resume or personal candidate data was sent.

The missing-key probe blocked offline before client creation. Offline tests cover wrong schemas, invented/omitted evidence, duplicate skills, fixed-model enforcement, authentication/access/model errors, timeout and rate/quota classification. A mocked 429 through the real SDK proved no automatic retry and preserved `Retry-After`. Those errors were simulated; the live account did not report them.

SDK calls are isolated in `GroqSkillProbe`, with a fixed official destination and typed result/classified errors. Future providers can implement the same boundary after explicit cost/privacy decisions; no routing engine exists. [Organization limits](https://console.groq.com/docs/rate-limits) must be checked on the account rather than inferred from generic public limits.

Local evidence: `data/feasibility/groq.json`, `groq-missing-key.json`. Live command: `.venv/bin/python -m scripts.feasibility.test_groq --confirm-free-plan`. Use the flag only for an organization with no paid billing; the script cannot enforce the external billing tier. One successful comparison does not validate the later resume/JD system or sustained quota capacity.
