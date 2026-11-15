"""3 - REFINE. Parse the delta, move one axis, re-rank what the user saw.

Mutates the profile on that axis ONLY, and re-runs retrieval over the documents already
retrieved for this conversation PLUS a widened candidate set - so the correction is
anchored to what the user actually saw rather than being a fresh search that happens to
be adjacent. Never re-interviews (FR-8).

The widening is `plan(widen=True)`, which relaxes the sweetness band by one level. That
is the one place a refine turn is allowed to be more permissive than a first answer,
and the reason is that the user has just told us the previous answer was wrong on that
axis: the next-best rows are by definition the ones the first query's band excluded.
"""

from __future__ import annotations

import logging

from ...observability import METRICS, log
from ...taste import refine as refine_mod
from ...taste.axes import REFINE_BY_ID
from ...turns.engine import Checkpoint, ChipsEvent, ProfilePatch, Token
from ..gateway import GatewayError
from ..prompts import REFINE_DELTA
from ..state import Context
from . import ask

logger = logging.getLogger("wines_ai.workflows.refine")


async def read_delta(ctx: Context) -> tuple[dict | None, str]:
    """Which adjustment the user means. -> (chip spec or None, source).

    The lexical reader goes first and wins when it matches: a chip press or "too
    sweet" has one right answer and needs no model. Only free text it cannot read
    ("those all felt like syrup, honestly") goes to Opus, with the wines the user saw,
    because the correction only means something relative to them.
    """
    state = ctx.state
    chip = refine_mod.detect(state.utterance, state.selected_chip_id)
    if chip is not None:
        return chip, "lexical"
    seen = [
        {"row_id": r.row_id, "variety": r.variety, "sweetness": r.sweetness,
         "body": r.body, "oak": r.oak, "tannin": r.tannin}
        for rid in state.previous_row_ids[:5]
        if (r := ctx.index.resolve(rid)) is not None
    ]
    req = REFINE_DELTA.build(
        ctx.models["refine"],
        {
            "utterance": state.utterance,
            "history": state.history[-4:],
            "profile": {k: v for k, v in sorted(state.profile.items()) if v},
            "wines_shown": seen,
        },
    )
    try:
        result = await ctx.gateway.complete(req, ctx.ledger)
    except GatewayError as exc:
        log(logger, logging.WARNING, "refine_delta_failed", error=repr(exc))
        return None, "fallback"
    data = result.structured or {}
    adjustment = data.get("adjustment")
    METRICS.incr("refine.delta_model")
    return REFINE_BY_ID.get(str(adjustment)) if adjustment else None, "model"


async def run(ctx: Context):
    state = ctx.state
    state.effective_intent = "refine"

    chip, source = await read_delta(ctx)
    yield Checkpoint(
        node="refine_delta",
        state={"chip": chip["id"] if chip else None, "source": source},
    )
    model = ctx.models["refine"]
    if chip is None:
        # Classified as a refine but nothing to move: answer it as an ask rather than
        # tell the user their correction was unparseable.
        async for event in ask.run(
            ctx, anchor_row_ids=state.previous_row_ids, label="refine", generator_model=model
        ):
            yield event
        return

    patch, blocked = refine_mod.apply(state.profile, chip)
    if blocked:
        yield Checkpoint(node="refine_blocked", state={"chip": chip["id"], "reason": blocked})
        text = (
            f"I cannot go further that way - {blocked}. "
            "Try one of the other adjustments below."
        )
        words = text.split(" ")
        for idx, word in enumerate(words):
            yield Token(text=word if idx == len(words) - 1 else word + " ")
        yield ChipsEvent(payload={"kind": "refine", "options": refine_mod.chips_payload()})
        return

    state.profile.update(patch)
    yield ProfilePatch(
        values=patch,
        confidence={axis: {"confidence": 1.0, "provenance": "refined"} for axis in patch},
    )
    yield Checkpoint(node="refine", state={"chip": chip["id"], "patch": patch})

    # Trailing space: the next text run is concatenated by the client's reducer.
    text = f"Adjusting for {chip['label']}. "
    for word in text.split(" "):
        if word:
            yield Token(text=word + " ")

    async for event in ask.run(
        ctx, anchor_row_ids=state.previous_row_ids, label="refine", generator_model=model
    ):
        yield event


__all__ = ["run"]
