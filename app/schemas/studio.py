from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.schemas.api import StrictCommand, View, JobView
from app.schemas.ai import SourceSpan, StructuredJD, TailoredContent, VerificationResult, ClaimViolation

Identifier = Annotated[UUID, Field(strict=False)]
FactKind = Literal["name", "email", "phone", "links", "summary", "skills", "education", "projects", "experience", "certifications", "achievements", "other"]


class PageText(View):
    page: int
    text: str
    start_offset: int
    end_offset: int


class FactView(View):
    id: UUID
    stable_id: UUID
    kind: FactKind
    text: str
    provenance: Literal["extracted", "user"]
    source_ref: SourceSpan | None
    extraction_method: Literal['local','groq','user'] = 'local'


class ProfileSummary(View):
    id: UUID
    version: int
    revision: int
    source_artifact_id: UUID | None
    confirmed_at: datetime | None
    created_at: datetime


class ProfileParsing(View):
    requested_mode: Literal['local','groq'] = 'local'
    mode: Literal['local','groq','local_fallback'] = 'local'
    provider: Literal['groq','controlled_fixture'] | None = None
    model: Literal['openai/gpt-oss-120b','openai/gpt-oss-20b'] | None = None
    error_code: str | None = None
    consent_version: str | None = None
    prompt_version: str | None = None
    schema_version: str = 'profile-v1'


class ProfileView(ProfileSummary):
    facts: list[FactView]
    pages: list[PageText]
    warnings: list[str]
    parsing: ProfileParsing = Field(default_factory=ProfileParsing)


class FactEdit(StrictCommand):
    fact_id: Identifier | None = None
    kind: FactKind
    text: str = Field(min_length=1, max_length=4000)


class CorrectionCommand(StrictCommand):
    expected_revision: int = Field(ge=1)
    corrections: list[FactEdit] = Field(min_length=1, max_length=200)


class RevisionCommand(StrictCommand):
    expected_revision: int = Field(ge=1)


class SearchFilters(StrictCommand):
    location: str | None = Field(default=None, min_length=1, max_length=150)
    remote: bool | None = None
    employment_type: str | None = Field(default=None, min_length=1, max_length=100)


class SearchCommand(StrictCommand):
    profile_version_id: Identifier
    preferred_title: str = Field(min_length=2, max_length=120)
    filters: SearchFilters = Field(default_factory=SearchFilters)


class DecisionCommand(RevisionCommand):
    decision: Literal["continue_requested_role", "change_role"]
    preferred_title: str | None = Field(default=None, min_length=2, max_length=120)


class SelectionCommand(RevisionCommand):
    job_snapshot_id: Identifier


class SearchJob(JobView):
    match_explanation: str
    source_refreshed_at: datetime | None


class SearchView(View):
    id: UUID
    profile_version_id: UUID
    title: str
    original_title: str
    filters: SearchFilters
    state: Literal["RUNNING", "NEEDS_ROLE_DECISION", "COMPLETED", "FAILED"]
    revision: int
    warning: str | None
    reason: str | None
    task_id: UUID | None
    selected_analysis_id: UUID | None
    results: list[SearchJob]
    created_at: datetime


class SkillMatch(View):
    skill: str
    status: Literal["supported", "not_evidenced"]
    source_fact_ids: list[UUID]
    evidence_kinds: list[str]


class Assessment(View):
    required: list[SkillMatch]
    preferred: list[SkillMatch]
    coverage: float | None
    reason: str | None
    eligibility: list[str]
    scope: str


class AnalysisView(View):
    id: UUID
    search_id: UUID
    profile_version_id: UUID
    job_snapshot_id: UUID
    job_title: str
    employer: str
    content_hash: str
    raw_text: str
    structured: StructuredJD
    assessment: Assessment
    pipeline_version: str
    model: str | None
    created_at: datetime


class GenerationCommand(StrictCommand):
    analysis_id: Identifier
    profile_version_id: Identifier
    consent: bool
    consent_version: Literal["groq-resume-v2"]


class GenerationSummary(View):
    id: UUID
    profile_version_id: UUID
    analysis_id: UUID
    task_id: UUID
    state: Literal["QUEUED", "RUNNING", "VERIFIED", "BLOCKED", "FAILED"]
    resume_version_id: UUID | None
    error_code: str | None
    created_at: datetime


class PDFChecks(View):
    extractable_text: Literal["pass"]
    contact_preservation: Literal["pass"]
    section_order: Literal["pass"]
    no_unexpected_omissions: Literal["pass"]
    text_bounds: Literal["pass"]
    visual_layout: Literal["not_assessed"]
    pages: int


class ResumeContent(View):
    tailored: TailoredContent
    verification: VerificationResult
    reverted_item_ids: list[str]
    review_findings: list[ClaimViolation] = Field(default_factory=list)
    repair_count: int = Field(default=0,ge=0,le=1)
    original_assessment: Assessment
    tailored_assessment: Assessment
    pdf_checks: PDFChecks
    provider: Literal["groq", "controlled_fixture"]
    model: Literal["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    stage_models: dict[str, Literal["openai/gpt-oss-120b", "openai/gpt-oss-20b"]] = Field(default_factory=dict)
    fallback_used: bool = False
    pipeline_version: str
    prompt_version: str
    schema_version: str


class ProviderDiagnostic(View):
    model: Literal["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    purpose: Literal["DRAFT", "VERIFY", "REPAIR", "VERIFY_REPAIR", "PROFILE"]
    http_status: int
    headers: dict[str, str]
    limiting_factor: str
    scope: Literal["model", "shared", "unknown"]
    limited_model: str | None
    retry_after_seconds: float | None
    retry_not_before: datetime | None
    limit: float | None = None
    used: float | None = None
    requested: float | None = None
    fallback_decision: str | None = None
    usage: dict[str, int] | None = None


class GenerationView(GenerationSummary):
    job_title: str
    employer: str
    original_artifact_id: UUID | None
    pdf_artifact_id: UUID | None
    pdf_sha256: str | None
    verification: VerificationResult | None
    content: ResumeContent | None
    consent_at: datetime
    consent_version: str
    provider_diagnostics: list[ProviderDiagnostic] = Field(default_factory=list)
