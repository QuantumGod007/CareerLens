"""Export implemented routes and the evidence/AI contracts used by Resume Studio."""
import json

from pydantic.json_schema import models_json_schema

from app.core.config import ROOT
from app.main import create_app
from app.schemas.ai import ProfileDraft, StructuredJD, TailoredContent, VerificationResult
from app.schemas.profile_ai import GroqProfileDraft
from app.tools.init_db import BOARD_ID


def documents():
    _, ai = models_json_schema([(model, "validation") for model in (
        ProfileDraft, StructuredJD, TailoredContent, VerificationResult, GroqProfileDraft)],
        title="CareerLens AI contracts", description="Phase 4 evidence contracts with local extraction and verified Groq resume wording.")
    ai.update({"$schema": "https://json-schema.org/draft/2020-12/schema",
               "x-implementation-status": "implemented", "x-contract-version": "0.4.1",
               "x-services": {"ProfileDraft": "local extraction or separately consented Groq structuring, with exact validated PDF spans",
                              "GroqProfileDraft": "strict text-only section/span selection; contacts stay local and every model span is grounded",
                              "StructuredJD": "local reviewed skill vocabulary with JD evidence",
                              "TailoredContent": "consent-gated Groq wording plus deterministic verification",
                              "VerificationResult": "Groq semantic review and fail-closed publication checks"}})
    return {
        "openapi.json": create_app().openapi(), "ai_schemas.json": ai,
        "examples.json": {
            "notice": "Synthetic examples; references do not imply live task or candidate records.",
            "refresh_request": {"expected_revision": 1},
            "refresh_response": {"task_id": "11111111-1111-4111-8111-111111111111",
                "entity_type": "source_board", "entity_id": str(BOARD_ID),
                "status_url": "/api/v1/tasks/11111111-1111-4111-8111-111111111111"},
            "error": {"error": {"code": "STALE_REVISION", "message": "Refresh the source revision.",
                "retryable": False, "details": {}}, "correlation_id": "22222222-2222-4222-8222-222222222222"},
            "future_verification": {"pass": False, "violations": [], "uncertain_claims": [
                {"item_id": "synthetic-claim-1", "reason": "Source evidence requires review", "source_fact_ids": []}]},
        },
    }


if __name__ == "__main__":
    destination = ROOT / "contracts"
    destination.mkdir(exist_ok=True)
    for name, value in documents().items():
        (destination / name).write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print("Exported implemented OpenAPI, Phase 4 evidence/AI schemas and synthetic examples.")
