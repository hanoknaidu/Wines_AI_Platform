"""Taste ingestion: POST a tasting note in your own words; it becomes a searchable row.

KNOWN tastes are answered from the matched catalogue row; UNKNOWN tastes are profiled
by an LLM and enriched by web search. Both are embedded and stored as `unreviewed`.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ...deps import AgeGate, ReadyServicesDep
from ...errors import ApiProblem
from ...ingest import IngestRejected

router = APIRouter(prefix="/tastes", tags=["tastes"], dependencies=[AgeGate])


class TasteUpload(BaseModel):
    note: str = Field(min_length=1, max_length=4000)


class TasteRow(BaseModel):
    row_id: str
    variety: str
    style: str
    sweetness: str
    body: str
    oak: str
    tannin: str
    acidity: str
    fruit_savoury: str
    description: str
    typical_regions: list[str]
    example_producers: list[str]
    review_status: str


class TasteIngestResponse(BaseModel):
    path: Literal["known", "unknown", "duplicate"]
    created: bool
    row: TasteRow
    matched_row: TasteRow | None = None
    match_score: float | None = None
    scorer: str = ""
    sources: list[dict] = Field(default_factory=list)
    degraded: list[str] = Field(default_factory=list)
    trace: list[dict] = Field(default_factory=list)


def _row(row) -> TasteRow:
    return TasteRow(**row.model_dump(include=set(TasteRow.model_fields)))


@router.post("", response_model=TasteIngestResponse, status_code=201)
async def ingest_taste(body: TasteUpload, services: ReadyServicesDep) -> TasteIngestResponse:
    if services.ingestor is None:
        raise ApiProblem(503, "ingest_disabled", "Ingestion disabled",
                         "Taste ingestion is turned off on this deployment.")
    try:
        result = await services.ingestor.ingest(body.note)
    except IngestRejected as exc:
        raise ApiProblem(422, "taste_rejected", "Taste not ingested", str(exc)) from exc
    return TasteIngestResponse(
        path=result.path,
        created=result.created,
        row=_row(result.row),
        matched_row=_row(result.matched_row) if result.matched_row else None,
        match_score=result.match_score,
        scorer=result.scorer,
        sources=result.sources,
        degraded=result.degraded,
        trace=result.trace,
    )
