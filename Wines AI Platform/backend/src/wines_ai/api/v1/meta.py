"""The vocabulary and provenance endpoints.

/meta/taste-axes is the single source of truth for every label, level, hedge and
refine chip, so no wine word is ever hardcoded in the frontend.
"""

from __future__ import annotations

from fastapi import APIRouter

from ...db.repositories import logs as logs_repo
from ...deps import ServicesDep, UserDep
from ...errors import dataset_unavailable
from ...schemas import (
    AxisLevel,
    AxisSpec,
    ChipOption,
    DatasetVersionResponse,
    RefineChip,
    TasteAxesResponse,
    UsageResponse,
)
from ...taste.axes import AXES, REFINE_CHIPS
from ...taste.interview import style_options

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/taste-axes", response_model=TasteAxesResponse)
async def taste_axes(services: ServicesDep) -> TasteAxesResponse:
    return TasteAxesResponse(
        axes=[
            AxisSpec(
                id=axis.id,
                asked=axis.asked,
                question_order=axis.question_order,
                prompt=axis.prompt,
                applies_to=list(axis.applies_to),
                levels=[
                    AxisLevel(value=lv.value, label=lv.label, hedged_label=lv.hedged_label)
                    for lv in axis.levels
                ],
            )
            for axis in AXES
        ],
        refine_chips=[RefineChip(**chip) for chip in REFINE_CHIPS],
        confidence_threshold=services.settings.confidence_threshold,
        styles=[ChipOption(**opt) for opt in style_options()],
    )


@router.get("/dataset-version", response_model=DatasetVersionResponse)
async def dataset_version(services: ServicesDep) -> DatasetVersionResponse:
    index = services.index
    if index is None:
        raise dataset_unavailable()
    return DatasetVersionResponse(
        dataset_version=index.version,
        row_count=index.row_count,
        review_status_counts=index.review_status_counts,
        built_at=index.built_at,
        checksum=index.checksum,
    )


@router.get("/usage", response_model=UsageResponse)
async def usage(services: ServicesDep, user_id: UserDep) -> UsageResponse:
    """Session-scoped spend. Cost is only ever controlled if something reports it."""
    async with services.db.connect() as conn:
        stats = await logs_repo.session_usage(conn, user_id=user_id)
    spend = float(stats.get("cost_usd") or 0.0)
    return UsageResponse(
        turns=int(stats.get("turns") or 0),
        tokens_in=int(stats.get("tokens_in") or 0),
        tokens_out=int(stats.get("tokens_out") or 0),
        cost_usd=round(spend, 6),
        engine=services.settings.engine,
        cache_hits=int(stats.get("cache_hits") or 0),
        ceiling_per_session_usd=services.settings.cost_ceiling_per_session_usd,
        degraded=spend >= services.settings.cost_ceiling_per_session_usd,
    )
