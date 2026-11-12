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

from ...taste import refine as refine_mod
from ...turns.engine import Checkpoint, ChipsEvent, ProfilePatch, Token
from ..state import Context
from . import ask


async def run(ctx: Context):
    state = ctx.state
    state.effective_intent = "refine"

    chip = refine_mod.detect(state.utterance, state.selected_chip_id)
    if chip is None:
        # Classified as a refine but nothing to move: answer it as an ask rather than
        # tell the user their correction was unparseable.
        async for event in ask.run(
            ctx, anchor_row_ids=state.previous_row_ids, label="refine"
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

    async for event in ask.run(ctx, anchor_row_ids=state.previous_row_ids, label="refine"):
        yield event


__all__ = ["run"]
