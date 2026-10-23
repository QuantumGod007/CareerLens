from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class BrowserSessionView(BaseModel):
    connected: bool


class RefreshCommand(StrictCommand):
    expected_revision: int | None = Field(default=None, ge=1)


class View(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class ErrorDetail(View):
    code: str
    message: str
    retryable: bool
    details: dict


class ErrorEnvelope(View):
    error: ErrorDetail
    correlation_id: UUID


class TaskReference(View):
    task_id: UUID
    entity_type: Literal["source_board"]
    entity_id: UUID
    status_url: str


class RefreshResult(View):
    entity_type: Literal["source_board"]
    entity_id: UUID
    listing_count: int
    new_snapshots: int
    reused_snapshots: int
    duplicates_removed: int
    data_origin: Literal["live", "fixture"]


class TaskView(View):
    id: UUID
    correlation_id: UUID
    entity_type: str
    entity_id: UUID
    kind: str
    status: Literal["QUEUED", "RUNNING", "WAITING", "SUCCEEDED", "FAILED", "CANCELLED"]
    current_step: str
    progress: int
    attempts: int
    max_attempts: int
    retry_eligible: bool
    retry_at: datetime | None
    lease_owner: UUID | None
    lease_expires_at: datetime | None
    heartbeat_at: datetime | None
    error_code: str | None
    result: RefreshResult | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class BoardView(View):
    id: UUID
    family: str
    slug: str
    employer: str
    enabled: bool
    revision: int
    validated_at: datetime | None
    refreshed_at: datetime | None
    last_error_code: str | None


class JobView(View):
    id: UUID
    external_id: str
    canonical_job_key: str
    title: str
    employer: str
    location: str | None
    employment_type: str | None
    source_url: str
    apply_url: str
    fetched_at: datetime
    content_hash: str


class JobsPage(View):
    items: list[JobView]
    total: int
    offset: int
    limit: int
    last_refreshed_at: datetime | None


class WorkerStatus(View):
    ready: bool
    heartbeat_at: datetime | None
    lease_expires_at: datetime | None


class HealthView(View):
    version: str
    api_ready: bool
    database_ready: bool
    ready: bool
    worker: WorkerStatus
    groq_key_present: bool
    groq_model: str
    fallback_enabled: Literal[False]


class EventView(View):
    id: UUID
    kind: str
    correlation_id: UUID
    created_at: datetime
    metadata: dict
