"""The lane-2 / lane-3 boundary.

Everything above this interface - routes, SSE, seq allocation, persistence,
idempotency, cancellation, logging, cost - is written once and does not change when
the implementation does. Lane 3 implements the same protocol and nothing else moves.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

Intent = Literal["interview", "recommend", "refine", "out_of_scope"]


@dataclass
class TurnRequest:
    """Exactly what the diagram's turn context builder assembles."""

    turn_id: str
    conversation_id: str
    utterance: str
    selected_chip_id: str | None
    profile: dict
    history: list[dict] = field(default_factory=list)
    previous_row_ids: list[str] = field(default_factory=list)
    asked_count: int = 0
    dataset_version: str = ""


# --- events --------------------------------------------------------------


@dataclass
class Token:
    text: str


@dataclass
class CardEvent:
    row_id: str
    payload: dict


@dataclass
class ChipsEvent:
    payload: dict


@dataclass
class CitationEvent:
    row_ids: list[str]


@dataclass
class ProfilePatch:
    """Not an SSE frame: tells the runner to persist a taste_profile change."""

    values: dict
    confidence: dict = field(default_factory=dict)


@dataclass
class RetrievalTrace:
    """Not an SSE frame: one retrieval_log row."""

    stage: str
    query_text: str | None
    candidate_row_ids: list[str]
    ranks: list[int] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)


@dataclass
class Checkpoint:
    """Not an SSE frame: one graph_checkpoint row."""

    node: str
    state: dict


@dataclass
class Usage:
    intent: str
    intent_confidence: float
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    # Set by an engine that spent across SEVERAL models in one turn, which is the
    # normal case under lane 3: the router, rewriter and verifier run on Haiku and
    # only the generator runs on Sonnet. `model` names the one that wrote the prose,
    # so pricing the turn off it alone would under-report every turn. When this is
    # None the runner prices the turn from `model` - correct for a single-model turn,
    # and the deterministic engine's $0.00.
    cost_usd: float | None = None
    # Why the turn produced a degraded answer (budget, provider down, verifier
    # repair). Reported on the usage frame so a turn that silently fell back to
    # templated copy is visible rather than merely cheaper.
    degraded_reason: str | None = None


TurnEvent = (
    Token
    | CardEvent
    | ChipsEvent
    | CitationEvent
    | ProfilePatch
    | RetrievalTrace
    | Checkpoint
    | Usage
)


@runtime_checkable
class TurnEngine(Protocol):
    name: str

    def run(self, req: TurnRequest) -> AsyncIterator[TurnEvent]: ...
