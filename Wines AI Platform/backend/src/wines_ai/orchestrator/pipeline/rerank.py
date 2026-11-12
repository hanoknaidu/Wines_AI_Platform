"""Stages G and H: score the pair jointly, then spread the winners across variety.

G - RERANK. The diagram calls for a cross-encoder: a model that reads the query and
    the candidate TOGETHER and scores the pair, rather than comparing two independently
    computed vectors. It is the single biggest quality lever in the pipeline and the
    stage naive RAG skips.

    This implementation is a joint feature scorer, not a neural cross-encoder, and the
    distinction is worth being exact about. What it keeps from the idea: the score is a
    function of (query, candidate) evaluated together, so it can use evidence a
    bi-encoder structurally cannot - which query terms this row actually contains,
    whether this row's variety was named, and how far this row's axes are from what
    the user asked for. What it gives up: the semantic judgement a trained model makes
    about whether a note answers a question.

    Loading a real cross-encoder means `torch`, and at 30 candidates over 45 rows the
    features below carry the ranking. The protocol is a function of the same shape, so
    the swap is one import. Measuring it against the eval tap is how anyone would know
    it is time.

H - MMR. Maximal Marginal Relevance across GRAPE VARIETY. Three Cabernets, a Malbec
    and a Syrah teaches the user something; five Cabernets does not, and it hedges
    against one wrong inference. Also where stage B's sub-query groups merge.
"""

from __future__ import annotations

from ...taste.axes import AXES_BY_ID, level_index
from ..retrieval.bm25 import tokenize
from ..retrieval.index import document_text
from .types import Candidate

# Weights. Term overlap dominates because it is the only signal that reads the actual
# query text; axis distance is a correction, not the ranking.
W_OVERLAP = 1.0
W_VARIETY = 0.6
W_AXIS = 0.8
W_FUSED = 0.4


AXIS_IDS = ("sweetness", "body", "oak", "tannin", "acidity", "fruit_savoury")


def _axis_agreement(row, profile: dict) -> float:
    """1.0 when every stated axis matches, falling off with level distance.

    Weighted by each axis's own weight, so a sweetness miss costs what a sweetness
    miss costs - the heaviest axis in the product - rather than one sixth of the score.
    """
    total = 0.0
    denom = 0.0
    for axis_id in AXIS_IDS:
        target = profile.get(axis_id)
        if not target:
            continue
        t = level_index(axis_id, target)
        a = level_index(axis_id, getattr(row, axis_id, None))
        if t is None or a is None:
            continue
        span = max(1, len(AXES_BY_ID[axis_id].levels) - 1)
        weight = AXES_BY_ID[axis_id].weight or 1.0
        total += (1.0 - abs(t - a) / span) * weight
        denom += weight
    if denom == 0.0:
        # Nothing stated to agree with: neutral, not zero. Zero would rank a row the
        # user said nothing about below one that happens to mismatch.
        return 0.5
    return round(total / denom, 6)


def rerank(
    candidates: list[Candidate], *, query: str, profile: dict, top_n: int
) -> list[Candidate]:
    """Stage G. Scores each (query, candidate) pair jointly; returns the top n."""
    query_terms = set(tokenize(query))
    named_variety = {t for t in query_terms if len(t) > 3}

    for candidate in candidates:
        doc_terms = set(tokenize(document_text(candidate.row)))
        overlap = (
            len(query_terms & doc_terms) / len(query_terms) if query_terms else 0.0
        )
        variety_terms = set(tokenize(candidate.row.variety))
        # An explicitly named varietal is the strongest signal a user can send, and
        # the one the dense arm is worst at: "Malbec" and "Merlot" embed close
        # together and are not substitutes.
        variety_hit = 1.0 if variety_terms & named_variety else 0.0
        candidate.rerank = round(
            W_OVERLAP * overlap
            + W_VARIETY * variety_hit
            + W_AXIS * _axis_agreement(candidate.row, profile)
            + W_FUSED * candidate.fused,
            6,
        )

    ordered = sorted(candidates, key=lambda c: (-c.rerank, c.row_id))
    return ordered[:top_n]


def _variety_key(variety: str) -> str:
    return variety.split("(")[0].strip().lower()


def mmr(
    candidates: list[Candidate], *, want: int, lambda_: float, min_results: int
) -> list[Candidate]:
    """Stage H. Relevance against redundancy, where redundancy is shared variety.

    score = lambda * relevance - (1 - lambda) * max_similarity_to_already_chosen,
    with similarity 1.0 for the same variety and 0.0 otherwise. That similarity is
    deliberately binary: the quantity the product cares about is "did we show this
    grape already", and a continuous text similarity would let five Cabernets through
    on the strength of five different tasting notes.

    **The variety cap is hard, not a penalty, while unused varieties remain.** A pure
    MMR penalty is the textbook formulation and it is wrong here, which only showed up
    on a real response: asked for "a buttery white, Chardonnay maybe", relevance for
    the two Chardonnay rows beat the penalty and both were served. That is defensible
    on its own terms - oaked and unoaked Chardonnay are genuinely different wines - but
    `taste/diversify.py` caps lane 2 at one row per variety and backfills only to reach
    `results_min`, so allowing it here would mean the two engines answer the same
    question differently on FR-7, with no setting that says so. The cap matches lane 2;
    `lambda_` still orders the choices within it.
    """
    if not candidates:
        return []
    pool = sorted(candidates, key=lambda c: (-c.rerank, c.row_id))
    chosen: list[Candidate] = []
    used: set[str] = set()
    # Sub-query groups must each be represented before any group gets a second row.
    groups = sorted({c.group for c in pool})

    while pool and len(chosen) < want:
        best: Candidate | None = None
        best_score = float("-inf")
        exhausted = len({_variety_key(c.row.variety) for c in pool} - used) == 0
        for candidate in pool:
            seen = _variety_key(candidate.row.variety) in used
            if seen and not exhausted:
                # An unused variety is still available: this row cannot take its slot.
                continue
            score = lambda_ * candidate.rerank - (1.0 - lambda_) * (1.0 if seen else 0.0)
            if len(groups) > 1:
                # Round-robin across groups: a turn that asked for two things must not
                # be answered entirely from the first.
                represented = {c.group for c in chosen}
                if candidate.group in represented and len(represented) < len(groups):
                    score -= 1.0
            if score > best_score:
                best, best_score = candidate, score
        if best is None:
            break
        chosen.append(best)
        used.add(_variety_key(best.row.variety))
        pool.remove(best)

    if len(chosen) < min_results:
        # Backfill: relaxing the spread beats returning two results when five good
        # matches exist. The spread is a preference, not a cap on the count.
        for candidate in sorted(candidates, key=lambda c: (-c.rerank, c.row_id)):
            if candidate not in chosen:
                chosen.append(candidate)
            if len(chosen) >= min_results:
                break
    return chosen


def variety_count(candidates: list[Candidate]) -> int:
    return len({_variety_key(c.row.variety) for c in candidates})
