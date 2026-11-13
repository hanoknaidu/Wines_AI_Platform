"""The Phase-1 engine: BRD v1.1's serving path.

    answers -> target profile -> hard filter on style -> weighted distance across axes
            -> diversify by grape variety -> top 3-5 rows -> copy drawn from the row

Not a mock. It is the product the BRD originally specified, which is why Phase 1 ships
a working recommender with no key, no network and sub-10ms turns. Lane 3 later replaces
how the profile is built, not whether the app works.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from ..config import Settings
from ..dataset.loader import DatasetIndex
from ..taste import copy as copytext
from ..taste import diversify as div
from ..taste import interview, ranking, refine
from .engine import (
    CardEvent,
    Checkpoint,
    ChipsEvent,
    CitationEvent,
    ProfilePatch,
    RetrievalTrace,
    Token,
    TurnEvent,
    TurnRequest,
    Usage,
)
from .intent import classify


class DeterministicEngine:
    name = "deterministic"

    def __init__(self, index: DatasetIndex, settings: Settings) -> None:
        self.index = index
        self.settings = settings

    async def run(self, req: TurnRequest) -> AsyncIterator[TurnEvent]:
        profile = dict(req.profile)
        intent, confidence, topic = classify(
            req.utterance,
            profile,
            selected_chip_id=req.selected_chip_id,
            has_results=bool(req.previous_row_ids),
        )
        yield Checkpoint(node="intent_router", state={"intent": intent, "confidence": confidence})

        # The routed intent is not always the EFFECTIVE one: an interview turn that
        # fills the last slot goes on to recommend, and a refine that cannot move an
        # axis falls back. Usage is emitted at the end carrying what actually
        # happened, because transaction_log.intent feeds the intent eval set and a
        # turn mislabelled 'interview' while serving five cards corrupts it.
        ctx = {"intent": intent}

        if intent == "out_of_scope":
            async for event in self._out_of_scope(topic or "generic"):
                yield event
        elif intent == "refine":
            async for event in self._refine(req, profile, ctx):
                yield event
        else:
            # Both 'interview' and 'recommend' go through the interview path. It
            # harvests whatever axes the utterance states and only then decides
            # whether it has enough to recommend. Dispatching 'recommend' straight
            # to _recommend would hand it the STORED profile and lose the slots the
            # router just read out of the utterance - which, with an empty stored
            # profile, lands in the empty state instead of answering.
            async for event in self._interview(req, profile, ctx):
                yield event

        yield Usage(
            intent=ctx["intent"], intent_confidence=confidence, model="deterministic"
        )

    # --- 4 - out-of-scope / safety --------------------------------------
    async def _out_of_scope(self, topic: str) -> AsyncIterator[TurnEvent]:
        """Templated reply, no retrieval. No price, no availability, no health claims
        in either direction, no purchase path."""
        yield Checkpoint(node="safety", state={"topic": topic})
        async for token in self._stream(copytext.out_of_scope(topic)):
            yield token

    # --- 1 - interview ---------------------------------------------------
    async def _interview(
        self, req: TurnRequest, profile: dict, ctx: dict
    ) -> AsyncIterator[TurnEvent]:
        patch: dict[str, str] = {}
        confidence: dict[str, dict] = {}

        if req.selected_chip_id and (read := interview.read_chip(req.selected_chip_id)):
            axis_id, value = read
            patch[axis_id] = value
            confidence[axis_id] = {"confidence": 1.0, "provenance": "asked"}
        else:
            # Harvest every axis the utterance states, not only the one just asked:
            # re-asking what the user already said is the fastest way to look stupid.
            for axis_id, value in interview.read_any(req.utterance).items():
                if profile.get(axis_id) is None:
                    patch[axis_id] = value
                    confidence[axis_id] = {"confidence": 0.8, "provenance": "inferred"}

        if patch:
            profile.update(patch)
            yield ProfilePatch(values=patch, confidence=confidence)

        asked_count = sum(
            1 for axis in ("style", "sweetness", "body", "oak") if profile.get(axis) is not None
        )

        if interview.is_sufficient(profile):
            yield Checkpoint(node="interview_complete", state={"profile": profile})
            async for event in self._recommend(req, profile, ctx=ctx):
                yield event
            return

        question = interview.next_question(
            profile, asked_count, self.settings.max_interview_questions
        )
        if question is None:
            # Cap reached without enough slots: recommend on what we have rather than
            # asking a fourth question the product promised not to ask.
            async for event in self._recommend(req, profile, ctx=ctx):
                yield event
            return

        ctx["intent"] = "interview"
        yield Checkpoint(node="interview_ask", state={"axis": question.axis})
        async for token in self._stream(question.prompt):
            yield token
        yield ChipsEvent(
            payload={
                "kind": "interview",
                "axis": question.axis,
                "prompt": question.prompt,
                "options": question.options,
            }
        )

    # --- 3 - refine ------------------------------------------------------
    async def _refine(
        self, req: TurnRequest, profile: dict, ctx: dict
    ) -> AsyncIterator[TurnEvent]:
        chip = refine.detect(req.utterance, req.selected_chip_id)
        if chip is None:
            async for event in self._recommend(req, profile, ctx=ctx):
                yield event
            return

        patch, blocked = refine.apply(profile, chip)
        if blocked:
            async for token in self._stream(
                f"I cannot go further that way - {blocked}. "
                "Try one of the other adjustments below."
            ):
                yield token
            yield ChipsEvent(payload={"kind": "refine", "options": refine.chips_payload()})
            return

        profile.update(patch)
        yield ProfilePatch(
            values=patch,
            confidence={
                axis: {"confidence": 1.0, "provenance": "refined"} for axis in patch
            },
        )
        yield Checkpoint(node="refine", state={"chip": chip["id"], "patch": patch})

        ctx["intent"] = "refine"
        # Trailing space: the next text run is concatenated by the client's reducer.
        async for token in self._stream(f"Adjusting for {chip['label']}. "):
            yield token
        # Anchored to what the user actually saw: the previous rows plus a widened set.
        #
        # `ctx=None` keeps the label at `refine`: the turn serves cards, but the action
        # that defines it is the one-axis delta against what was already on screen, and
        # `transaction_log.intent` feeds the intent eval set. Lane 3 labels the same
        # turn the same way, which is what makes the two engines comparable.
        async for event in self._recommend(
            req, profile, anchor=req.previous_row_ids, ctx=None
        ):
            yield event

    # --- 2 - recommend ---------------------------------------------------
    async def _recommend(
        self,
        req: TurnRequest,
        profile: dict,
        anchor: list[str] | None = None,
        ctx: dict | None = None,
    ) -> AsyncIterator[TurnEvent]:
        if ctx is not None:
            ctx["intent"] = "recommend"
        candidates = ranking.hard_filter(self.index.rows, profile)
        yield RetrievalTrace(
            stage="style_filter",
            query_text=req.utterance,
            candidate_row_ids=[row.row_id for row in candidates],
        )

        if anchor:
            # Widened candidate set that keeps the previously shown rows in play, so the
            # correction is relative to what was on screen rather than a fresh search.
            anchored = [self.index.resolve(rid) for rid in anchor]
            seen = {row.row_id for row in candidates}
            candidates = candidates + [
                row for row in anchored if row is not None and row.row_id not in seen
            ]

        if not candidates:
            yield Checkpoint(node="empty_state", state={"profile": profile})
            async for token in self._stream(copytext.empty_state(profile)):
                yield token
            yield ChipsEvent(payload={"kind": "refine", "options": refine.chips_payload()})
            return

        scored = ranking.rank(candidates, profile)

        # FR-13: an honest empty state, never a silently widened filter. The style
        # filter alone is not enough - without this floor, asking for a dessert wine
        # that is "not sweet at all" would return five properly-sweet dessert wines,
        # which is the exact failure the requirement names.
        in_range = ranking.within_sweetness_tolerance(
            scored, profile, self.settings.sweetness_tolerance_levels
        )
        in_range = [s for s in in_range if s.distance <= self.settings.max_match_distance]
        if not in_range:
            best = scored[0].distance if scored else None
            yield Checkpoint(
                node="empty_state",
                state={"profile": profile, "best_distance": best, "reason": "below_match_floor"},
            )
            async for token in self._stream(copytext.empty_state(profile)):
                yield token
            yield ChipsEvent(payload={"kind": "refine", "options": refine.chips_payload()})
            return
        scored = in_range

        yield RetrievalTrace(
            stage="rank",
            query_text=req.utterance,
            candidate_row_ids=[s.row.row_id for s in scored[:30]],
            ranks=list(range(1, min(30, len(scored)) + 1)),
            scores=[s.score for s in scored[:30]],
        )

        chosen = div.diversify(scored, want=self.settings.results_max)
        if len(chosen) < self.settings.results_min:
            chosen = scored[: self.settings.results_min]

        yield RetrievalTrace(
            stage="diversify",
            query_text=req.utterance,
            candidate_row_ids=[s.row.row_id for s in chosen],
            ranks=list(range(1, len(chosen) + 1)),
            scores=[s.score for s in chosen],
        )
        yield Checkpoint(
            node="recommend",
            state={
                "row_ids": [s.row.row_id for s in chosen],
                "variety_count": div.variety_count(chosen),
            },
        )

        lead = self._lead_in(len(chosen), profile)
        async for token in self._stream(lead):
            yield token

        threshold = self.settings.confidence_threshold
        for item in chosen:
            row = item.row
            yield CardEvent(
                row_id=row.row_id,
                payload={
                    "row_id": row.row_id,
                    "variety": row.variety,
                    "style": row.style,
                    "axes": copytext.axis_readings(row, threshold),
                    "description": copytext.tastes_like(row),
                    "why_it_matches": copytext.why_it_matches(
                        row, profile, item.per_axis, threshold
                    ),
                    "typical_regions": list(row.typical_regions),
                    "example_producers": list(row.example_producers),
                    "review_status": row.review_status,
                    "dataset_version": row.dataset_version,
                },
            )

        yield CitationEvent(row_ids=[item.row.row_id for item in chosen])
        yield ChipsEvent(payload={"kind": "refine", "options": refine.chips_payload()})

    # --- helpers ---------------------------------------------------------
    def _lead_in(self, count: int, profile: dict) -> str:
        from ..taste.axes import AXES_BY_ID

        bits = []
        for axis_id in ("sweetness", "body", "oak"):
            value = profile.get(axis_id)
            if value is None:
                continue
            axis = AXES_BY_ID[axis_id]
            for level in axis.levels:
                if level.value == value:
                    bits.append(level.label.lower())
                    break
        # A colon and a plain comma list, for two reasons. The sentence already ends in
        # "for", so prefixing the tail with another one read "worth looking for for not
        # sweet at all". And these labels are phrases that themselves contain "and"
        # ("rich and bold"), so `_join`'s "and" made the boundary between two of them
        # unreadable: "rich and bold and rounded and buttery". `_join` is right for the
        # noun lists it serves elsewhere and is left alone.
        tail = f": {', '.join(bits)}" if bits else ""
        return f"Here are {count} grape varieties worth looking for{tail}."

    async def _stream(self, text: str) -> AsyncIterator[Token]:
        """Word-by-word on an uneven cadence.

        The frontend's cursor, stop button and no-layout-shift guarantees have to be
        tested against something that behaves like a stream, and the `?after=` resume
        path cannot be tested at all against an instant response.
        """
        delay = self.settings.stream_token_delay_ms / 1000.0
        words = text.split(" ")
        for idx, word in enumerate(words):
            yield Token(text=word if idx == len(words) - 1 else word + " ")
            if delay:
                # Uneven: every fourth token pauses a little longer.
                await asyncio.sleep(delay * (2.0 if idx % 4 == 3 else 1.0))
