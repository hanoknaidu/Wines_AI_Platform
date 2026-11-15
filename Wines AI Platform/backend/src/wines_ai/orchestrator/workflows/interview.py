"""1 - INTERVIEW. Slots unfilled -> ask, never guess. Free-text taste -> suggest, then ask.

Two paths, chosen by how the user answered:

**Chip path (unchanged).** The user tapped one of the option chips. The answer is
exact, the router already wrote it into the profile, and the next question is a total
function of the filled slots - no model call, no retrieval. Hard cap: 3 questions.

**Free-text taste path.** The user typed a taste of their own instead of (or as well
as) tapping a chip - "something smoky and peppery", "I like the jammy ones". That is
information the chips could not capture, and answering it with the next canned question
would ignore it. So the turn runs the RAG pipeline over it:

    rewrite (Haiku, rewrite@2 guardrails)
      -> hybrid retrieval: dense (Qdrant) top-K + BM25 top-K + axis floor, fused
      -> rerank (cross-encoder blended with axis agreement) -> top `interview_top_n`
      -> pack (token budget) -> Sonnet writes grounded suggestions citing row ids
      -> structural citation check
    then, if the profile is still not sufficient, the next interview question + chips.

The suggestion is prose with citations, not cards. Cards are the recommend workflow's
output and imply the interview is over; here it is not, and three more chips follow.
"""

from __future__ import annotations

import logging
import re

from ...observability import METRICS, log
from ...taste import interview as interview_mod
from ...turns.engine import Checkpoint, ChipsEvent, CitationEvent, RetrievalTrace, Token
from .. import pipeline
from ..prompts import INTERVIEW_SUGGEST
from ..retrieval.bm25 import tokenize
from ..state import Context
from . import ask

logger = logging.getLogger("wines_ai.workflows.interview")

# Words that carry no taste. A message made only of these ("hi", "ok sure", "not sure")
# is not a taste and must not trigger retrieval.
_NON_TASTE = set(
    tokenize(
        "a an the and or but i im i'm me my we you it its is are was be to of for in on "
        "with like likes liked love want wants would could should something some one "
        "wine wines please maybe just really very quite bit kind sort thing things "
        "hi hello hey ok okay sure yes no not dont don't know idea any anything "
        "what which how good nice great prefer usually also too more less"
    )
)
_ROW_REF = re.compile(r"\[([A-Za-z0-9_.:-]+)\]")


def is_free_text_taste(ctx: Context) -> bool:
    """True when this turn's typed words describe a taste the chips did not.

    A chip press is never one. Otherwise any of: the router extracted a slot from the
    text, the text uses a consumer taste word stage C knows, or it shares a
    non-trivial term with the corpus vocabulary.
    """
    state = ctx.state
    if state.intent_source == "chip" or not state.utterance.strip():
        return False
    if state.slots or pipeline.harvest_consumer_words(state.utterance):
        return True
    vocab = ctx.indexes.bm25.doc_freqs
    terms = [t for t in tokenize(state.utterance) if t not in _NON_TASTE and len(t) > 2]
    return any(t in vocab for t in terms)


async def run(ctx: Context):
    state = ctx.state
    state.effective_intent = "interview"

    # Slots extracted by the router are already merged into the profile by the
    # graph's `slot_merge` node. Doing it there is what lets the graph decide between
    # this workflow and `recommend` on the POST-merge profile.
    asked_count = sum(
        1 for axis in ("style", "sweetness", "body", "oak") if state.profile.get(axis) is not None
    )

    if interview_mod.is_sufficient(state.profile):
        yield Checkpoint(node="interview_complete", state={"profile": state.profile})
        async for event in ask.run(ctx):
            yield event
        return

    if is_free_text_taste(ctx):
        METRICS.incr("interview.free_text_taste")
        async for event in _suggest(ctx):
            yield event

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
    for token in ask._tokens(question.prompt):
        yield token
    yield ChipsEvent(
        payload={
            "kind": "interview",
            "axis": question.axis,
            "prompt": question.prompt,
            "options": question.options,
        }
    )


