"""Evidence and bounded AI contracts used by the Phase 4 resume pipeline."""
from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue, model_validator

from app.schemas.api import StrictCommand


class SourceSpan(StrictCommand):
    page: int | None = Field(ge=1)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=1)
    source_text: str = Field(min_length=1)

    @model_validator(mode="after")
    def ordered(self):
        if self.end_offset <= self.start_offset:
            raise ValueError("Source offsets must be ordered")
        return self


class SourcedFact(StrictCommand):
    id: UUID
    kind: str
    value: JsonValue
    source_ref: SourceSpan


class ProfileDraft(StrictCommand):
    contact: dict[str, str | None]
    education: list[str]
    skills: list[str]
    projects: list[str]
    experience: list[str]
    other_sections: dict[str, list[str]]
    facts: list[SourcedFact]
    warnings: list[str]


class SkillRequirement(StrictCommand):
    canonical_name: str
    verbatim_text: str
    source_span: SourceSpan


class EvidenceStatement(StrictCommand):
    text: str
    source_span: SourceSpan


class StructuredJD(StrictCommand):
    title: str | None
    employer: str | None
    required_skills: list[SkillRequirement]
    preferred_skills: list[SkillRequirement]
    responsibilities: list[EvidenceStatement]
    eligibility: list[EvidenceStatement]
    uncertainties: list[str]


class GeneratedClaim(StrictCommand):
    item_id: str
    section: str
    text: str
    source_fact_ids: list[UUID] = Field(min_length=1)


class ChangeRecord(StrictCommand):
    section: str
    item_id: str
    before: str
    after: str
    reason: str
    source_fact_ids: list[UUID] = Field(min_length=1)


class TailoredContent(StrictCommand):
    claims: list[GeneratedClaim] = Field(max_length=8)
    changes: list[ChangeRecord] = Field(max_length=8)
    selected_section_order: list[str]


class ClaimViolation(StrictCommand):
    item_id: str
    reason: str
    source_fact_ids: list[UUID]


class VerificationResult(StrictCommand):
    passed: bool = Field(alias="pass")
    violations: list[ClaimViolation]
    uncertain_claims: list[ClaimViolation]

    @model_validator(mode="after")
    def uncertainty_is_not_pass(self):
        if self.passed and (self.violations or self.uncertain_claims):
            raise ValueError("A result with violations or uncertainty cannot pass")
        return self
