"""GraphState: everything one turn knows, and the context the nodes share.

One mutable object per turn, snapshotted per node into `graph_checkpoint`. That table
is what gives resume-after-crash, turn replay, and an audit trail of which node
decided what - and it is already wired, because the deterministic engine has been
writing stage snapshots into it since lane 2.

`GraphState.snapshot()` is deliberately small and JSON-safe. A checkpoint that carried
the packed context would make the table the biggest thing in the database and would
duplicate the dataset into it on every turn; the row ids are enough to reconstruct
what the node saw, because the artifact is frozen and version-pinned.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..config import Settings
from ..dataset.loader import DatasetIndex
from ..turns.engine import TurnRequest
from .gateway import ModelGateway, TurnLedger
from .retrieval import RetrievalIndexes

if TYPE_CHECKING:
    from .pipeline.types import Candidate, PackedContext


@dataclass
class GraphState:
    turn_id: str
    conversation_id: str
    utterance: str
    selected_chip_id: str | None
    profile: dict
    history: list[dict]
    previous_row_ids: list[str]
    dataset_version: str

    # --- filled by the nodes --------------------------------------------
    intent: str = "interview"
    intent_confidence: float = 0.0
    intent_source: str = ""  # model | keyword | chip
    out_of_scope_topic: str | None = None
    # The intent the turn ACTUALLY served. An interview turn that fills the last slot
    # goes on to recommend, and transaction_log.intent feeds the intent eval set - a
    # turn labelled 'interview' while serving five cards corrupts it.
    effective_intent: str = ""
    slots: dict[str, str] = field(default_factory=dict)
    query: str = ""
    rewrite_source: str = ""
    sub_queries: list[str] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    chosen: list[Candidate] = field(default_factory=list)
    packed: PackedContext | None = None
    verified: bool | None = None
    unsupported_row_ids: list[str] = field(default_factory=list)
    verify_source: str = ""
    degraded_reason: str | None = None
    generator_model: str = ""
    nodes_run: list[str] = field(default_factory=list)

    def snapshot(self) -> dict:
        return {
            "intent": self.intent,
            "intent_confidence": self.intent_confidence,
            "intent_source": self.intent_source,
            "effective_intent": self.effective_intent or self.intent,
            "out_of_scope_topic": self.out_of_scope_topic,
            "slots": dict(self.slots),
            "profile": {k: v for k, v in self.profile.items() if v},
            "query": self.query,
            "rewrite_source": self.rewrite_source,
            "sub_queries": list(self.sub_queries),
            "candidate_row_ids": [c.row_id for c in self.candidates],
            "chosen_row_ids": [c.row_id for c in self.chosen],
            "packed": self.packed.trace() if self.packed else None,
            "verified": self.verified,
            "unsupported_row_ids": list(self.unsupported_row_ids),
            "verify_source": self.verify_source,
            "degraded_reason": self.degraded_reason,
            "generator_model": self.generator_model,
            "nodes_run": list(self.nodes_run),
        }


@dataclass
class Context:
    """What every node is handed. Read-only except for `state` and `ledger`."""

    req: TurnRequest
    state: GraphState
    settings: Settings
    index: DatasetIndex
    indexes: RetrievalIndexes
    gateway: ModelGateway
    ledger: TurnLedger

    @property
    def models(self) -> dict[str, str]:
        return {
            "router": self.settings.model_router,
            "rewriter": self.settings.model_rewriter,
            "verifier": self.settings.model_verifier,
            "generator": self.settings.model_generator,
            "interview": self.settings.model_interview,
            "recommend": self.settings.model_recommend,
            "recommend_complex": self.settings.model_recommend_complex,
            "refine": self.settings.model_refine,
        }


def initial_state(req: TurnRequest) -> GraphState:
    return GraphState(
        turn_id=req.turn_id,
        conversation_id=req.conversation_id,
        utterance=req.utterance,
        selected_chip_id=req.selected_chip_id,
        profile=dict(req.profile),
        history=list(req.history),
        previous_row_ids=list(req.previous_row_ids),
        dataset_version=req.dataset_version,
    )
