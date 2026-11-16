"""5 - EXPLAIN. A question about wine, answered directly - not an interview step.

    match catalogue rows by name -> generator writes a short description from them
      -> producers line (verbatim from the rows) -> one card per matched row

"Describe Cabernet Sauvignon" used to fall through to the interview and get "Red,
white or rosé?" back. This workflow answers it: a paragraph grounded in the matched
rows, then the rows' `example_producers` as brands to look for, then the rows as cards
so the user can see the full profile. Producer names never come from the model - the
prompt forbids them and they are appended from the rows, and the cards go through the
same grounding guard as every other card.

The taste profile is untouched: asking about a grape is not saying you like it.
"""

from __future__ import annotations

from ...observability import METRICS
from ...taste import copy as copytext
from ...taste import explain as explain_mod
from ...turns.engine import CardEvent, Checkpoint, CitationEvent
from .. import pipeline
from ..prompts import EXPLAIN
from ..state import Context
from . import ask


async def run(ctx: Context):
    state = ctx.state
    state.effective_intent = "explain"
    threshold = ctx.settings.confidence_threshold

    rows = explain_mod.find_varieties(state.utterance, ctx.index.rows)
    METRICS.incr("explain.matched" if rows else "explain.general")
    yield Checkpoint(node="explain", state={"row_ids": [r.row_id for r in rows]})

    model = ctx.models["recommend"]
    state.generator_model = model
    fallback = explain_mod.describe(rows)
    async for token in ask._stream_prose(
        ctx,
        model=model,
        prompt=EXPLAIN,
        payload={
            "kind": "explain",
            "utterance": state.utterance,
            "rows": [pipeline.render_row(r, threshold=threshold) for r in rows],
            "fallback": fallback,
        },
        fallback=fallback,
    ):
        yield token

    if not rows:
        return

    line = explain_mod.producers_line(rows)
    if line:
        for token in ask._tokens("\n\n" + line):
            yield token
    # A nudge back to the main path: the interview starts from the next message.
    for token in ask._tokens(f"\n\n{explain_mod.NUDGE}"):
        yield token

    for row in rows:
        yield CardEvent(
            row_id=row.row_id,
            payload={
                "row_id": row.row_id,
                "variety": row.variety,
                "style": row.style,
                "axes": copytext.axis_readings(row, threshold),
                "description": copytext.tastes_like(row),
                "why_it_matches": f"The {row.variety} you asked about.",
                "typical_regions": list(row.typical_regions),
                "example_producers": list(row.example_producers),
                "review_status": row.review_status,
                "dataset_version": row.dataset_version,
            },
        )
    yield CitationEvent(row_ids=[r.row_id for r in rows])


__all__ = ["run"]
