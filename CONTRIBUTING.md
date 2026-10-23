# Development

CareerLens currently has one maintainer. Keep changes focused, preserve existing requirements and working behavior, and keep documentation consistent with what runs. Follow the requested Git workflow; PRs and formal handoffs are optional. Make meaningful commits and push normally without force-pushing or rewriting unrelated history.

Use the [README](README.md) for setup and `python -m app.dev` for local development. Before committing, review the complete diff and run:

```bash
.venv/bin/python -m pytest -q
# After staging the intended files:
.venv/bin/python -m scripts.feasibility.check_repository_safety
```

After intentional API/schema changes, regenerate contracts with `python -m app.tools.export_contracts`. Describe tests honestly: distinguish fixtures from live integrations. Normal tests use isolated databases and synthetic/mocked data, including worker crash recovery; they do not call employers or Groq. Live probes are opt-in, and a Groq call requires confirmation that the organization has no paid billing. See [validation details](docs/backend/README.md#tests-and-diagnostics).

Never commit populated `.env` files, credentials, session tokens, resumes, answers, databases, browser state, private screenshots/traces or generated local outputs. Use placeholders and synthetic fixtures; check the staged diff as well as credential-scan results.

Keep the product’s safety rules intact: use confirmed facts for generated claims, ask for missing answers, and bind approval to the exact application payload. Changed resumes or answers need fresh approval. Test browser preparation against a controlled receiver. Never retry an uncertain possible submission automatically.

Preserve technical evidence and architecture decisions. Consolidate duplicates only when every unique detail remains accessible. Stay within the requested scope; do not begin the next phase or merge unrelated work automatically.
