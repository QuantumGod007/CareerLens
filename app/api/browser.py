"""Local browser pairing never returns the persistent API token."""
from fastapi import APIRouter, Request, Response

from app.core.security import COOKIE, SESSION_SECONDS, browser_boundary
from app.schemas.api import BrowserSessionView

router = APIRouter(prefix="/api/v1/browser-session", tags=["local browser"])


@router.post("", response_model=BrowserSessionView)
def connect(request: Request, response: Response):
    origin = browser_boundary(request, mutation=True)
    sessions = request.app.state.browser_sessions
    sessions.revoke(request.cookies.get(COOKIE))
    response.set_cookie(COOKIE, sessions.issue(origin), max_age=SESSION_SECONDS,
                        httponly=True, samesite="strict", path="/api/v1",
                        secure=request.url.scheme == "https")
    return {"connected": True}


@router.post("/disconnect", response_model=BrowserSessionView)
def disconnect(request: Request, response: Response):
    browser_boundary(request, mutation=True)
    request.app.state.browser_sessions.revoke(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/api/v1", httponly=True, samesite="strict")
    return {"connected": False}
