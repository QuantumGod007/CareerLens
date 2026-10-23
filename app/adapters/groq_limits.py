"""Allowlisted quota diagnostics. Never persist the provider's raw error message."""
import math
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from sqlalchemy import func, select

from app.core.errors import DomainError
from app.persistence.models import ResumeGeneration

HEADERS = ('x-ratelimit-limit-requests', 'x-ratelimit-limit-tokens',
           'x-ratelimit-remaining-requests', 'x-ratelimit-remaining-tokens',
           'x-ratelimit-reset-requests', 'x-ratelimit-reset-tokens')


def diagnostics(status, headers, body=None, *, now=None):
    now = now or datetime.now(timezone.utc)
    safe = {key: value for key in HEADERS if (value := headers.get(key))
            and re.fullmatch(r'[0-9.hmsd ]{1,80}', value)}
    retry = headers.get('retry-after')
    seconds = None
    if retry:
        try:
            seconds = float(retry)
        except ValueError:
            try:
                seconds = (parsedate_to_datetime(retry) - now).total_seconds()
            except (TypeError, ValueError, OverflowError):
                pass
    if seconds is not None and (not math.isfinite(seconds) or seconds < 0 or seconds > 7*86400):
        seconds = None
    error = body.get('error', {}) if isinstance(body, dict) else {}
    if not isinstance(error, dict):
        error = {}
    message = error.get('message', '')
    message = message if isinstance(message, str) else ''
    metric = 'unknown'
    for phrase, value in [('input tokens per minute', 'input_tokens_per_minute'),
                          ('output tokens per minute', 'output_tokens_per_minute'),
                          ('tokens per minute', 'tokens_per_minute'), ('tokens per day', 'tokens_per_day'),
                          ('requests per minute', 'requests_per_minute'), ('requests per day', 'requests_per_day')]:
        if phrase in message.casefold():
            metric = value
            break
    shared = bool(re.search(r'shared|across (?:all )?models|(?:organization|project)[ -]wide|\b(?:ITPM|OTPM)\b|billing|spend|budget', message, re.I))
    model_match = re.search(r'for model\s+[`\'"]?(openai/gpt-oss-(?:120|20)b)\b', message)
    # Mentioning the model in an error does not prove the quota is isolated to it.
    model_scope = error.get('scope') == 'model' or bool(re.search(r'model[ -]specific|per[ -]model', message, re.I))
    scope = 'shared' if shared else 'model' if model_match and model_scope else 'unknown'
    numbers = {}
    for label in ('limit', 'used', 'requested'):
        found = re.search(r'\b' + label + r'\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)\b', message, re.I)
        if found:
            numbers[label] = float(found[1])
    return {'http_status': status, 'headers': safe, 'limiting_factor': metric, 'scope': scope,
            'limited_model': model_match.group(1) if model_match else None, **numbers,
            'retry_after_seconds': seconds,
            'retry_not_before': (now + timedelta(seconds=seconds)).isoformat() if seconds is not None else None}


def fallback_reason(report, model, input_bytes, output_budget):
    """Fail closed: TPM/daily/shared/unknown limits should wait, never switch models."""
    if report['http_status'] != 429 or report['scope'] != 'model' or report['limited_model'] != model:
        return 'shared_or_ambiguous_quota'
    if report['limiting_factor'] != 'requests_per_minute':
        return 'wait_for_token_or_daily_limit'
    wait = report['retry_after_seconds']
    if wait is None or wait > 2:
        return 'wait_for_reported_cooldown'
    headers = report['headers']
    # Bytes are a conservative upper bound, unlike the usual characters/4 token estimate.
    required = input_bytes + output_budget
    try:
        enough = (float(headers['x-ratelimit-remaining-requests']) > 0
                  and float(headers['x-ratelimit-remaining-tokens']) >= required
                  and float(headers['x-ratelimit-limit-tokens']) >= required)
    except (ValueError, KeyError):
        enough = False
    return None if enough else 'insufficient_or_unknown_token_budget'


def check_cooldown(session):
    deadline = session.scalar(select(func.max(ResumeGeneration.stage_json['retry_not_before'].as_string())))
    if deadline:
        try:
            remaining = (datetime.fromisoformat(deadline) - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError):
            return
        if remaining > 0:
            raise DomainError('PROVIDER_COOLDOWN', 'Groq requested a cooldown. Wait before explicitly generating again.',
                              429, retry_after=remaining)
