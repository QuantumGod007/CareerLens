import json

import groq
import httpx
import pytest
from pydantic import ValidationError

from scripts.feasibility.common import ProbeError
from scripts.feasibility.test_groq import (
    CANDIDATE, REQUIREMENTS, MODEL, GroqSkillProbe, SkillComparison, classify_error,
)

VALID = {"matched_skills": ["Python", "SQL"], "not_evidenced_skills": ["Docker", "AWS"],
         "candidate_skills": CANDIDATE}


def test_valid_skill_evidence():
    SkillComparison.model_validate(VALID).verify(CANDIDATE, REQUIREMENTS)


@pytest.mark.parametrize("change", [
    {"matched_skills": ["Python", "SQL", "Docker"]},
    {"candidate_skills": [*CANDIDATE, "AWS"]},
    {"not_evidenced_skills": []},
    {"matched_skills": ["Python", "Python", "SQL"]},
])
def test_fabricated_or_missing_evidence_is_rejected(change):
    with pytest.raises(ProbeError, match="FACTUAL_VALIDATION_FAILED"):
        SkillComparison.model_validate({**VALID, **change}).verify(CANDIDATE, REQUIREMENTS)


def test_schema_does_not_coerce_or_accept_extra_fields():
    with pytest.raises(ValidationError):
        SkillComparison.model_validate({**VALID, "candidate_skills": "Python"})
    with pytest.raises(ValidationError):
        SkillComparison.model_validate({**VALID, "experience": "Invented"})


@pytest.mark.parametrize("key", [None, "", "replace_with_your_groq_key"])
def test_missing_key_blocks_before_client_creation(key, monkeypatch):
    def forbidden(**kwargs):
        raise AssertionError("Client must not be created without credentials")
    monkeypatch.setattr("scripts.feasibility.test_groq.Groq", forbidden)
    with pytest.raises(ProbeError, match="MISSING_API_KEY"):
        GroqSkillProbe(key)


@pytest.mark.parametrize("status,code", [(401, "AUTHENTICATION_FAILED"), (403, "PROVIDER_ACCESS_DENIED"),
    (404, "MODEL_UNAVAILABLE"), (429, "RATE_LIMIT_OR_QUOTA_EXHAUSTED"), (503, "PROVIDER_UNAVAILABLE")])
def test_provider_errors_are_classified_without_response_body(status, code):
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(status, request=request, headers={"retry-after": "12"})
    error = groq.APIStatusError("Sensitive synthetic response must not escape", response=response,
                                body={"detail": "DO_NOT_LOG_THIS"})
    safe = classify_error(error)
    assert safe.code == code
    assert "DO_NOT_LOG_THIS" not in str(safe)
    assert safe.retry_after == "12"


def test_timeout_classification():
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    assert classify_error(groq.APITimeoutError(request=request)).code == "PROVIDER_TIMEOUT"


def test_other_models_are_not_silent_fallbacks():
    with pytest.raises(ProbeError, match="UNVALIDATED_MODEL"):
        GroqSkillProbe("synthetic-not-a-real-key", model="another-model")


def test_official_sdk_request_and_response_contract(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"object": "list", "data": [{"id": MODEL, "object": "model",
                "created": 0, "owned_by": "synthetic"}]})
        payload = json.loads(request.content)
        assert payload["response_format"]["json_schema"]["strict"] is True
        assert payload["model"] == MODEL
        return httpx.Response(200, json={"id": "synthetic", "object": "chat.completion", "created": 0,
            "model": MODEL, "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps(VALID)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}})

    real_constructor = groq.Groq
    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("scripts.feasibility.test_groq.Groq", lambda **kwargs: real_constructor(
        **kwargs, http_client=client))
    result = GroqSkillProbe("synthetic-not-a-real-key").run()
    assert result["status"] == "PASS"
    assert len(seen) == 2


def test_rate_limit_is_not_automatically_retried(monkeypatch):
    count = 0

    def handler(request):
        nonlocal count
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"object": "list", "data": [{
                "id": MODEL, "object": "model", "created": 0, "owned_by": "synthetic"}]})
        count += 1
        return httpx.Response(429, json={"error": {"message": "Synthetic quota exhausted"}},
                              headers={"retry-after": "30"})

    real_constructor = groq.Groq
    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("scripts.feasibility.test_groq.Groq", lambda **kwargs: real_constructor(
        **kwargs, http_client=client))
    with pytest.raises(ProbeError, match="RATE_LIMIT_OR_QUOTA_EXHAUSTED") as caught:
        GroqSkillProbe("synthetic-not-a-real-key").run()
    assert caught.value.retry_after == "30"
    assert count == 1
