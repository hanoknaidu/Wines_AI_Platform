"""App factory and lifespan.

Boots with no API key, no network, no orchestrator and no frontend.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import errors
from .api.v1 import age_gate, conversations, feedback, health, meta, tastes, turns
from .config import Settings, get_settings
from .db.engine import create_all, create_engine
from .db.repositories import logs as logs_repo
from .middleware.core import (
    AgeGateMiddleware,
    RateLimitMiddleware,
    RequestIdMiddleware,
    SessionMiddleware,
    ShieldMiddleware,
)
from .observability import configure_logging, log
from .services.container import build

logger = logging.getLogger("wines_ai.main")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = create_engine(settings)
        await create_all(db)
        services = build(settings, db)
        # Prime the global daily spend so a restart does not reset the ceiling.
        async with db.connect() as conn:
            spent = await logs_repo.global_cost_today(conn)
        services.cost_guard.prime(global_today=spent)
        app.state.services = services
        log(
            logger,
            logging.INFO,
            "startup",
            engine=settings.engine,
            wire_case=settings.wire_case,
            dataset_version=services.index.version if services.index else None,
            row_count=services.index.row_count if services.index else 0,
            dataset_error=services.dataset_error,
            spent_today_usd=spent,
        )
        try:
            yield
        finally:
            services.registry.cancel_all()
            await db.dispose()
            log(logger, logging.INFO, "shutdown")

    app = FastAPI(
        title="Wines AI API",
        version="0.1.0",
        description=(
            "Conversational wine recommendation served from a frozen, reviewed dataset. "
            "Every claim carries the dataset row id it came from."
        ),
        lifespan=lifespan,
    )

    # Added innermost-first: Starlette runs the LAST added middleware outermost, so
    # this order produces request-id -> log -> shield -> CORS -> session -> age -> rate.
    app.add_middleware(RateLimitMiddleware, settings=settings)
    app.add_middleware(AgeGateMiddleware)
    app.add_middleware(SessionMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        # Cookies are load-bearing here, so the origin list must be explicit: with
        # credentials on, "*" is not allowed by the browser.
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id"],
    )
    app.add_middleware(ShieldMiddleware)
    app.add_middleware(RequestIdMiddleware)

    errors.install(app)

    v1 = APIRouter(prefix="/api/v1")
    v1.include_router(health.router)
    v1.include_router(age_gate.router)
    v1.include_router(meta.router)
    v1.include_router(conversations.router)
    v1.include_router(turns.router)
    v1.include_router(feedback.router)
    v1.include_router(tastes.router)
    app.include_router(v1)

    @app.get("/", include_in_schema=False)
    async def root() -> dict:
        return {"service": "wines-ai", "docs": "/docs", "api": "/api/v1"}

    return app


app = create_app()
