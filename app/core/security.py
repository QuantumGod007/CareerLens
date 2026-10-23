import secrets
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader

from app.core.errors import DomainError

token_header = APIKeyHeader(name="X-CareerLens-Token", auto_error=False,
    description="Persistent local session token from the private local-session.json file; never share it.")


def local_session(request: Request, token: str | None = Depends(token_header)) -> UUID:
    local = request.app.state.local
    if not token or not secrets.compare_digest(token, local.token):
        raise DomainError("LOCAL_SESSION_REQUIRED", "A valid local session token is required.", 401)
    return local.id
