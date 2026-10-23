from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from app.core.errors import DomainError
from app.core.security import local_session
from app.persistence.models import Event, Task
from app.schemas.api import EventView, TaskView

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


def owned_task(session, task_id, owner):
    task = session.get(Task, task_id)
    if not task or task.session_id != owner:
        raise DomainError("NOT_FOUND", "Task not found.", 404)
    return task


@router.get("/{task_id}", response_model=TaskView)
def task_view(task_id: UUID, request: Request, owner: UUID = Depends(local_session)):
    with request.app.state.database.read() as session:
        task = owned_task(session, task_id, owner)
        fields = TaskView.model_fields.keys() - {"result", "retry_eligible"}
        return {**{name: getattr(task, name) for name in fields}, "result": task.result_json,
            "retry_eligible": task.kind == "source_refresh" and task.possible_send_at is None
                and task.status == "WAITING" and task.attempts < task.max_attempts}


@router.get("/{task_id}/events", response_model=list[EventView])
def task_events(task_id: UUID, request: Request, owner: UUID = Depends(local_session)):
    with request.app.state.database.read() as session:
        owned_task(session, task_id, owner)
        events = session.scalars(select(Event).where(Event.entity_type == "task", Event.entity_id == task_id)
                                .order_by(Event.created_at, Event.id).limit(100))
        return [{"id": e.id, "kind": e.kind, "correlation_id": e.correlation_id,
                 "created_at": e.created_at, "metadata": e.metadata_json} for e in events]
