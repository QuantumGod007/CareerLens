from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException


class DomainError(Exception):
    def __init__(self, code: str, message: str, status: int = 409, *, retryable: bool = False):
        super().__init__(code)
        self.code, self.message, self.status, self.retryable = code, message, status, retryable


def envelope(code: str, message: str, correlation_id: str, retryable: bool = False, details=None):
    return {"error": {"code": code, "message": message, "retryable": retryable,
                      "details": details or {}}, "correlation_id": correlation_id}


def handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain(request: Request, error: DomainError):
        return JSONResponse(envelope(error.code, error.message, request.state.correlation_id,
                                     error.retryable), status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def validation(request: Request, error: RequestValidationError):
        # Never reflect invalid values or the request body, which may contain secrets.
        fields = [{"location": list(item["loc"]), "type": item["type"]} for item in error.errors()]
        return JSONResponse(envelope("VALIDATION_ERROR", "Request validation failed.",
            request.state.correlation_id, details={"fields": fields}), status_code=422)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        return JSONResponse(envelope("HTTP_ERROR", "The request could not be served.",
                            request.state.correlation_id), status_code=error.status_code)

    @app.exception_handler(OperationalError)
    async def database_error(request: Request, error: OperationalError):
        return JSONResponse(envelope("DATABASE_UNAVAILABLE", "The database is temporarily unavailable.",
                            request.state.correlation_id, True), status_code=503)
