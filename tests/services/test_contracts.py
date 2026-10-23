import json

import pytest
from pydantic import ValidationError

from app.core.config import ROOT
from app.main import create_app
from app.schemas.ai import SourceSpan, VerificationResult
from app.tools.export_contracts import documents


def test_generated_openapi_only_contains_real_routes():
    paths = set(create_app().openapi()["paths"])
    assert paths == {"/health", "/api/v1/source-boards", "/api/v1/source-boards/{board_id}/refresh",
        "/api/v1/source-boards/{board_id}/jobs", "/api/v1/tasks/{task_id}",
        "/api/v1/tasks/{task_id}/events", "/api/v1/artifacts/{artifact_id}",
        "/api/v1/browser-session", "/api/v1/browser-session/disconnect",
        "/api/v1/profiles", "/api/v1/profiles/{profile_id}", "/api/v1/profiles/{profile_id}/confirm",
        "/api/v1/searches", "/api/v1/searches/{search_id}", "/api/v1/searches/{search_id}/decision",
        "/api/v1/searches/{search_id}/selection", "/api/v1/job-analyses/{analysis_id}",
        "/api/v1/resume-generations", "/api/v1/resume-generations/{generation_id}",
        "/api/v1/resume-generations/{generation_id}/preview/{page}", "/api/v1/studio/tasks"}
    assert not any("approve" in path or "applications" in path for path in paths)


def test_exported_contracts_match_implementation():
    for name, value in documents().items():
        assert json.loads((ROOT / "contracts" / name).read_text()) == value


def test_ai_contracts_reject_uncertain_pass_and_bad_spans():
    with pytest.raises(ValidationError):
        VerificationResult.model_validate({"pass": True, "violations": [], "uncertain_claims": [
            {"item_id": "synthetic", "reason": "unknown", "source_fact_ids": []}]})
    with pytest.raises(ValidationError):
        SourceSpan.model_validate({"page": 1, "start_offset": 10, "end_offset": 2, "source_text": "invalid"})
    assert documents()["ai_schemas.json"]["x-implementation-status"] == "implemented"
    assert "local" in documents()["ai_schemas.json"]["x-services"]["StructuredJD"]
