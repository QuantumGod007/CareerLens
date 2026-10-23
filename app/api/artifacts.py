from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.core.security import local_session
from app.services.artifacts import ArtifactStore

router = APIRouter(prefix="/api/v1/artifacts", tags=["artifacts"])


@router.get("/{artifact_id}", response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}, "description": "Verified private artifact bytes"}})
def download(artifact_id: UUID, request: Request, owner: UUID = Depends(local_session)):
    data = ArtifactStore(request.app.state.database).read(artifact_id, owner)
    return Response(data, media_type="application/octet-stream", headers={
        "Content-Disposition": f'attachment; filename="{artifact_id}.bin"',
        "X-Content-Type-Options": "nosniff"})
