"""Cost controls that bound spend structurally rather than by hoping.

Phase 1 spends nothing, so none of this fires yet. It is built now because every one
of these levers is cheap to add before lane 3 and awkward to retrofit after:

1. TURN CACHE - a completed turn is replayed for free when the same question arrives
   against the same profile and the same dataset version. The deterministic engine is
   pure, so this is always safe; under lane 3 it is the difference between paying for
   a repeated turn and not.
2. COST GUARD - per-turn, per-session and global daily ceilings. Exceeding one
   DEGRADES to the free deterministic engine; it never returns an error, because a
   demo that stops working is worse than a demo that is cheap.
3. The other three levers live elsewhere and are listed here so the set is in one
   place: idempotency (a retried send cannot pay twice), one-in-flight-turn-per-
   conversation, and cancellation on client disconnect (an abandoned turn stops
   costing immediately).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field

from ..observability import log

logger = logging.getLogger("wines_ai.cost")


def turn_cache_key(
    *,
    engine: str,
    dataset_version: str,
    utterance: str,
    chip_id: str | None,
    profile: dict,
    variant: str = "",
) -> str:
    """Content-addressed: same engine, same data, same question, same state -> same answer.

    `variant` separates answers an engine name does not distinguish. Under lane 3 the
    same `orchestrated` engine answers through either the offline provider or a real
    model, and the two produce different prose; without this, switching the provider
    would serve yesterday's templated copy from cache and look like the model had
    silently stopped working.
    """
    material = {
        "engine": engine,
        "variant": variant,
        "dataset_version": dataset_version,
        # Normalised so trivial whitespace and case differences still hit.
        "utterance": " ".join(utterance.lower().split()),
        "chip": chip_id,
        "profile": {k: v for k, v in sorted(profile.items()) if k != "confidence_json"},
    }
    blob = json.dumps(material, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


@dataclass
class _Entry:
    events: list
    expires_at: float


class TurnCache:
    """Small in-process TTL+LRU map of completed turns.

    Only successful turns are stored, and only the replayable event stream - never a
    cancelled or errored turn, which would cache a failure.
    """

    def __init__(self, *, ttl_seconds: int, max_entries: int, enabled: bool = True) -> None:
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self.enabled = enabled
        self._data: dict[str, _Entry] = {}
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> list | None:
        if not self.enabled:
            return None
        entry = self._data.get(key)
        if entry is None:
            self.misses += 1
            return None
        if entry.expires_at < time.monotonic():
            del self._data[key]
            self.misses += 1
            return None
        self.hits += 1
        # Refresh recency.
        self._data[key] = self._data.pop(key)
        return list(entry.events)

    def put(self, key: str, events: list) -> None:
        if not self.enabled:
            return
        if len(self._data) >= self.max_entries:
            self._data.pop(next(iter(self._data)), None)
        self._data[key] = _Entry(events=list(events), expires_at=time.monotonic() + self.ttl)

    def stats(self) -> dict:
        return {"entries": len(self._data), "hits": self.hits, "misses": self.misses}


@dataclass
class CostDecision:
    engine: str
    degraded: bool
    reason: str | None = None


@dataclass
class CostGuard:
    """Chooses the engine for a turn given what has already been spent."""

    per_turn_usd: float
    per_session_usd: float
    global_daily_usd: float
    free_engine: str = "deterministic"
    _session_spend: dict[str, float] = field(default_factory=dict)
    _global_today: float = 0.0

    def record(self, user_id: str, cost: float) -> None:
        if cost <= 0:
            return
        self._session_spend[user_id] = round(self._session_spend.get(user_id, 0.0) + cost, 8)
        self._global_today = round(self._global_today + cost, 8)

    def prime(self, *, global_today: float) -> None:
        self._global_today = global_today

    def session_spend(self, user_id: str) -> float:
        return self._session_spend.get(user_id, 0.0)

    def decide(self, *, requested_engine: str, user_id: str) -> CostDecision:
        if requested_engine == self.free_engine:
            return CostDecision(engine=self.free_engine, degraded=False)

        if self._global_today >= self.global_daily_usd:
            reason = (
                f"global daily ceiling reached (${self._global_today:.4f} >= "
                f"${self.global_daily_usd:.2f})"
            )
        elif self.session_spend(user_id) >= self.per_session_usd:
            reason = (
                f"session ceiling reached (${self.session_spend(user_id):.4f} >= "
                f"${self.per_session_usd:.2f})"
            )
        else:
            return CostDecision(engine=requested_engine, degraded=False)

        log(logger, logging.WARNING, "cost_ceiling_degrade", reason=reason, user_id=user_id)
        return CostDecision(engine=self.free_engine, degraded=True, reason=reason)
