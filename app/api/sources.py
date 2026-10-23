from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import func, select

from app.core.errors import DomainError
from app.core.security import local_session
from app.persistence.models import SourceBoard, SourceListing, JobSnapshot
from app.schemas.api import BoardView, JobsPage, RefreshCommand, TaskReference
from app.services.tasks import enqueue_refresh

router = APIRouter(prefix="/api/v1/source-boards", tags=["source boards"])


@router.get("", response_model=list[BoardView])
def boards(request: Request, owner: UUID = Depends(local_session)):
    with request.app.state.database.read() as session:
        return list(session.scalars(select(SourceBoard).order_by(SourceBoard.slug)))


@router.post("/{board_id}/refresh", status_code=202, response_model=TaskReference)
def refresh(board_id: UUID, command: RefreshCommand, request: Request,
            idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1,
                max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")], owner: UUID = Depends(local_session)):
    return enqueue_refresh(request.app.state.database, board_id, owner, UUID(request.state.correlation_id),
                           idempotency_key, command.expected_revision)


@router.get("/{board_id}/jobs", response_model=JobsPage)
def jobs(board_id: UUID, request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 20,
         offset: Annotated[int, Query(ge=0)] = 0, owner: UUID = Depends(local_session)):
    with request.app.state.database.read() as session:
        board = session.get(SourceBoard, board_id)
        if board is None:
            raise DomainError("NOT_FOUND", "Source board not found.", 404)
        query = select(JobSnapshot).join(SourceListing, SourceListing.job_snapshot_id == JobSnapshot.id).where(
            SourceListing.source_board_id == board.id)
        count = session.scalar(select(func.count()).select_from(SourceListing).where(SourceListing.source_board_id == board.id))
        rows = list(session.scalars(query.order_by(JobSnapshot.title, JobSnapshot.id).offset(offset).limit(limit)))
        return {"items": rows, "total": count, "offset": offset, "limit": limit,
                "last_refreshed_at": board.refreshed_at}
