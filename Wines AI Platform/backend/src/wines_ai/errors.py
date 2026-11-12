"""RFC 9457 problem+json. No stack trace ever reaches a user (NFR-7)."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .observability import METRICS, log, request_id_var

logger = logging.getLogger("wines_ai.errors")


class ApiProblem(Exception):
    """A failure with a user-presentable detail and a stable machine-readable code."""

    def __init__(self, status: int, code: str, title: str, detail: str) -> None:
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        super().__init__(detail)

    def body(self) -> dict[str, object]:
        return {
            "type": "about:blank",
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "code": self.code,
            "request_id": request_id_var.get(),
        }


def age_not_confirmed() -> ApiProblem:
    return ApiProblem(
        403,
        "age_not_confirmed",
        "Age confirmation required",
        "Confirm you are 21 or older before starting a conversation.",
    )


def conversation_not_found(cid: str) -> ApiProblem:
    return ApiProblem(
        404, "conversation_not_found", "Conversation not found", f"No conversation {cid}."
    )


def turn_not_found(tid: str) -> ApiProblem:
    return ApiProblem(
        404, "turn_not_found", "Turn not found", f"Turn {tid} is unknown or has expired."
    )


def turn_in_flight(tid: str) -> ApiProblem:
    return ApiProblem(
        409,
        "turn_in_flight",
        "A turn is already running",
        f"Turn {tid} is still in flight for this conversation. Wait for it or cancel it.",
    )


def dataset_unavailable() -> ApiProblem:
    return ApiProblem(
        503,
        "dataset_unavailable",
        "Recommendations unavailable",
        "The wine dataset is not loaded, so no recommendation can be grounded in it.",
    )


def engine_unavailable(engine: str) -> ApiProblem:
    return ApiProblem(
        503,
        "engine_unavailable",
        "Engine unavailable",
        f"The '{engine}' engine needs the orchestrator extra installed and configured.",
    )


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiProblem)
    async def _problem(_: Request, exc: ApiProblem) -> JSONResponse:
        METRICS.incr(f"error.{exc.code}")
        return JSONResponse(
            exc.body(), status_code=exc.status, media_type="application/problem+json"
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        problem = ApiProblem(
            exc.status_code, "http_error", "Request failed", str(exc.detail or "Request failed.")
        )
        return JSONResponse(
            problem.body(), status_code=exc.status_code, media_type="application/problem+json"
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        problem = ApiProblem(
            422, "validation_error", "Invalid request", "The request body failed validation."
        )
        body = problem.body()
        body["errors"] = exc.errors()
        return JSONResponse(body, status_code=422, media_type="application/problem+json")

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Logged with its traceback server-side; the client gets a code and a request id.
        log(logger, logging.ERROR, "unhandled_exception", error=repr(exc))
        logger.exception("unhandled")
        METRICS.incr("error.internal")
        problem = ApiProblem(
            500, "internal_error", "Something went wrong", "The request could not be completed."
        )
        return JSONResponse(problem.body(), status_code=500, media_type="application/problem+json")
