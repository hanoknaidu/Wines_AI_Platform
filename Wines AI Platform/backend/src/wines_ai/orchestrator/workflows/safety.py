"""4 - OUT-OF-SCOPE / SAFETY. Templated reply, no retrieval, no model call.

No price, no availability, no health claims in either direction, no purchase path, no
marketing to minors. The copy is written once, per topic, in `taste/copy.py`.

**A prompt-injection attempt never reaches the retriever**, and this is the node that
makes that true: the router matches the safety topics lexically and lands here, before
stage A runs, so an utterance asking for new instructions is never rewritten into a
query, never embedded, and never packed into a prompt. The rest of the lane's defence
is passive - retrieved text is framed as data in the preamble, and the generator cannot
reach the index - but this is the active part, and it is a lexical match on purpose: a
probabilistic classifier cannot be the only thing standing between a user and a health
claim.

Generating this copy with a model would mean asking a model to decline to answer, which
is strictly worse than not asking it: the one case where the model's judgement is least
wanted is the case where the answer must be a refusal.
"""

from __future__ import annotations

from ...observability import METRICS
from ...taste import copy as copytext
from ...turns.engine import Checkpoint, Token
from ..state import Context


async def run(ctx: Context):
    state = ctx.state
    state.effective_intent = "out_of_scope"
    topic = state.out_of_scope_topic or "generic"
    METRICS.incr(f"safety.{topic}")

    yield Checkpoint(node="safety", state={"topic": topic})
    text = copytext.out_of_scope(topic)
    words = text.split(" ")
    for idx, word in enumerate(words):
        yield Token(text=word if idx == len(words) - 1 else word + " ")


__all__ = ["run"]
