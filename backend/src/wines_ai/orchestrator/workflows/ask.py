"""The ASK workflow (the diagram's RECOMMEND workflow): band 2, end to end.

    A rewrite -> B decompose -> C expand -> D plan -> E1/E2/E3 -> F fuse
      -> G rerank -> abstention gate -> H diversify -> I pack -> J generate -> K verify

Three things in here are load-bearing and easy to lose in a refactor.

**The abstention gate sits between G and H, not after the answer.** FR-13 requires an
honest empty state rather than a silently widened filter, and the gate is the same one
lane 2 enforces: a candidate more than `sweetness_tolerance_levels` from the sweetness
that was asked for is not a match at all. It runs BEFORE diversify because MMR's job
is to spread good matches across varieties, and spreading bad ones across varieties
just produces five different wrong answers. It runs before packing because a row that
cannot be shown must not reach the generator - the cheapest way to stop a model
explaining a bad match is for it never to see one.

**The generator cannot reach the index.** It is handed `PackedContext` and the user's
own words, and nothing else. Every field that asserts a fact about a wine is copied
from the row by `turns/grounding.py` after this workflow yields, so the only text the
model actually owns is the lead-in and the per-card reason.

**Every model call here has a non-model answer.** The lead-in, the card reason and the
verifier all degrade to templated copy drawn from the row. A turn in which the gateway
is down, the budget is spent and the provider refuses still produces cards - the same
cards, with flatter prose. That is the difference between a cost control and an outage.
"""

from __future__ import annotations

import asyncio
import logging

from ...observability import METRICS, log
from ...taste import copy as copytext
from ...taste import ranking
from ...taste import refine as refine_mod
from ...taste.axes import AXES_BY_ID, level_index
from ...turns.engine import (
    CardEvent,
    Checkpoint,
    ChipsEvent,
    CitationEvent,
    RetrievalTrace,
    Token,
)
from .. import pipeline
from ..gateway import BudgetExceeded, GatewayError, ModelDelta
from ..prompts import CARD_REASON, LEAD_IN
from ..state import Context

logger = logging.getLogger("wines_ai.workflows.ask")


