"""1 - INTERVIEW. Slots unfilled -> ask, never guess.

Picks the next most-discriminating question given what is already known (style gates
which axes even apply), phrases it as a physical sensation rather than wine jargon, and
emits option chips. Writes answers back into taste_profile. Hard cap: 3 questions.

No model call. The question selection is a total function of the filled slots, and the
phrasings are the product's own vocabulary, served over `/meta/taste-axes` so the
frontend never hardcodes a wine word. Asking a model to choose between three
pre-written questions would add a round trip, a failure mode and a source of
non-determinism to a decision that has one right answer - and the chips it emits have
to match the vocabulary endpoint exactly or the client cannot render them.

What lane 3 adds here is upstream: the router's slot extraction reads axes out of free
text that the keyword reader misses, so the interview is reached with more slots
already filled and asks fewer questions. That is the improvement - not a different
question.
"""

from __future__ import annotations

from ...taste import interview as interview_mod
from ...turns.engine import Checkpoint, ChipsEvent, Token
from ..state import Context
from . import ask


async def run(ctx: Context):
    state = ctx.state
    state.effective_intent = "interview"

    # Slots extracted by the router are already merged into the profile by the
    # graph's `slot_merge` node, which also emits the ProfilePatch. Doing it there
    # rather than here is what lets the graph decide between this workflow and `ask`
    # on the POST-merge profile: an opening turn of "a smooth dry red" answers two
    # questions, and asking one of them again is the fastest way to look stupid.
    asked_count = sum(
        1 for axis in ("style", "sweetness", "body", "oak") if state.profile.get(axis) is not None
    )

    if interview_mod.is_sufficient(state.profile):
        yield Checkpoint(node="interview_complete", state={"profile": state.profile})
        async for event in ask.run(ctx):
            yield event
        return

    question = interview_mod.next_question(
        state.profile, asked_count, ctx.settings.max_interview_questions
    )
    if question is None:
        # Cap reached without enough slots: recommend on what we have rather than ask
        # a fourth question the product promised not to ask.
        yield Checkpoint(node="interview_capped", state={"asked_count": asked_count})
        async for event in ask.run(ctx):
            yield event
        return

    yield Checkpoint(node="interview_ask", state={"axis": question.axis})
    words = question.prompt.split(" ")
    for idx, word in enumerate(words):
        yield Token(text=word if idx == len(words) - 1 else word + " ")
    yield ChipsEvent(
        payload={
            "kind": "interview",
            "axis": question.axis,
            "prompt": question.prompt,
            "options": question.options,
        }
    )


__all__ = ["run"]
