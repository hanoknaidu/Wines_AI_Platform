"""Drives an engine for one turn: guard -> persist -> publish.

This is the only place that writes assistant messages, and the only place that decides
what reaches a client. Everything an engine emits passes through here, so the grounding
guard, the cost accounting and the seq allocation apply to every engine equally.
"""

from __future__ import annotations

import asyncio
import logging
import time

from ..config import Settings
from ..dataset.loader import DatasetIndex
from ..db.repositories import logs as logs_repo
from ..db.repositories import messages as messages_repo
from ..db.repositories import profile as profile_repo
from ..observability import METRICS, log, turn_id_var
from ..pricing import cost_usd
from ..turns import grounding
from ..turns.cost import TurnCache, turn_cache_key
from ..turns.engine import (
    CardEvent,
    Checkpoint,
    ChipsEvent,
    CitationEvent,
    ProfilePatch,
    RetrievalTrace,
    Token,
    TurnRequest,
    Usage,
)
from ..turns.registry import InFlight, TurnRegistry
from .bus import Event, SseEventBus
from .seq import SeqAllocator

logger = logging.getLogger("wines_ai.runner")

# Tokens are coalesced: live subscribers get one `token` event per chunk, the database
# gets ONE text part per message when the turn ends. Persisting a row per token would
# turn a 300-word answer into 400 writes for no readable benefit.