async def run(
    ctx: Context, *, anchor_row_ids: list[str] | None = None, label: str = "recommend"
):
    """Yields TurnEvents. `anchor_row_ids` and `label` are set by the refine workflow.

    `label` is what the turn reports to `transaction_log.intent` and the intent eval
    set, and it is the workflow that OWNS the turn rather than the one that produced
    the cards. An interview turn that fills the last slot and goes on to recommend is
    a `recommend` - the user got cards. A refine turn is a `refine` even though it
    also ends in cards, because the action that defines it is the one-axis delta
    against what was already on screen. Mislabelling either corrupts the eval set,
    which is the one thing in this lane that cannot be recomputed later.
    """
    state = ctx.state
    settings = ctx.settings
    state.effective_intent = label

    # --- A, B, C: the conversation never reaches the retriever raw --------
    state.query, resolved, state.rewrite_source = await pipeline.rewrite(
        ctx.gateway,
        ctx.ledger,
        model=ctx.models["rewriter"],
        utterance=state.utterance,
        profile=state.profile,
        history=state.history,
        previous_row_ids=state.previous_row_ids,
    )
    state.nodes_run.append("rewrite")
    yield Checkpoint(
        node="rewrite",
        state={"query": state.query, "resolved": resolved, "source": state.rewrite_source},
    )
    yield RetrievalTrace(stage="rewrite", query_text=state.query, candidate_row_ids=[])

    state.sub_queries = await pipeline.decompose(
        ctx.gateway, ctx.ledger, model=ctx.models["rewriter"], utterance=state.utterance
    )
    if state.sub_queries:
        state.nodes_run.append("decompose")
        yield Checkpoint(node="decompose", state={"sub_queries": state.sub_queries})

    # Stage C is applied two ways: the unasked axes the utterance states are merged
    # into the profile for this turn only, and the HyDE note is what the dense arm
    # actually embeds.
    harvested = pipeline.harvest_consumer_words(state.utterance)
    working_profile = {**state.profile}
    for axis, value in harvested.items():
        working_profile.setdefault(axis, value)

    # --- D, E, F: per sub-query, then merged -----------------------------
    queries = state.sub_queries or [state.query]
    fused: list[pipeline.Candidate] = []
    for group, query in enumerate(queries):
        plan_ = pipeline.plan(
            query=query,
            profile=working_profile,
            settings=settings,
            group=group,
            widen=bool(anchor_row_ids),
        )
        yield Checkpoint(node=f"plan.{group}", state=plan_.trace())

        arms = await pipeline.retrieve(
            index=ctx.index,
            indexes=ctx.indexes,
            plan_=plan_,
            hyde_text=pipeline.hyde(working_profile, query),
        )
        for arm, hits in arms.items():
            yield RetrievalTrace(
                stage=f"retrieve.{arm}",
                query_text=query,
                candidate_row_ids=[row_id for row_id, _ in hits],
                ranks=list(range(1, len(hits) + 1)),
                scores=[score for _, score in hits],
            )

        group_fused = pipeline.fuse(
            index=ctx.index,
            arms=arms,
            rrf_k=settings.rrf_k,
            top_n=30,
            group=group,
        )
        yield RetrievalTrace(
            stage=f"fuse.{group}",
            query_text=query,
            candidate_row_ids=[c.row_id for c in group_fused],
            ranks=list(range(1, len(group_fused) + 1)),
            scores=[c.fused for c in group_fused],
        )
        fused.extend(group_fused)

    # Anchoring: a refine keeps the rows the user actually saw in play, so the
    # correction is relative to what was on screen rather than a fresh search.
    if anchor_row_ids:
        present = {c.row_id for c in fused}
        carried: list[str] = []
        for row_id in anchor_row_ids:
            row = ctx.index.resolve(row_id)
            if row is not None and row_id not in present:
                fused.append(pipeline.Candidate(row=row, fused=0.0))
                carried.append(row_id)
        # Traced as its own stage: "which rows were carried over from what the user
        # was looking at" is the question a refine turn has to be able to answer, and
        # it is not recoverable from the arm traces, which never saw them.
        yield RetrievalTrace(
            stage="anchor",
            query_text=state.query,
            candidate_row_ids=list(anchor_row_ids),
            scores=[1.0 if rid in carried else 0.0 for rid in anchor_row_ids],
        )

    state.candidates = fused
    if not fused:
        async for event in _empty_state(ctx, working_profile, reason="no_candidates"):
            yield event
        return

    # --- G: score the pair jointly ---------------------------------------
    reranked = pipeline.rerank(
        fused, query=state.query, profile=working_profile, top_n=settings.rerank_top_n
    )
    state.nodes_run.append("rerank")
    yield RetrievalTrace(
        stage="rerank",
        query_text=state.query,
        candidate_row_ids=[c.row_id for c in reranked],
        ranks=list(range(1, len(reranked) + 1)),
        scores=[c.rerank for c in reranked],
    )

    # --- the abstention gate (FR-13) -------------------------------------
    in_range, best_distance = _gate(reranked, working_profile, settings)
    if not in_range:
        METRICS.incr("ask.abstained")
        async for event in _empty_state(
            ctx, working_profile, reason="below_match_floor", best_distance=best_distance
        ):
            yield event
        return

    # --- H: spread across variety ----------------------------------------
    chosen = pipeline.mmr(
        in_range,
        want=settings.results_max,
        lambda_=settings.mmr_lambda,
        min_results=settings.results_min,
    )
    state.chosen = chosen
    state.nodes_run.append("diversify")
    yield RetrievalTrace(
        stage="diversify",
        query_text=state.query,
        candidate_row_ids=[c.row_id for c in chosen],
        ranks=list(range(1, len(chosen) + 1)),
        scores=[c.rerank for c in chosen],
    )
    yield Checkpoint(
        node="diversify",
        state={
            "row_ids": [c.row_id for c in chosen],
            "variety_count": pipeline.variety_count(chosen),
        },
    )

    # --- I: pack ----------------------------------------------------------
    packed = pipeline.pack(
        chosen, budget=settings.context_token_budget, threshold=settings.confidence_threshold
    )
    state.packed = packed
    state.nodes_run.append("pack")
    yield Checkpoint(node="pack", state=packed.trace())
    # A row dropped at the budget cannot be shown: its card would have no source in
    # the context the generator saw, which is exactly what the verifier rejects.
    packed_ids = set(packed.row_ids)
    chosen = [c for c in chosen if c.row_id in packed_ids]
    if not chosen:
        async for event in _empty_state(ctx, working_profile, reason="packing_dropped_all"):
            yield event
        return

    # Per-axis distances, for the templated copy and the hedging. Computed from the
    # same ranking module lane 2 uses, so the two engines explain a match identically.
    scored_by_id = {
        s.row.row_id: s
        for s in ranking.rank([c.row for c in chosen], working_profile)
    }

    # --- J: generate ------------------------------------------------------
    threshold = settings.confidence_threshold
    lead_fallback = _lead_in_fallback(len(chosen), working_profile)
    async for token in _stream_prose(
        ctx,
        prompt=LEAD_IN,
        payload={
            "kind": "lead_in",
            "count": len(chosen),
            "profile_labels": _profile_labels(working_profile),
            "utterance": state.utterance,
            "fallback": lead_fallback,
        },
        fallback=lead_fallback,
    ):
        yield token

    # One reason per card, fanned out. They are independent calls over disjoint rows,
    # and running them in sequence was 7.7s of a 14s turn on the first live run -
    # against an architecture whose own amendment puts p95 at 2-4s. Order is preserved
    # by `gather`, and nothing is streamed from these calls, so concurrency changes
    # latency and nothing else.
    fallbacks = [
        copytext.why_it_matches(
            c.row,
            working_profile,
            (scored_by_id.get(c.row_id).per_axis if scored_by_id.get(c.row_id) else {}),
            threshold,
        )
        for c in chosen
    ]
    requests = [
        CARD_REASON.build(
            ctx.models["generator"],
            {
                "kind": "card_reason",
                "row": pipeline.render_row(c.row, threshold=threshold),
                "asked_for": _profile_labels(working_profile),
                "utterance": state.utterance,
                "confidence_threshold": threshold,
                "fallback": fallback,
            },
        )
        for c, fallback in zip(chosen, fallbacks, strict=True)
    ]
    reasons = await _fan_out(ctx, requests, fallbacks)

    claims: list[dict] = []
    cards: list[CardEvent] = []
    for candidate, reason in zip(chosen, reasons, strict=True):
        row = candidate.row
        claims.append({"row_id": row.row_id, "text": reason})
        cards.append(
            CardEvent(
                row_id=row.row_id,
                payload={
                    "row_id": row.row_id,
                    "variety": row.variety,
                    "style": row.style,
                    "axes": copytext.axis_readings(row, threshold),
                    "description": copytext.tastes_like(row),
                    "why_it_matches": reason,
                    "typical_regions": list(row.typical_regions),
                    "example_producers": list(row.example_producers),
                    "review_status": row.review_status,
                    "dataset_version": row.dataset_version,
                },
            )
        )

    # --- K: verify, then emit --------------------------------------------
    grounded, unsupported, source = await pipeline.verify(
        ctx.gateway,
        ctx.ledger,
        model=ctx.models["verifier"],
        packed=packed,
        claims=claims,
        enabled=settings.verify_enabled,
    )
    state.verified, state.unsupported_row_ids, state.verify_source = (
        grounded,
        unsupported,
        source,
    )
    state.nodes_run.append("verify")
    yield Checkpoint(
        node="verify",
        state={"grounded": grounded, "unsupported": unsupported, "source": source},
    )

    if unsupported:
        # One repair pass, then templated copy drawn straight from the row. The card
        # itself survives - the row is real and the guard will rebuild its fields; it
        # is the sentence that failed, so the sentence is what gets replaced.
        METRICS.incr("ask.verify_repair")
        log(
            logger,
            logging.WARNING,
            "verify_repair",
            turn_id=state.turn_id,
            unsupported=unsupported,
        )
        failed = set(unsupported)
        for card in cards:
            if card.row_id in failed:
                scored = scored_by_id.get(card.row_id)
                card.payload["why_it_matches"] = copytext.why_it_matches(
                    ctx.index.resolve(card.row_id) or scored.row,
                    working_profile,
                    scored.per_axis if scored else {},
                    threshold,
                )

    for card in cards:
        yield card

    yield CitationEvent(row_ids=[card.row_id for card in cards])
    yield ChipsEvent(payload={"kind": "refine", "options": refine_mod.chips_payload()})


