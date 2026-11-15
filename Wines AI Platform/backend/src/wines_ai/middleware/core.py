"""The middleware chain, outermost first:

    request-id -> access log -> exception shield -> CORS -> session cookie
               -> age-gate guard -> per-IP rate limit -> route

This deviates from the diagram, which draws request-id and logging innermost. Taken
literally, a rate-limited request or an age-gate rejection would carry no
X-Request-Id and leave no log line - the two failures most likely to need tracing in a
group demo. Request-id outermost, with the shield just inside it, makes every response
traceable and every rejection logged.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict

from itsdangerous import BadSignature, URLSafeSerializer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ..config import Settings
from ..observability import METRICS, log, request_id_var

logger = logging.getLogger("wines_ai.http")

# Open without age confirmation. Everything else is a chat route and is gated.
OPEN_PATHS = (
    "/api/v1/age-gate",
    "/api/v1/meta/",
    "/api/v1/healthz",
    "/api/v1/readyz",
    "/openapi.json",
    "/docs",
    "/redoc",
    "/",
)


def _is_open(path: str) -> bool:
    return any(path == p or path.startswith(p) for p in OPEN_PATHS)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Outermost. Every response carries X-Request-Id, including every rejection."""

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get("x-request-id")
        request_id = incoming or f"req-{uuid.uuid4().hex[:12]}"
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        started = time.monotonic()
        try:
            response = await call_next(request)
        finally:
            elapsed = (time.monotonic() - started) * 1000
            METRICS.observe(f"http {request.method} {request.url.path}", elapsed)
            request_id_var.reset(token)
        response.headers["X-Request-Id"] = request_id
        log(
            logger,
            logging.INFO,
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            ms=round(elapsed, 2),
        )
        METRICS.incr(f"http.{response.status_code}")
        return response


class SessionMiddleware(BaseHTTPMiddleware):
    """Mints an anonymous signed user id on first contact, and reads the age cookie.

    The age cookie is signed, not a bare flag - a client-set `wa_age=1` must not pass.
    """

    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings
        self.signer = URLSafeSerializer(settings.cookie_secret, salt="wines-ai")

    def _read(self, request: Request, name: str) -> str | None:
        raw = request.cookies.get(name)
        if not raw:
            return None
        try:
            return str(self.signer.loads(raw))
        except BadSignature:
            return None

    async def dispatch(self, request: Request, call_next):
        user_id = self._read(request, self.settings.session_cookie_name)
        minted = False
        if not user_id:
            user_id = f"u-{uuid.uuid4().hex[:12]}"
            minted = True
        request.state.user_id = user_id
        request.state.age_confirmed = self._read(request, self.settings.age_cookie_name) == user_id

        response = await call_next(request)

        if minted:
            response.set_cookie(
                self.settings.session_cookie_name,
                self.signer.dumps(user_id),
                max_age=self.settings.cookie_max_age_seconds,
                httponly=True,
                samesite="lax",
                secure=self.settings.cookie_secure,
            )
        return response


class AgeGateMiddleware(BaseHTTPMiddleware):
    """Blocks every chat route until confirmed, re-checked server-side on each call."""

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS" or _is_open(request.url.path):
            return await call_next(request)
        if not getattr(request.state, "age_confirmed", False):
            METRICS.incr("error.age_not_confirmed")
            return JSONResponse(
                {
                    "type": "about:blank",
                    "title": "Age confirmation required",
                    "status": 403,
                    "detail": "Confirm you are 21 or older before starting a conversation.",
                    "code": "age_not_confirmed",
                    "request_id": getattr(request.state, "request_id", None),
                },
                status_code=403,
                media_type="application/problem+json",
            )
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP token bucket over an in-process TTL map (band 3, Phase 1).

    Also a cost control: a bounded number of turns can ever be started per minute, so
    a runaway client cannot run up a model bill.
    """

    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings
        self._buckets: dict[tuple[str, str], list[float]] = defaultdict(list)

    def _limit_for(self, request: Request) -> tuple[str, int]:
        path = request.url.path
        if request.method == "POST" and path.endswith("/messages"):
            return "turns", self.settings.rate_limit_turns_per_min
        return "reads", self.settings.rate_limit_reads_per_min

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        client = request.client.host if request.client else "unknown"
        kind, limit = self._limit_for(request)
        now = time.monotonic()
        window = self._buckets[(client, kind)]
        cutoff = now - 60.0
        window[:] = [t for t in window if t > cutoff]

        if len(window) >= limit:
            retry_after = max(1, int(60 - (now - window[0])))
            METRICS.incr("error.rate_limited")
            return JSONResponse(
                {
                    "type": "about:blank",
                    "title": "Too many requests",
                    "status": 429,
                    "detail": f"Rate limit of {limit} {kind} per minute exceeded.",
                    "code": "rate_limited",
                    "request_id": getattr(request.state, "request_id", None),
                },
                status_code=429,
                media_type="application/problem+json",
                headers={"Retry-After": str(retry_after)},
            )

        window.append(now)
        return await call_next(request)


class ShieldMiddleware(BaseHTTPMiddleware):
    """Last resort: nothing unhandled escapes as a stack trace (NFR-7)."""

    async def dispatch(self, request: Request, call_next) -> Response:
        try:
            return await call_next(request)
        except Exception as exc:  # noqa: BLE001
            log(logger, logging.ERROR, "unhandled_in_middleware", error=repr(exc))
            logger.exception("unhandled_in_middleware")
            METRICS.incr("error.internal")
            return JSONResponse(
                {
                    "type": "about:blank",
                    "title": "Something went wrong",
                    "status": 500,
                    "detail": "The request could not be completed.",
                    "code": "internal_error",
                    "request_id": getattr(request.state, "request_id", None),
                },
                status_code=500,
                media_type="application/problem+json",
            )
