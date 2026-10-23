from contextlib import asynccontextmanager
import os
import time
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__
from app.api import health, tasks, sources, artifacts
from app.core.config import Settings, identity, load_settings
from app.core.errors import envelope, handlers
from app.core.logging import configure, record
from app.persistence.database import Database
from app.schemas.api import ErrorEnvelope
from app.tools.init_db import HEAD


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(api):
        os.umask(0o077)
        configure()
        api.state.local = identity(settings)
        database = Database(settings)
        try:
            with database.read() as session:
                revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
            if revision != HEAD:
                raise RuntimeError("Run python -m app.tools.init_db before starting the API")
            api.state.database = database
            yield
        finally:
            database.close()

    app = FastAPI(title="CareerLens backend foundation", version=__version__, lifespan=lifespan,
        description="Phase 2: persisted public-source refresh, task polling and private artifacts. No employer submission API.",
        responses={code: {"model": ErrorEnvelope} for code in (400, 401, 403, 404, 409, 422, 500, 503)})
    app.state.settings = settings
    handlers(app)

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        started = time.perf_counter()
        supplied = request.headers.get("X-Correlation-ID", "")
        try:
            correlation_id = str(UUID(supplied))
        except ValueError:
            correlation_id = str(uuid4())
        request.state.correlation_id = correlation_id
        host = request.url.hostname
        origin = request.headers.get("origin")
        code = None
        if host not in settings.allowed_hosts:
            code = "UNTRUSTED_HOST"
        elif origin is not None and origin not in settings.allowed_origins:
            code = "ORIGIN_NOT_ALLOWED"
        elif request.headers.get("sec-fetch-site") == "cross-site":
            code = "CROSS_SITE_REQUEST"
        if code:
            response = JSONResponse(envelope(code, "Local request boundary rejected the request.", correlation_id), status_code=403)
        elif request.method == "OPTIONS":
            response = JSONResponse({}, headers={"Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Idempotency-Key, X-CareerLens-Token, X-Correlation-ID"})
        else:
            try:
                response = await call_next(request)
            except Exception:
                # Do not log exception text, request values or SDK/SQL parameter dumps.
                record("request_error", correlation_id=correlation_id, error_code="INTERNAL_ERROR")
                response = JSONResponse(envelope("INTERNAL_ERROR", "An internal error occurred.", correlation_id), status_code=500)
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        if origin in settings.allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        record("request", correlation_id=correlation_id, status_code=response.status_code,
               duration_ms=round((time.perf_counter() - started) * 1000))
        return response

    for module in (health, sources, tasks, artifacts):
        app.include_router(module.router)
    return app


app = create_app()