# --- the abstention gate -------------------------------------------------
def _gate(
    candidates: list[pipeline.Candidate], profile: dict, settings
) -> tuple[list[pipeline.Candidate], float | None]:
    """FR-13, applied before diversify and before packing.

    Two parts, for the reason config.py states at length: the sweetness tolerance is
    the real gate, because a weighted average can always be dragged back under a
    threshold by other axes agreeing, and no amount of agreement about body makes a
    sweet wine an answer to "not sweet at all". The distance floor is the backstop.
    """
    scored = {s.row.row_id: s for s in ranking.rank([c.row for c in candidates], profile)}
    target = profile.get("sweetness")
    t = level_index("sweetness", target) if target else None

    keep: list[pipeline.Candidate] = []
    best: float | None = None
    for candidate in candidates:
        item = scored.get(candidate.row_id)
        distance = item.distance if item else 1.0
        best = distance if best is None else min(best, distance)
        if t is not None:
            a = level_index("sweetness", candidate.row.sweetness)
            if a is None or abs(a - t) > settings.sweetness_tolerance_levels:
                continue
        if distance > settings.max_match_distance:
            continue
        keep.append(candidate)
    return keep, best


async def _empty_state(ctx: Context, profile: dict, *, reason: str, best_distance=None):
    """An honest empty state is the correct answer, not a degraded one.

    `degraded_reason` is deliberately NOT set here: it means "the answer you got is
    lower fidelity than it should have been", and the client raises a notice on it.
    An abstention is the product working - FR-13 requires it - so the reason is
    recorded in the checkpoint, where it explains the turn without apologising for it.
    """
    yield Checkpoint(
        node="empty_state",
        state={"reason": reason, "best_distance": best_distance, "profile": profile},
    )
    # Templated, from the profile. Never a widened filter and never a model call: the
    # one thing a model must not do here is persuade the user to accept a bad match.
    for token in _tokens(copytext.empty_state(profile)):
        yield token
    yield ChipsEvent(payload={"kind": "refine", "options": refine_mod.chips_payload()})


