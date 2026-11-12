"""The lane-3 engine: an orchestrated turn, behind the lane-2 protocol.

Implements `TurnEngine` and nothing else. `run()` builds the graph context, drives the
graph, and translates what comes back into the same `TurnEvent` stream the
deterministic engine emits - so the routes, the SSE frames, the persistence, the
grounding guard and the frontend are all unchanged by its existence.

## The four cost contracts this engine owes, and where each is kept

The docstring this file used to carry listed them as requirements for whoever built
this. They are now assertions about the code, so here is where to check each one:

* **Model tiering** - `Context.models` reads the four model ids straight from config:
  Haiku for the router, rewriter and verifier; Sonnet only for the generator, which is
  the single call that writes prose. The router is the highest-volume call and runs on
  the cheapest tier.
* **The context budget** - enforced in `pipeline/pack.py`, which drops rows rather
  than truncating them. At 8K the packed prompt is nowhere near Haiku's 100K
  tier-break, which is the point: it stays there structurally.
* **Cache-stable prefixes** - `prompts.Prompt.build()` puts instructions first and the
  per-turn payload last, and `ModelRequest.validate_cache_order()` raises if that ever
  inverts. The ordering is a tested property, not a convention.
* **Real token counts** - `TurnLedger` accumulates the usage the provider reports, and
  `Usage` is emitted from the ledger rather than estimated. CostGuard's ceilings are
  only as good as the numbers it is given, so the numbers come from the API.

## What happens when nothing is configured

`WA_LLM_PROVIDER` defaults to `offline`, so this engine runs end to end on an empty
environment: the full pipeline, real retrieval, real traces, $0.00. It no longer
raises `engine_unavailable` - that error survives only for the case it was actually
describing, which is `anthropic` requested without the extra installed, and even that
degrades rather than failing (see `gateway/__init__.py`).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from ..config import Settings
from ..dataset.loader import DatasetIndex
from ..observability import METRICS, log
from ..orchestrator import graph, initial_state
from ..orchestrator.gateway import ModelGateway, TurnLedger, build_gateway
from ..orchestrator.retrieval import RetrievalIndexes
from ..orchestrator.retrieval import build as build_indexes
from ..orchestrator.state import Context
from .engine import TurnEvent, TurnRequest, Usage

logger = logging.getLogger("wines_ai.orchestrated")


class OrchestratedEngine:
    name = "orchestrated"

    def __init__(
        self,
        index: DatasetIndex,
        settings: Settings,
        *,
        indexes: RetrievalIndexes | None = None,
        gateway: ModelGateway | None = None,
    ) -> None:
        self.index = index
        self.settings = settings
        # Both are built once at lifespan and injected. Building the vector and BM25
        # indexes per turn would be the kind of mistake that only shows up as latency.
        self.indexes = indexes or build_indexes(index, dim=settings.embedding_dim)
        self.gateway = gateway or build_gateway(settings)

    @property
    def cache_variant(self) -> str:
        """Part of the turn cache key: a different provider is a different answer."""
        return self.gateway.provider_name

    async def run(self, req: TurnRequest) -> AsyncIterator[TurnEvent]:
        state = initial_state(req)
        ledger = TurnLedger(ceiling_usd=self.settings.cost_ceiling_per_turn_usd)
        ctx = Context(
            req=req,
            state=state,
            settings=self.settings,
            index=self.index,
            indexes=self.indexes,
            gateway=self.gateway,
            ledger=ledger,
        )

        try:
            async for event in graph.run(ctx):
                yield event
        finally:
            # In `finally` so a cancelled turn still reports what it spent before it
            # was abandoned. The runner writes one transaction_log row per turn
            # without exception, and a cancelled turn that reports $0.00 after calling
            # a model would make the accounting a polite fiction.
            yield self._usage(state, ledger)

    def _usage(self, state, ledger: TurnLedger) -> Usage:
        provider = self.gateway.provider_name
        # The model reported is the one that actually did the most expensive work, and
        # `none` when the turn made no model call at all - which is the common case for
        # a chip-answered interview turn, and worth being able to see. The COST is the
        # ledger's, which spans all four models: pricing a multi-model turn off one
        # model id would under-report every turn.
        # Only a real provider can name a real model. The offline provider records the
        # model id each prompt ASKED for, which is useful in the trace and actively
        # misleading here - a turn that called nothing out must not report Sonnet.
        if provider == "anthropic":
            model = ledger.dominant_model() or "none"
        else:
            model = provider
        if ledger.calls:
            METRICS.observe("orchestrated.calls_per_turn", len(ledger.calls))
        log(
            logger,
            logging.INFO,
            "turn_complete",
            turn_id=state.turn_id,
            intent=state.effective_intent or state.intent,
            provider=provider,
            calls=len(ledger.calls),
            tokens_in=ledger.tokens_in,
            tokens_out=ledger.tokens_out,
            cache_read=ledger.cache_read_tokens,
            cache_write=ledger.cache_write_tokens,
            cost_usd=ledger.spent_usd,
            degraded_reason=state.degraded_reason,
            nodes=state.nodes_run,
            trace=ledger.trace(),
        )
        return Usage(
            intent=state.effective_intent or state.intent,
            intent_confidence=state.intent_confidence,
            model=model,
            tokens_in=ledger.tokens_in,
            tokens_out=ledger.tokens_out,
            cache_read_tokens=ledger.cache_read_tokens,
            cache_write_tokens=ledger.cache_write_tokens,
            cost_usd=ledger.spent_usd,
            degraded_reason=state.degraded_reason,
        )
