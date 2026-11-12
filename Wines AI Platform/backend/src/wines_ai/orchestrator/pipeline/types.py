"""What flows between the pipeline stages.

One candidate type carried the whole way from retrieval to the packed prompt, so a
row's provenance - which arm found it, at what rank, what each stage scored it - is
still attached when the card is written. That is what makes the retrieval log an
explanation rather than a list of ids.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...dataset.schema import WineRow


@dataclass
class Candidate:
    row: WineRow
    # Per-arm rank (1-based) and score, by arm name: dense | sparse | structured.
    ranks: dict[str, int] = field(default_factory=dict)
    arm_scores: dict[str, float] = field(default_factory=dict)
    fused: float = 0.0
    rerank: float = 0.0
    # Which sub-query (stage B) produced it; 0 when the turn was not decomposed.
    group: int = 0

    @property
    def row_id(self) -> str:
        return self.row.row_id

    @property
    def arms(self) -> list[str]:
        return sorted(self.ranks)

    def trace(self) -> dict:
        return {
            "row_id": self.row_id,
            "arms": self.arms,
            "ranks": dict(self.ranks),
            "fused": round(self.fused, 6),
            "rerank": round(self.rerank, 6),
            "group": self.group,
        }


@dataclass
class QueryPlan:
    """Stage D's output: what each arm is asked, and what is filtered before it runs."""

    query: str
    # The hard pre-filter, applied INSIDE each arm rather than after it, so top-k is k
    # relevant rows and not k rows followed by a filter that empties the list.
    style: str | None = None
    sweetness_band: tuple[str, ...] = ()
    soft_weights: dict[str, str] = field(default_factory=dict)
    k_dense: int = 50
    k_sparse: int = 50
    k_structured: int = 50
    group: int = 0

    def trace(self) -> dict:
        return {
            "query": self.query,
            "style": self.style,
            "sweetness_band": list(self.sweetness_band),
            "soft_weights": dict(self.soft_weights),
            "k": {
                "dense": self.k_dense,
                "sparse": self.k_sparse,
                "structured": self.k_structured,
            },
            "group": self.group,
        }


@dataclass
class PackedRow:
    row_id: str
    text: str
    tokens: int


@dataclass
class PackedContext:
    """Stage I's output. This, and nothing else, is what the generator sees."""

    rows: list[PackedRow] = field(default_factory=list)
    tokens: int = 0
    budget: int = 0
    dropped_row_ids: list[str] = field(default_factory=list)
    collapsed_row_ids: list[str] = field(default_factory=list)

    @property
    def row_ids(self) -> list[str]:
        return [r.row_id for r in self.rows]

    def as_text(self) -> str:
        return "\n\n".join(r.text for r in self.rows)

    def trace(self) -> dict:
        return {
            "row_ids": self.row_ids,
            "tokens": self.tokens,
            "budget": self.budget,
            "dropped": self.dropped_row_ids,
            "collapsed": self.collapsed_row_ids,
        }
