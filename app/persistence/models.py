from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (Boolean, CheckConstraint, ForeignKey, Index, Integer, JSON, String,
                        Text, UniqueConstraint, Uuid, DateTime, text)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Timezone-aware UTC timestamp required")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value is not None else None


class Base(DeclarativeBase):
    pass


class IdentityMixin:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Candidate(IdentityMixin, Base):
    __tablename__ = "candidates"
    session_id: Mapped[UUID] = mapped_column(Uuid, unique=True)


class Artifact(IdentityMixin, Base):
    __tablename__ = "artifacts"
    session_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    relative_path: Mapped[str] = mapped_column(String(180), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    media_type: Mapped[str] = mapped_column(String(80))
    __table_args__ = (CheckConstraint("size >= 0", name="artifact_size_nonnegative"),)


class ProfileVersion(IdentityMixin, Base):
    __tablename__ = "profile_versions"
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("candidates.id"))
    version: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    source_artifact_id: Mapped[UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    profile_json: Mapped[dict] = mapped_column(JSON)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    __table_args__ = (UniqueConstraint("candidate_id", "version"),)


class Fact(IdentityMixin, Base):
    __tablename__ = "facts"
    profile_version_id: Mapped[UUID] = mapped_column(ForeignKey("profile_versions.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    value_json: Mapped[dict] = mapped_column(JSON)
    provenance: Mapped[str] = mapped_column(String(20))
    source_ref: Mapped[dict | None] = mapped_column(JSON)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    __table_args__ = (CheckConstraint("provenance IN ('extracted','user')", name="fact_provenance"),)


class SourceBoard(IdentityMixin, Base):
    __tablename__ = "source_boards"
    family: Mapped[str] = mapped_column(String(30))
    slug: Mapped[str] = mapped_column(String(100))
    employer: Mapped[str] = mapped_column(String(150))
    allowed_hosts: Mapped[list] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    validated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    refreshed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    __table_args__ = (UniqueConstraint("family", "slug"),)


class JobSnapshot(IdentityMixin, Base):
    __tablename__ = "job_snapshots"
    source_board_id: Mapped[UUID] = mapped_column(ForeignKey("source_boards.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(100))
    canonical_job_key: Mapped[str] = mapped_column(String(200), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime())
    title: Mapped[str] = mapped_column(String(300))
    employer: Mapped[str] = mapped_column(String(150))
    location: Mapped[str | None] = mapped_column(String(200))
    employment_type: Mapped[str | None] = mapped_column(String(100))
    raw_text: Mapped[str] = mapped_column(Text)
    structured_json: Mapped[dict] = mapped_column(JSON, default=dict)
    source_url: Mapped[str] = mapped_column(Text)
    apply_url: Mapped[str] = mapped_column(Text)
    pipeline_version: Mapped[str] = mapped_column(String(50), default="lever-v2")
    __table_args__ = (UniqueConstraint("source_board_id", "external_id", "content_hash"),)


class SourceListing(Base):
    """Current board membership is mutable; historical snapshots never are."""
    __tablename__ = "source_listings"
    source_board_id: Mapped[UUID] = mapped_column(ForeignKey("source_boards.id"), primary_key=True)
    external_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    job_snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("job_snapshots.id"))


class Search(IdentityMixin, Base):
    __tablename__ = "searches"
    profile_version_id: Mapped[UUID] = mapped_column(ForeignKey("profile_versions.id"))
    title: Mapped[str] = mapped_column(String(200))
    filters: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(40))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class SearchResult(Base):
    __tablename__ = "search_results"
    search_id: Mapped[UUID] = mapped_column(ForeignKey("searches.id"), primary_key=True)
    job_snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("job_snapshots.id"), primary_key=True)


class ResumeVersion(IdentityMixin, Base):
    __tablename__ = "resume_versions"
    profile_version_id: Mapped[UUID] = mapped_column(ForeignKey("profile_versions.id"))
    job_snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("job_snapshots.id"))
    pdf_artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"))
    content_json: Mapped[dict] = mapped_column(JSON)
    pipeline_version: Mapped[str] = mapped_column(String(50))


class ResumeUpload(IdentityMixin, Base):
    __tablename__ = "resume_uploads"
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("candidates.id"), index=True)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"))
    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id"), unique=True)
    profile_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("profile_versions.id"))
    state: Mapped[str] = mapped_column(String(30), default="QUEUED")
    error_code: Mapped[str | None] = mapped_column(String(80))


