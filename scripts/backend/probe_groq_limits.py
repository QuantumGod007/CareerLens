"""One synthetic strict-schema call per selected Groq model; no retries or fallback."""
import argparse
import json
from datetime import datetime, timezone

from app.adapters.groq_resume import GroqResumeProvider, MODEL, FALLBACK_MODEL
from app.core.config import ROOT, load_settings
from app.core.errors import DomainError
from app.persistence.database import Database
from app.adapters.groq_limits import check_cooldown
from app.schemas.ai import VerificationResult


def run(model, confirm_free_plan):
    if not confirm_free_plan:
        raise ValueError('Confirm the existing Free plan with no paid billing first')
    settings = load_settings()
    # Respect any cooldown recorded by the running isolated demo or normal workspace.
    if settings.db_path.exists():
        database = Database(settings)
        try:
            with database.read() as session:
                check_cooldown(session)
        finally:
            database.close()
    provider = GroqResumeProvider(settings)
    provider.model = model
    provider.fallback_used = True  # Diagnostic means exactly one HTTP request, including on 429.
    report = {'observed_at': datetime.now(timezone.utc).isoformat(), 'model': model,
              'synthetic_only': True, 'automatic_retries': 0, 'fallback_enabled': False}
    try:
        value = provider.complete(VerificationResult, {'facts': [], 'draft': {
            'claims': [], 'changes': [], 'selected_section_order': []}}, 'VERIFY')
        report.update(status='PASS' if value.passed else 'REVIEW_FAILED', schema_validation='PASS')
    except DomainError as error:
        report.update(status='BLOCKED', error_code=error.code)
    report['diagnostics'] = provider.diagnostics
    destination = ROOT / 'data' / 'phase4' / ('groq-' + model.rsplit('/', 1)[1] + '-limits.json')
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=(MODEL, FALLBACK_MODEL), default=MODEL)
    parser.add_argument('--confirm-free-plan', action='store_true')
    args = parser.parse_args()
    result = run(args.model, args.confirm_free_plan)
    raise SystemExit(0 if result['status'] == 'PASS' else 1)
