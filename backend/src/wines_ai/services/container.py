"""Everything built once at lifespan and handed to routes through one dependency."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..config import Settings
from ..dataset.loader import DatasetError, DatasetIndex, load
from ..db.database import Database
from ..errors import engine_unavailable
from ..ingest import IngestStore, TasteIngestor, build_web_searcher
from ..observability import log
from ..orchestrator.gateway import ModelGateway, build_gateway, provider_unavailable_reason
from ..orchestrator.retrieval import RetrievalIndexes
from ..orchestrator.retrieval import build as build_retrieval_indexes
from ..turns.cost import CostGuard, TurnCache
from ..turns.deterministic import DeterministicEngine
from ..turns.orchestrated import OrchestratedEngine
from ..turns.registry import TurnRegistry
from .bus import SseEventBus
from .runner import TurnRunner
from .seq import SeqAllocator

logger = logging.getLogger("wines_ai.services")


@dataclass
class Services:
    settings: Settings
    db: Database
    bus: SseEventBus
    registry: TurnRegistry
    seq: SeqAllocator
    cache: TurnCache
    cost_guard: CostGuard
    index: DatasetIndex | None
    dataset_error: str | None
    runner: TurnRunner | None
    # Lane 3's two singletons. Built at lifespan because both are per-process state:
    # the indexes are O(corpus) to build and the gateway owns the circuit breaker,
    # which is meaningless if a fresh one is constructed per turn.
    indexes: RetrievalIndexes | None = None
    gateway: ModelGateway | None = None
    # Set when the requested model provider could not be built. Advisory unless
    # `require_llm_provider` is on, in which case it fails readiness.
    provider_error: str | None = None
    # POST /tastes. None when ingestion is disabled or the dataset failed to load.
    ingestor: TasteIngestor | None = None

    def engine_for(self, name: str):
        if self.index is None:
            raise RuntimeError("dataset not loaded")
        if name == "orchestrated" and self.provider_error and self.settings.require_llm_provider:
            # Only reachable if something drove a turn past a red /readyz.
            raise engine_unavailable(self.settings.llm_provider)
        if name == "orchestrated":
            return OrchestratedEngine(
                self.index, self.settings, indexes=self.indexes, gateway=self.gateway
            )
        return DeterministicEngine(self.index, self.settings)

    @property
    def ready(self) -> bool:
        if self.provider_error and self.settings.require_llm_provider:
            return False
        return self.index is not None

    def describe_engine(self) -> dict:
        """What /readyz reports about the serving path.

        The provider matters here: `offline` is a complete, free, keyless run of the
        same pipeline, and someone looking at a deployment needs to be able to tell
        which one they are getting without inferring it from the bill.
        """
        out: dict = {"engine": self.settings.engine}
        if self.settings.engine != "orchestrated":
            return out
        out["provider"] = self.gateway.provider_name if self.gateway else "unbuilt"
        out["provider_requested"] = self.settings.llm_provider
        if self.provider_error:
            out["provider_error"] = self.provider_error
        out["models"] = {
            "router": self.settings.model_router,
            "rewriter": self.settings.model_rewriter,
            "verifier": self.settings.model_verifier,
            "generator": self.settings.model_generator,
        }
        if self.indexes is not None:
            out["retrieval"] = self.indexes.describe()
        return out


def build(settings: Settings, db: Database) -> Services:
    index: DatasetIndex | None = None
    dataset_error: str | None = None
    try:
        index = load(settings.resolved_dataset_path)
    except DatasetError as exc:
        # Not fatal to the process: healthz stays green, readyz goes red, and the
        # failure is a named state rather than a crash loop.
        dataset_error = str(exc)
        log(logger, logging.ERROR, "dataset_load_failed", error=dataset_error)

    bus = SseEventBus()
    registry = TurnRegistry(expiry_seconds=settings.turn_expiry_seconds)
    seq = SeqAllocator(db)
    cache = TurnCache(
        ttl_seconds=settings.turn_cache_ttl_seconds,
        max_entries=settings.turn_cache_max_entries,
        enabled=settings.turn_cache_enabled,
    )
    cost_guard = CostGuard(
        per_turn_usd=settings.cost_ceiling_per_turn_usd,
        per_session_usd=settings.cost_ceiling_per_session_usd,
        global_daily_usd=settings.cost_ceiling_global_daily_usd,
    )

    services = Services(
        settings=settings,
        db=db,
        bus=bus,
        registry=registry,
        seq=seq,
        cache=cache,
        cost_guard=cost_guard,
        index=index,
        dataset_error=dataset_error,
        runner=None,
    )
    if index is not None:
        # Built for either engine. The indexes cost a few milliseconds over a corpus
        # this size and make `WA_ENGINE=orchestrated` a restart rather than a rebuild;
        # the gateway with the default `offline` provider opens no socket and reads no
        # key, so neither of these breaks the empty-environment boot.
        services.indexes = build_retrieval_indexes(
            index, dim=settings.embedding_dim, settings=settings
        )
        services.provider_error = provider_unavailable_reason(settings)
        if services.provider_error:
            log(
                logger,
                logging.ERROR if settings.require_llm_provider else logging.WARNING,
                "provider_unavailable",
                requested=settings.llm_provider,
                reason=services.provider_error,
                strict=settings.require_llm_provider,
            )
        services.gateway = build_gateway(settings)
        if settings.ingest_enabled:
            services.ingestor = TasteIngestor(
                index=index,
                indexes=services.indexes,
                gateway=services.gateway,
                searcher=build_web_searcher(settings),
                store=IngestStore(settings.resolved_ingest_store_path),
                settings=settings,
            )
            services.ingestor.replay()
        services.runner = TurnRunner(
            engine_factory=services.engine_for,
            db=db,
            bus=bus,
            registry=registry,
            index=index,
            settings=settings,
            cache=cache,
            cost_guard=cost_guard,
            seq=seq,
        )
    return services