# --- generation helpers --------------------------------------------------
def _tokens(text: str) -> list[Token]:
    words = text.split(" ")
    return [Token(text=w if i == len(words) - 1 else w + " ") for i, w in enumerate(words)]


async def _stream_prose(ctx: Context, *, prompt, payload: dict, fallback: str):
    """Stream one prose run, falling back to templated copy on any model failure.

    The fallback is emitted only if NOTHING was streamed. Once a partial sentence has
    reached the client, replacing it would mean retracting text the user has already
    read - so a truncated lead-in stays truncated and the cards still arrive.
    """
    req = prompt.build(ctx.models["generator"], payload)
    produced = False
    try:
        async for item in ctx.gateway.stream(req, ctx.ledger):
            # The terminal ModelResult carries the usage, not more prose; the gateway
            # has already recorded it by the time it arrives here.
            if isinstance(item, ModelDelta) and item.text:
                produced = True
                yield Token(text=item.text)
    except BudgetExceeded as exc:
        ctx.state.degraded_reason = "turn_budget"
        METRICS.incr("ask.budget_degrade")
        log(logger, logging.WARNING, "generator_budget", error=str(exc))
    except GatewayError as exc:
        ctx.state.degraded_reason = "generator_unavailable"
        METRICS.incr("ask.generator_degrade")
        log(logger, logging.WARNING, "generator_unavailable", error=repr(exc))

    if not produced:
        for token in _tokens(fallback):
            yield token


async def _complete_prose(ctx: Context, req, fallback: str) -> str:
    """One prose call, degrading to templated copy on any failure."""
    try:
        result = await ctx.gateway.complete(req, ctx.ledger)
    except BudgetExceeded:
        ctx.state.degraded_reason = "turn_budget"
        return fallback
    except GatewayError:
        ctx.state.degraded_reason = "generator_unavailable"
        return fallback
    text = (result.text or "").strip()
    if not text:
        # A degraded result (a refusal, or a cap hit before any text) carries no prose.
        ctx.state.degraded_reason = ctx.state.degraded_reason or "generator_empty"
        return fallback
    return text


async def _fan_out(ctx: Context, requests: list, fallbacks: list[str]) -> list[str]:
    """Run the prose calls concurrently, bounded by the turn ceiling as a group.

    The whole fan-out is priced against the ledger BEFORE it launches. Letting each
    call run its own pre-check would let N concurrent calls each see the same headroom
    and spend it N times - a ceiling that holds only when requests are serialised is
    not a ceiling.
    """
    if not requests:
        return []
    try:
        ctx.ledger.check(
            about_to_spend=sum(ctx.gateway.estimate_cost(req) for req in requests)
        )
    except BudgetExceeded as exc:
        ctx.state.degraded_reason = "turn_budget"
        METRICS.incr("ask.budget_degrade")
        log(logger, logging.WARNING, "card_reasons_over_budget", error=str(exc))
        return list(fallbacks)

    return list(
        await asyncio.gather(
            *(
                _complete_prose(ctx, req, fallback)
                for req, fallback in zip(requests, fallbacks, strict=True)
            )
        )
    )


def _profile_labels(profile: dict) -> list[str]:
    labels = []
    for axis_id in ("sweetness", "body", "oak"):
        value = profile.get(axis_id)
        axis = AXES_BY_ID.get(axis_id)
        if not value or axis is None:
            continue
        for level in axis.levels:
            if level.value == value:
                labels.append(level.label.lower())
                break
    return labels


def _lead_in_fallback(count: int, profile: dict) -> str:
    labels = _profile_labels(profile)
    tail = f": {', '.join(labels)}" if labels else ""
    return f"Here are {count} grape varieties worth looking for{tail}."


__all__ = ["run"]
