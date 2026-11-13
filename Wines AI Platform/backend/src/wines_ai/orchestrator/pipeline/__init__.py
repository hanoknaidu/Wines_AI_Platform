"""Band 2: the end-to-end RAG pipeline, stages A to K.

    A rewrite -> B decompose -> C expand -> D plan -> E1/E2/E3 retrieve
      -> F fuse (RRF) -> G rerank -> H diversify (MMR) -> I pack
      -> J generate (in the workflow, which owns the event stream) -> K verify
"""

from __future__ import annotations

from .pack import pack, render_row
from .query import decompose, harvest_consumer_words, hyde, rewrite
from .rerank import mmr, rerank, variety_count
from .retrieve import fuse, plan, retrieve
from .types import Candidate, PackedContext, PackedRow, QueryPlan
from .verify import ndcg_at_k, recall_at_k, verify

__all__ = [
    "Candidate",
    "PackedContext",
    "PackedRow",
    "QueryPlan",
    "decompose",
    "fuse",
    "harvest_consumer_words",
    "hyde",
    "mmr",
    "ndcg_at_k",
    "pack",
    "plan",
    "recall_at_k",
    "render_row",
    "rerank",
    "retrieve",
    "rewrite",
    "variety_count",
    "verify",
]
