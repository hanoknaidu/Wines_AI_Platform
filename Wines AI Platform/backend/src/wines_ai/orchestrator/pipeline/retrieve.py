"""Stages D, E and F: plan the retrieval, run three arms, fuse the ranked lists.

D - PLANNER. Slots become filters: style is a HARD pre-filter, sweetness a band, body
    and oak soft weights. The filters are applied inside each arm, not after it, so
    top-k is k relevant rows rather than k rows followed by a filter that empties the
    list - which is the single most common way a hybrid retriever returns nothing.
E - THREE ARMS, run concurrently. Dense catches paraphrase, sparse catches the exact
    varietal and region terms embeddings blur, structured guarantees a recall floor
    when both text sides miss. The floor is the point: a corpus of 45 rows has no
    redundancy, so an empty text result must not mean an empty answer.
F - FUSION. Reciprocal Rank Fusion, k=60: score(d) = sum over arms of 1/(k + rank).
    Rank-based, so the three arms' incomparable score scales never have to be
    normalised - a cosine of 0.31, a BM25 of 7.4 and a structured hit have no common
    unit, and inventing one is where naive hybrid search goes wrong.
"""

from __future__ import annotations

import asyncio

from ...config import Settings
from ...dataset.loader import DatasetIndex
from ...taste.axes import level_at, level_index
from ..retrieval import RetrievalIndexes
from .types import Candidate, QueryPlan


def plan(
    *, query: str, profile: dict, settings: Settings, group: int = 0, widen: bool = False
) -> QueryPlan:
    """Stage D. `widen` relaxes the sweetness band for a refine turn's widened set."""
    style = profile.get("style")
    sweetness = profile.get("sweetness")

    band: tuple[str, ...] = ()
    if sweetness:
        idx = level_index("sweetness", sweetness)
        if idx is not None:
            spread = settings.sweetness_tolerance_levels + (1 if widen else 0)
            values = []
            for offset in range(-spread, spread + 1):
                value = level_at("sweetness", idx + offset)
                if value and value not in values:
                    values.append(value)
            band = tuple(values)

    soft = {
        axis: profile[axis]
        for axis in ("body", "oak", "tannin", "acidity", "fruit_savoury")
        if profile.get(axis)
    }
    return QueryPlan(
        query=query,
        style=style,
        sweetness_band=band,
        soft_weights=soft,
        k_dense=settings.retriever_k,
        k_sparse=settings.retriever_k,
        k_structured=settings.retriever_k,
        group=group,
    )


def _allowed(index: DatasetIndex, plan_: QueryPlan) -> set[str]:
    """The pre-filter, as a row-id set each arm intersects with as it ranks."""
    rows = index.for_style(plan_.style) if plan_.style else index.rows
    if plan_.sweetness_band:
        rows = [row for row in rows if row.sweetness in plan_.sweetness_band]
    return {row.row_id for row in rows}


async def retrieve(
    *,
    index: DatasetIndex,
    indexes: RetrievalIndexes,
    plan_: QueryPlan,
    hyde_text: str,
) -> dict[str, list[tuple[str, float]]]:
    """Stages E1-E3, run concurrently. -> {arm: [(row_id, score), ...]}.

    The arms are pure CPU over an in-process index, so `to_thread` is what makes the
    concurrency real rather than three sequential calls wearing a gather.
    """
    allowed = _allowed(index, plan_)

    def dense() -> list[tuple[str, float]]:
        # HyDE text, not the question: note-to-note beats question-to-note.
        # The allow-list is pushed into the query (a Qdrant payload filter), so top-K
        # is K eligible rows.
        return indexes.dense(hyde_text or plan_.query, k=plan_.k_dense, allowed=allowed)

    def sparse() -> list[tuple[str, float]]:
        hits = indexes.sparse(plan_.query, k=plan_.k_sparse * 2)
        return [pair for pair in hits if pair[0] in allowed][: plan_.k_sparse]

    def structured() -> list[tuple[str, float]]:
        """Range scan on the axes: the recall floor.

        Ranked by how many soft axes agree, so it is a ranked list like the other two
        and RRF can consume it without a special case.
        """
        scored: list[tuple[str, float]] = []
        for row_id in allowed:
            row = index.resolve(row_id)
            if row is None:
                continue
            agree = 0
            for axis, target in plan_.soft_weights.items():
                if getattr(row, axis, None) == target:
                    agree += 1
            scored.append((row_id, float(agree)))
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored[: plan_.k_structured]

    dense_hits, sparse_hits, structured_hits = await asyncio.gather(
        asyncio.to_thread(dense),
        asyncio.to_thread(sparse),
        asyncio.to_thread(structured),
    )
    return {"dense": dense_hits, "sparse": sparse_hits, "structured": structured_hits}


def fuse(
    *,
    index: DatasetIndex,
    arms: dict[str, list[tuple[str, float]]],
    rrf_k: int,
    top_n: int,
    group: int = 0,
) -> list[Candidate]:
    """Stage F. RRF over the ranked lists, deduped by row_id."""
    by_row: dict[str, Candidate] = {}
    for arm, hits in arms.items():
        for rank, (row_id, score) in enumerate(hits, start=1):
            row = index.resolve(row_id)
            if row is None:
                continue
            candidate = by_row.get(row_id)
            if candidate is None:
                candidate = Candidate(row=row, group=group)
                by_row[row_id] = candidate
            candidate.ranks[arm] = rank
            candidate.arm_scores[arm] = score
            candidate.fused += 1.0 / (rrf_k + rank)

    fused = sorted(by_row.values(), key=lambda c: (-c.fused, c.row_id))
    return fused[:top_n]
