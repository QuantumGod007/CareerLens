from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.core.security import local_session
from app.services.artifacts import ArtifactStore
from app.persistence.models import Artifact

router = APIRouter(prefix="/api/v1/artifacts", tags=["artifacts"])


@router.get("/{artifact_id}", response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}, "application/pdf": {}}, "description": "Verified private artifact bytes"}})
def download(artifact_id: UUID, request: Request, owner: UUID = Depends(local_session)):
    data = ArtifactStore(request.app.state.database).read(artifact_id, owner)
    with request.app.state.database.read() as session:
        pdf = session.get(Artifact,artifact_id).media_type == "application/pdf"
    return Response(data, media_type="application/pdf" if pdf else "application/octet-stream", headers={
        "Content-Disposition": f'attachment; filename="{artifact_id}.{"pdf" if pdf else "bin"}"',
        "X-Content-Type-Options": "nosniff"})