class TurnRunner:
    def __init__(
        self,
        *,
        engine_factory,
        db,
        bus: SseEventBus,
        registry: TurnRegistry,
        index: DatasetIndex,
        settings: Settings,
        cache: TurnCache,
        cost_guard,
        seq: SeqAllocator,
    ) -> None:
        self.engine_factory = engine_factory
        self.db = db
        self.bus = bus
        self.registry = registry
        self.index = index
        self.settings = settings
        self.cache = cache
        self.cost_guard = cost_guard
        self.seq = seq

    async def run(self, *, entry: InFlight, req: TurnRequest, user_id: str) -> None:
        turn_id_var.set(req.turn_id)
        started = time.monotonic()
        cid = req.conversation_id

        decision = self.cost_guard.decide(
            requested_engine=self.settings.engine, user_id=user_id
        )
        engine = self.engine_factory(decision.engine)

        cache_key = turn_cache_key(
            engine=decision.engine,
            # Which provider produced the answer is part of what the answer IS.
            variant=getattr(engine, "cache_variant", ""),
            dataset_version=self.index.version,
            utterance=req.utterance,
            chip_id=req.selected_chip_id,
            profile=req.profile,
        )

        status = "ok"
        error_code: str | None = None
        usage = Usage(intent="unknown", intent_confidence=0.0, model=decision.engine)
        text_chunks: list[str] = []
        # The seq of the FIRST token of the current run. The coalesced text part is
        # persisted under this seq, so on replay the text lands before the card or
        # chips that followed it live. Stamping it at the end of the turn instead
        # would invert that order for every resuming client.
        run_anchor: int | None = None
        committed: list[dict] = []
        cited_row_ids: list[str] = []
        cache_hit = False

        # Replayed from the cache, or produced by the engine - either way one async
        # iterator, consumed as it arrives.
        #
        # This used to drain the engine into a list before publishing anything, which
        # was invisible under lane 2 (a pure engine finishes in under 10 ms) and would
        # have broken lane 3 outright: a Sonnet generator streaming 300 words would
        # have been buffered for the whole turn and then published at once, so the
        # client's cursor, Stop button and `?after=` resume would all have had nothing
        # to work with until the answer was already complete. Streaming is the product
        # here, not a detail of the transport.
        recorded: list = []

        async def source():
            nonlocal cache_hit
            cached = self.cache.get(cache_key)
            if cached is not None:
                cache_hit = True
                METRICS.incr("turn.cache_hit")
                for event in cached:
                    yield event
                return
            METRICS.incr("turn.cache_miss")
            async for event in engine.run(req):
                recorded.append(event)
                yield event

        try:
            assistant_seq = None
            assistant_id = None

            async for event in source():
                if entry.cancel.is_set():
                    status = "cancelled"
                    break

                if isinstance(event, Usage):
                    usage = event
                    continue

                if isinstance(event, ProfilePatch):
                    async with self.db.begin() as conn:
                        await profile_repo.merge(
                            conn, cid=cid, values=event.values, confidence=event.confidence
                        )
                    continue

                if isinstance(event, RetrievalTrace):
                    async with self.db.begin() as conn:
                        await logs_repo.write_retrieval(
                            conn,
                            turn_id=req.turn_id,
                            stage=event.stage,
                            query_text=event.query_text,
                            candidate_row_ids=event.candidate_row_ids,
                            ranks=event.ranks,
                            scores=event.scores,
                        )
                    continue

                if isinstance(event, Checkpoint):
                    async with self.db.begin() as conn:
                        await logs_repo.write_checkpoint(
                            conn, turn_id=req.turn_id, node=event.node, state=event.state
                        )
                    continue

                # Everything below reaches the client, so it needs a message to hang off.
                if assistant_id is None:
                    assistant_seq = await self._reserve(cid)
                    async with self.db.begin() as conn:
                        row = await messages_repo.add_message(
                            conn, cid=cid, role="assistant", seq=assistant_seq, turn_id=req.turn_id
                        )
                    assistant_id = row["id"]

                if isinstance(event, Token):
                    seq = await self._reserve(cid)
                    if run_anchor is None:
                        run_anchor = seq
                    text_chunks.append(event.text)
                    data = {
                        "turn_id": req.turn_id,
                        "text": event.text,
                        # A client that drops mid-run reconnects with
                        # ?after=anchor_seq-1 to get the whole run replayed as one
                        # text frame, rather than resuming into a half-written
                        # sentence it cannot complete.
                        "anchor_seq": run_anchor,
                    }
                    entry.buffer.append((seq, "token", data))
                    self.bus.publish(cid, Event(seq=seq, name="token", data=data))
                    continue

                # Any non-token event closes the current text run.
                if text_chunks and run_anchor is not None:
                    async with self.db.begin() as conn:
                        await messages_repo.add_part(
                            conn,
                            message_id=assistant_id,
                            cid=cid,
                            kind="text",
                            seq=run_anchor,
                            text="".join(text_chunks),
                        )
                    committed.append({"seq": run_anchor, "kind": "text"})
                    text_chunks = []
                    run_anchor = None

                if isinstance(event, CardEvent):
                    guarded = grounding.check_card(self.index, event, turn_id=req.turn_id)
                    if guarded is None:
                        # The card lost its source: replace it with templated copy rather
                        # than let an unsourced claim through.
                        fallback = grounding.fallback_text(self.index, event.row_id)
                        if fallback:
                            text_chunks.append(fallback)
                        continue
                    payload = {"turn_id": req.turn_id, **guarded.payload}
                    seq = await self._reserve(cid)
                    async with self.db.begin() as conn:
                        await messages_repo.add_part(
                            conn,
                            message_id=assistant_id,
                            cid=cid,
                            kind="card",
                            seq=seq,
                            card_json=guarded.payload,
                            row_id=guarded.row_id,
                        )
                    cited_row_ids.append(guarded.row_id)
                    committed.append({"seq": seq, "kind": "card"})
                    self.bus.publish(cid, Event(seq=seq, name="card", data=payload))
                    continue

                if isinstance(event, ChipsEvent):
                    seq = await self._reserve(cid)
                    async with self.db.begin() as conn:
                        await messages_repo.add_part(
                            conn,
                            message_id=assistant_id,
                            cid=cid,
                            kind="chips",
                            seq=seq,
                            chips_json=event.payload,
                        )
                    committed.append({"seq": seq, "kind": "chips"})
                    chips_data = {"turn_id": req.turn_id, **event.payload}
                    self.bus.publish(cid, Event(seq=seq, name="chips", data=chips_data))
                    continue

                if isinstance(event, CitationEvent):
                    citation = {
                        "row_ids": event.row_ids,
                        "dataset_version": self.index.version,
                    }
                    seq = await self._reserve(cid)
                    async with self.db.begin() as conn:
                        await messages_repo.add_part(
                            conn,
                            message_id=assistant_id,
                            cid=cid,
                            kind="citation",
                            seq=seq,
                            citation_json=citation,
                        )
                    committed.append({"seq": seq, "kind": "citation"})
                    self.bus.publish(
                        cid,
                        Event(seq=seq, name="citation", data={"turn_id": req.turn_id, **citation}),
                    )
                    continue

            # Only a successful turn is cached, and only after it finished: caching
            # mid-stream would store a turn that was later cancelled or errored, and
            # replaying a failure for free is worse than paying for a retry.
            if not cache_hit and status == "ok":
                self.cache.put(cache_key, recorded)

            # Flush any trailing text run under its own anchor seq.
            if assistant_id is not None and text_chunks and run_anchor is not None:
                async with self.db.begin() as conn:
                    await messages_repo.add_part(
                        conn,
                        message_id=assistant_id,
                        cid=cid,
                        kind="text",
                        seq=run_anchor,
                        text="".join(text_chunks),
                    )

        except asyncio.CancelledError:
            status = "cancelled"
            raise
        except Exception as exc:  # noqa: BLE001
            status = "error"
            error_code = "engine_error"
            log(logger, logging.ERROR, "turn_failed", error=repr(exc))
            logger.exception("turn_failed")
            seq = await self._reserve(cid)
            self.bus.publish(
                cid,
                Event(
                    seq=seq,
                    name="error",
                    data={
                        "turn_id": req.turn_id,
                        "code": "engine_error",
                        "title": "The recommendation could not be completed",
                        "detail": "Something went wrong while answering. Try again.",
                    },
                ),
            )
        finally:
            latency_ms = int((time.monotonic() - started) * 1000)
            # A cached turn costs nothing. An engine that spent across several
            # models reports its own total (see Usage.cost_usd); anything else is
            # priced from the one model it named.
            if cache_hit:
                cost = 0.0
            elif usage.cost_usd is not None:
                cost = usage.cost_usd
            else:
                cost = cost_usd(
                    usage.model, usage.tokens_in, usage.tokens_out, usage.cache_read_tokens
                )
            self.cost_guard.record(user_id, cost)
            METRICS.record_usage(usage.tokens_in, usage.tokens_out, cost)
            METRICS.observe("turn.latency_ms", latency_ms)

            # One transaction_log row per turn, without exception. A cost of $0.00 is
            # still a row - the accounting path has to be exercised before the real
            # models make it expensive to discover it was wrong.
            async with self.db.begin() as conn:
                await logs_repo.write_turn(
                    conn,
                    cid=cid,
                    user_id=user_id,
                    turn_id=req.turn_id,
                    intent=usage.intent,
                    intent_confidence=usage.intent_confidence,
                    model=usage.model,
                    engine=decision.engine,
                    tokens_in=usage.tokens_in,
                    tokens_out=usage.tokens_out,
                    cost_usd=cost,
                    latency_ms=latency_ms,
                    status=status,
                    error_code=error_code,
                    cache_hit=cache_hit,
                )
                await logs_repo.write_intent_eval(
                    conn,
                    utterance=req.utterance,
                    predicted=usage.intent,
                    confidence=usage.intent_confidence,
                )

            seq = await self._reserve(cid)
            self.bus.publish(
                cid,
                Event(
                    seq=seq,
                    name="usage",
                    data={
                        "turn_id": req.turn_id,
                        "intent": usage.intent,
                        "intent_confidence": usage.intent_confidence,
                        "model": usage.model,
                        "engine": decision.engine,
                        "tokens_in": usage.tokens_in,
                        "tokens_out": usage.tokens_out,
                        "cost_usd": cost,
                        "cache_hit": cache_hit,
                        "degraded": decision.degraded,
                        # Why the answer degraded, when it did: a turn that fell back
                        # to templated copy because the budget ran out or the provider
                        # was down must be visible, not merely cheap. A stable code,
                        # not the log line's prose - the client maps it to copy.
                        "degraded_reason": (
                            "cost_ceiling" if decision.degraded else usage.degraded_reason
                        ),
                        "latency_ms": latency_ms,
                    },
                ),
            )
            done_seq = await self._reserve(cid)
            self.bus.publish(
                cid,
                Event(
                    seq=done_seq,
                    name="done",
                    data={
                        "turn_id": req.turn_id,
                        "status": status,
                        "row_ids": cited_row_ids,
                        "seq": done_seq,
                    },
                ),
            )
            self.registry.finish(req.turn_id)
            turn_id_var.set(None)

    async def _reserve(self, cid: str) -> int:
        """Reserve the next event seq for this conversation (see services/seq.py)."""
        return await self.seq.next(cid)
