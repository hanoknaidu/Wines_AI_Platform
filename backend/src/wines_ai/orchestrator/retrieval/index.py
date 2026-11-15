"""Band 3's retrieval indexes, built once at startup from the frozen artifact.

Three indexes, one per retriever arm, plus the document text each row contributes to
the text sides. They are built from the SAME `DatasetIndex` the deterministic engine
reads, which is what makes the "a mismatch between the artifact and any index fails
the build" rule hold trivially: there is no second artifact to drift from.

The axis table (stage E3) is not a separate structure - `DatasetIndex.by_style` plus
the row fields already are it, and a composite dict keyed on (style, sweetness, body)
is built here so the hard pre-filter stays a single lookup rather than a scan.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ...dataset.loader import DatasetIndex
from ...dataset.schema import WineRow
from ...observability import log
from .bm25 import Bm25Index
from .embed import Embedder, HashingEmbedder, cosine

if TYPE_CHECKING:
    from .vector_store import CrossEncoderReranker, QdrantDense

logger = logging.getLogger("wines_ai.retrieval")


def document_text(row: WineRow) -> str:
    """What the text retrievers see for one row.

    Variety and style are repeated into the text on purpose: on the sparse side an
    exact varietal match is the single strongest signal a user can give, and BM25 only
    sees terms that are present in the document.
    """
    return " ".join(
        [
            row.variety,
            row.variety,
            row.style,
            row.description,
            " ".join(row.typical_regions),
            " ".join(row.example_producers),
            row.sweetness,
            row.body,
            row.oak,
            row.tannin,
            row.acidity,
            row.fruit_savoury,
        ]
    )


@dataclass
class RetrievalIndexes:
    dataset_version: str
    embedder: Embedder
    vectors: dict[str, list[float]] = field(default_factory=dict)
    bm25: Bm25Index = field(default_factory=Bm25Index)
    by_axes: dict[tuple[str, str, str], list[str]] = field(default_factory=dict)
    build_ms: int = 0
    # Set when the `retrieval` extra is installed: the dense arm then runs on Qdrant
    # and stage G on a real cross-encoder. None means the local fallbacks.
    vector_store: QdrantDense | None = None
    cross_encoder: CrossEncoderReranker | None = None
    documents: dict[str, str] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return len(self.vectors)

    def describe(self) -> dict:
        return {
            "dataset_version": self.dataset_version,
            "rows": self.size,
            "embedder": (
                f"qdrant:{self.vector_store.model_name}"
                if self.vector_store
                else self.embedder.kind
            ),
            "dim": self.vector_store.dim if self.vector_store else self.embedder.dim,
            "reranker": (
                f"cross-encoder:{self.cross_encoder.model_name}"
                if self.cross_encoder
                else "feature-scorer"
            ),
            "bm25_terms": len(self.bm25.doc_freqs),
            "axis_buckets": len(self.by_axes),
            "build_ms": self.build_ms,
        }

    def add_row(self, row: WineRow) -> None:
        """Index one ingested row on every arm: embed, BM25, axis bucket, vector store."""
        if row.row_id in self.documents:
            return
        text = document_text(row)
        self.documents[row.row_id] = text
        self.vectors[row.row_id] = self.embedder.encode(text)
        self.bm25.add(row.row_id, text)
        self.bm25.finalize()
        self.by_axes.setdefault((row.style, row.sweetness, row.body), []).append(row.row_id)
        if self.vector_store is not None:
            self.vector_store.upsert({row.row_id: text})

    # --- E1 dense --------------------------------------------------------
    def dense(
        self, query: str, *, k: int, allowed: set[str] | None = None
    ) -> list[tuple[str, float]]:
        if self.vector_store is not None:
            return self.vector_store.search(query, k=k, allowed=allowed)
        q = self.embedder.encode(query)
        scored = [(row_id, round(cosine(q, vec), 6)) for row_id, vec in self.vectors.items()]
        scored = [pair for pair in scored if pair[1] > 0.0]
        if allowed is not None:
            scored = [pair for pair in scored if pair[0] in allowed]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored[:k]

    # --- E2 sparse -------------------------------------------------------
    def sparse(self, query: str, *, k: int) -> list[tuple[str, float]]:
        return self.bm25.search(query, k=k)

    # --- E3 structured ---------------------------------------------------
    def axis_bucket(self, style: str, sweetness: str, body: str) -> list[str]:
        return list(self.by_axes.get((style, sweetness, body), ()))


def build(index: DatasetIndex, *, dim: int, settings=None) -> RetrievalIndexes:
    started = time.monotonic()
    embedder = HashingEmbedder(dim=dim)
    out = RetrievalIndexes(dataset_version=index.version, embedder=embedder)

    for row in index.rows:
        text = document_text(row)
        out.documents[row.row_id] = text
        out.vectors[row.row_id] = embedder.encode(text)
        out.bm25.add(row.row_id, text)
        out.by_axes.setdefault((row.style, row.sweetness, row.body), []).append(row.row_id)
    out.bm25.finalize()
    if settings is not None:
        from .vector_store import load_backends

        out.vector_store, out.cross_encoder = load_backends(settings)
        if out.vector_store is not None:
            out.vector_store.build(out.documents)
    out.build_ms = int((time.monotonic() - started) * 1000)

    log(logger, logging.INFO, "retrieval_indexes_built", **out.describe())
    return out