class JobAnalysis(IdentityMixin, Base):
    __tablename__ = "job_analyses"
    search_id: Mapped[UUID] = mapped_column(ForeignKey("searches.id"), index=True)
    profile_version_id: Mapped[UUID] = mapped_column(ForeignKey("profile_versions.id"))
    job_snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("job_snapshots.id"))
    content_hash: Mapped[str] = mapped_column(String(64))
    analysis_json: Mapped[dict] = mapped_column(JSON)
    assessment_json: Mapped[dict] = mapped_column(JSON)
    pipeline_version: Mapped[str] = mapped_column(String(50))


class ResumeGeneration(IdentityMixin, Base):
    __tablename__ = "resume_generations"
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("candidates.id"), index=True)
    profile_version_id: Mapped[UUID] = mapped_column(ForeignKey("profile_versions.id"))
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("job_analyses.id"))
    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id"), unique=True)
    state: Mapped[str] = mapped_column(String(30), default="QUEUED")
    consent_at: Mapped[datetime] = mapped_column(UTCDateTime())
    consent_version: Mapped[str] = mapped_column(String(50))
    input_hash: Mapped[str] = mapped_column(String(64))
    stage_json: Mapped[dict] = mapped_column(JSON, default=dict)
    verification_json: Mapped[dict | None] = mapped_column(JSON)
    resume_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("resume_versions.id"))
    error_code: Mapped[str | None] = mapped_column(String(80))


class Application(IdentityMixin, Base):
    __tablename__ = "applications"
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("candidates.id"))
    canonical_job_key: Mapped[str] = mapped_column(String(200))
    state: Mapped[str] = mapped_column(String(40), default="CREATED")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    active_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("preparation_runs.id"))
    send_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    __table_args__ = (UniqueConstraint("candidate_id", "canonical_job_key"),)


class PreparationRun(IdentityMixin, Base):
    __tablename__ = "preparation_runs"
    application_id: Mapped[UUID] = mapped_column(ForeignKey("applications.id"), index=True)
    profile_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("profile_versions.id"))
    job_snapshot_id: Mapped[UUID | None] = mapped_column(ForeignKey("job_snapshots.id"))
    resume_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("resume_versions.id"))
    mode: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(40), default="CREATED")
    current_step: Mapped[str | None] = mapped_column(String(80))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (CheckConstraint("mode IN ('dry_run','review')", name="preparation_mode"),)


class QuestionAnswer(IdentityMixin, Base):
    __tablename__ = "question_answers"
    run_id: Mapped[UUID] = mapped_column(ForeignKey("preparation_runs.id"))
    field_key: Mapped[str] = mapped_column(String(150))
    revision: Mapped[int] = mapped_column(Integer)
    metadata_json: Mapped[dict] = mapped_column(JSON)
    value_json: Mapped[dict] = mapped_column(JSON)
    confirmed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    __table_args__ = (UniqueConstraint("run_id", "field_key", "revision"),)


class Approval(IdentityMixin, Base):
    __tablename__ = "approvals"
    run_id: Mapped[UUID] = mapped_column(ForeignKey("preparation_runs.id"), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    actor_session_id: Mapped[UUID] = mapped_column(Uuid)
    approved_revision: Mapped[int] = mapped_column(Integer)
    invalidated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Task(IdentityMixin, Base):
    __tablename__ = "tasks"
    session_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    kind: Mapped[str] = mapped_column(String(50))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[UUID] = mapped_column(Uuid)
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("preparation_runs.id"))
    business_key: Mapped[str | None] = mapped_column(String(200))
    correlation_id: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", index=True)
    current_step: Mapped[str] = mapped_column(String(80), default="QUEUED")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    lease_owner: Mapped[UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    possible_send_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    result_json: Mapped[dict | None] = mapped_column(JSON)
    input_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(80))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    __table_args__ = (
        CheckConstraint("status IN ('QUEUED','RUNNING','WAITING','SUCCEEDED','FAILED','CANCELLED')", name="task_status"),
        CheckConstraint("progress BETWEEN 0 AND 100", name="task_progress"),
        Index("uq_active_task_business", "business_key", unique=True,
              sqlite_where=text("status IN ('QUEUED','RUNNING','WAITING')")),
    )


class Event(IdentityMixin, Base):
    __tablename__ = "events"
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    correlation_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(80))
    metadata_json: Mapped[dict] = mapped_column(JSON)


class IdempotencyRecord(IdentityMixin, Base):
    __tablename__ = "idempotency_records"
    session_id: Mapped[UUID] = mapped_column(Uuid)
    route: Mapped[str] = mapped_column(String(180))
    key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int] = mapped_column(Integer)
    response_json: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("session_id", "route", "key"),)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    owner: Mapped[UUID] = mapped_column(Uuid)
    heartbeat_at: Mapped[datetime] = mapped_column(UTCDateTime())
    lease_expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    running: Mapped[bool] = mapped_column(Boolean)
