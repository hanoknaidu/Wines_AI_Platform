"""Liveness and index-loaded readiness, split deliberately.

A process that is up but has no dataset must fail readyz: serving a conversation with
no rows to cite would produce exactly the uncited answer the design exists to prevent.
"""

from __future__ import annotations

from fastapi import APIRouter

from ...db.engine import ping
from ...deps import ServicesDep
from ...schemas import HealthResponse, ReadyResponse

router = APIRouter(tags=["platform"])


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/readyz", response_model=ReadyResponse)
async def readyz(services: ServicesDep) -> ReadyResponse:
    db = await ping(services.db)
    if not services.ready or db != "ok":
        from fastapi.responses import JSONResponse

        body = ReadyResponse(
            status="not_ready", db=db, engine=services.settings.engine
        ).model_dump(by_alias=True)
        body["detail"] = (
            services.dataset_error
            or services.provider_error
            or "database unavailable"
        )
        body["serving"] = services.describe_engine()
        return JSONResponse(body, status_code=503)

    index = services.index
    assert index is not None
    return ReadyResponse(
        status="ready",
        db=db,
        dataset_version=index.version,
        row_count=index.row_count,
        indexes=index.index_sizes(),
        engine=services.settings.engine,
        serving=services.describe_engine(),
    )
