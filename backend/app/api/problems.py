"""RFC 7807 problem+json error responses with stable error codes (plan BE-1)."""

from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger()
PROBLEM_JSON = "application/problem+json"


class ProblemError(Exception):
    """Raise for expected, typed API errors (e.g. 409 state conflicts)."""

    def __init__(self, status: int, code: str, title: str, detail: str | None = None) -> None:
        self.status, self.code, self.title, self.detail = status, code, title, detail


def problem(status: int, code: str, title: str, detail: str | None = None, **extra: object) -> JSONResponse:
    body = {"type": f"about:blank#{code}", "title": title, "status": status, "code": code}
    if detail:
        body["detail"] = detail
    body.update(extra)
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


def install_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    async def _problem(_: Request, exc: ProblemError) -> JSONResponse:
        return problem(exc.status, exc.code, exc.title, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return problem(422, "VALIDATION_ERROR", "Request validation failed", errors=errors)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return problem(exc.status_code, f"HTTP_{exc.status_code}", str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", error_type=type(exc).__name__)
        return problem(500, "INTERNAL_ERROR", "Internal server error")  # no stack traces to clients