async def _suggest(ctx: Context):
    """The free-text path: rewrite -> hybrid retrieve -> rerank -> pack -> Sonnet."""
    state = ctx.state
    settings = ctx.settings

    # --- pre-retrieval: guarded rewrite ----------------------------------
    state.query, rewritten, state.rewrite_source = await pipeline.rewrite(
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
        state={"query": state.query, "rewritten": rewritten, "source": state.rewrite_source},
    )
    yield RetrievalTrace(stage="rewrite", query_text=state.query, candidate_row_ids=[])

    # --- retrieval: dense + BM25 (+ axis floor), fused --------------------
    working_profile = {**state.profile}
    for axis, value in pipeline.harvest_consumer_words(state.utterance).items():
        working_profile.setdefault(axis, value)
    plan_ = pipeline.plan(query=state.query, profile=working_profile, settings=settings)
    yield Checkpoint(node="plan.0", state=plan_.trace())
    arms = await pipeline.retrieve(
        index=ctx.index,
        indexes=ctx.indexes,
        plan_=plan_,
        # Embed the user's taste words with the profile around them: their phrasing is
        # the signal here, not a profile that is by definition still incomplete.
        hyde_text=pipeline.hyde(working_profile, state.query),
    )
    for arm, hits in arms.items():
        yield RetrievalTrace(
            stage=f"retrieve.{arm}",
            query_text=state.query,
            candidate_row_ids=[row_id for row_id, _ in hits],
            ranks=list(range(1, len(hits) + 1)),
            scores=[score for _, score in hits],
        )
    fused = pipeline.fuse(
        index=ctx.index, arms=arms, rrf_k=settings.rrf_k, top_n=2 * settings.retriever_k
    )
    state.candidates = fused
    if not fused:
        yield Checkpoint(node="interview_suggest_empty", state={"query": state.query})
        return

    # --- rerank -> top n ---------------------------------------------------
    reranked = pipeline.rerank(
        fused,
        query=state.query,
        profile=working_profile,
        top_n=settings.interview_top_n,
        cross_encoder=ctx.indexes.cross_encoder,
        ce_weight=settings.cross_encoder_weight,
        min_relevance=settings.rerank_min_relevance,
    )
    state.nodes_run.append("rerank")
    yield RetrievalTrace(
        stage="rerank",
        query_text=state.query,
        candidate_row_ids=[c.row_id for c in reranked],
        ranks=list(range(1, len(reranked) + 1)),
        scores=[c.rerank for c in reranked],
    )

    # --- augmentation -------------------------------------------------------
    packed = pipeline.pack(
        reranked, budget=settings.context_token_budget, threshold=settings.confidence_threshold
    )
    state.packed = packed
    state.chosen = [c for c in reranked if c.row_id in set(packed.row_ids)]
    state.nodes_run.append("pack")
    yield Checkpoint(node="pack", state=packed.trace())
    if not state.chosen:
        return

    # --- generation (Sonnet) ------------------------------------------------
    model = ctx.models["interview"]
    state.generator_model = model
    threshold = settings.confidence_threshold
    fallback = _fallback(state.chosen)
    text_parts: list[str] = []
    async for token in ask._stream_prose(
        ctx,
        model=model,
        prompt=INTERVIEW_SUGGEST,
        payload={
            "kind": "interview_suggest",
            "utterance": state.utterance,
            "query": state.query,
            "profile": {k: v for k, v in sorted(state.profile.items()) if v},
            "rows": [pipeline.render_row(c.row, threshold=threshold) for c in state.chosen],
            "fallback": fallback,
        },
        fallback=fallback,
    ):
        text_parts.append(token.text)
        yield token

    # --- citation check -----------------------------------------------------
    # Structural, like the offline verifier: every [row_id] the prose cites must be a
    # row it was given. Streamed text cannot be retracted, so an uncited or foreign
    # reference is recorded and only valid ids are emitted as citations.
    text = "".join(text_parts)
    cited = list(dict.fromkeys(_ROW_REF.findall(text)))
    packed_ids = set(packed.row_ids)
    foreign = [rid for rid in cited if rid not in packed_ids]
    valid = [rid for rid in cited if rid in packed_ids]
    state.verified = not foreign
    state.unsupported_row_ids = foreign
    state.verify_source = "structural"
    if foreign:
        METRICS.incr("interview.foreign_citation")
        log(logger, logging.WARNING, "interview_foreign_citation", row_ids=foreign)
    yield Checkpoint(
        node="interview_suggest",
        state={"model": model, "cited": valid, "foreign": foreign},
    )
    if valid:
        yield CitationEvent(row_ids=valid)
    # The question that follows is a new text run; keep the two apart.
    yield Token(text="\n\n")


def _fallback(chosen) -> str:
    names = [f"{c.row.variety} [{c.row_id}]" for c in chosen[:3]]
    if not names:
        return ""
    return "From what you describe, these are worth a look: " + ", ".join(names) + "."


__all__ = ["is_free_text_taste", "run"]
