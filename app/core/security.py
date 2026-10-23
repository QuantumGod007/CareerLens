import secrets
import hashlib
import ipaddress
import threading
import time
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import APIKeyCookie, APIKeyHeader

from app.core.errors import DomainError

token_header = APIKeyHeader(name="X-CareerLens-Token", auto_error=False,
    description="Persistent local session token from the private local-session.json file; never share it.")
COOKIE = "careerlens_browser"
cookie_header = APIKeyCookie(name=COOKIE, auto_error=False,
    description="HttpOnly local browser session. Issued only to same-origin loopback requests.")
SESSION_SECONDS = 12 * 60 * 60
session_clock = time.monotonic


def browser_boundary(request: Request, *, mutation: bool = False) -> str:
    """Cookies are site scoped; explicitly enforce the origin (including port) too."""
    origin = str(request.base_url).rstrip("/")
    content_type = request.headers.get("content-type", "").split(";")[0]
    allowed_content = {"application/json"}
    if request.method == "POST" and request.url.path == "/api/v1/profiles":
        allowed_content = {"multipart/form-data"}
    try:
        loopback = request.client and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        loopback = False
    if (not loopback or request.url.hostname not in ("127.0.0.1", "localhost", "::1")
            or origin not in request.app.state.settings.allowed_origins
            or request.headers.get("sec-fetch-site") != "same-origin"
            or request.headers.get("origin", origin) != origin
            or (mutation and (request.headers.get("origin") != origin
                or request.headers.get("X-CareerLens-Local") != "1"
                or content_type not in allowed_content))):
        raise DomainError("BROWSER_ORIGIN_REQUIRED", "Open CareerLens directly on its local address and reconnect.", 403)
    return origin


class BrowserSessions:
    """Small process-local capability store. Only digests are retained; restart revokes all."""

    def __init__(self):
        self._sessions = {}
        self._lock = threading.Lock()

    def valid(self, token: str | None, origin: str) -> bool:
        if not token or len(token) > 100:
            return False
        with self._lock:
            value = self._sessions.get(hashlib.sha256(token.encode()).digest())
            return bool(value and value[0] == origin and value[1] > session_clock())

    def issue(self, origin: str) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            now = session_clock()
            self._sessions = {k: v for k, v in self._sessions.items() if v[1] > now}
            if len(self._sessions) >= 128:
                del self._sessions[next(iter(self._sessions))]
            self._sessions[hashlib.sha256(token.encode()).digest()] = (origin, now + SESSION_SECONDS)
        return token

    def revoke(self, token: str | None):
        if token:
            with self._lock:
                self._sessions.pop(hashlib.sha256(token.encode()).digest(), None)


def local_session(request: Request, token: str | None = Depends(token_header),
                  cookie: str | None = Depends(cookie_header)) -> UUID:
    local = request.app.state.local
    if token is not None:
        if secrets.compare_digest(token, local.token):
            return local.id
    elif cookie:
        origin = browser_boundary(request, mutation=request.method not in ("GET", "HEAD"))
        if request.app.state.browser_sessions.valid(cookie, origin):
            return local.id
    raise DomainError("LOCAL_SESSION_REQUIRED", "Connect to your local CareerLens session.", 401)
