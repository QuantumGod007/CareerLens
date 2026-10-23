from fastapi import APIRouter, Request

from app import __version__
from app.persistence.models import WorkerHeartbeat, utcnow
from app.schemas.api import HealthView

router = APIRouter()


@router.get("/health", response_model=HealthView, tags=["health"])
def health(request: Request):
    database = request.app.state.database
    db_ready = database.ping()
    heartbeat = None
    if db_ready:
        with database.read() as session:
            heartbeat = session.get(WorkerHeartbeat, "primary")
    ready = bool(heartbeat and heartbeat.running and heartbeat.lease_expires_at > utcnow())
    return {"version": __version__, "api_ready": db_ready, "database_ready": db_ready,
            "ready": db_ready and ready, "worker": {"ready": ready,
            "heartbeat_at": heartbeat.heartbeat_at if heartbeat else None,
            "lease_expires_at": heartbeat.lease_expires_at if heartbeat else None},
            "groq_key_present": bool(request.app.state.settings.groq_key.get_secret_value()),
            "groq_model": request.app.state.settings.groq_model, "fallback_enabled": False}
