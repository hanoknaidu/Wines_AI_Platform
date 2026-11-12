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

from ...dataset.loader import DatasetIndex
from ...dataset.schema import WineRow
from ...observability import log
from .bm25 import Bm25Index
from .embed import Embedder, HashingEmbedder, cosine

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

    @property
    def size(self) -> int:
        return len(self.vectors)

    def describe(self) -> dict:
        return {
            "dataset_version": self.dataset_version,
            "rows": self.size,
            "embedder": self.embedder.kind,
            "dim": self.embedder.dim,
            "bm25_terms": len(self.bm25.doc_freqs),
            "axis_buckets": len(self.by_axes),
            "build_ms": self.build_ms,
        }

    # --- E1 dense --------------------------------------------------------
    def dense(self, query: str, *, k: int) -> list[tuple[str, float]]:
        q = self.embedder.encode(query)
        scored = [(row_id, round(cosine(q, vec), 6)) for row_id, vec in self.vectors.items()]
        scored = [pair for pair in scored if pair[1] > 0.0]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored[:k]

    # --- E2 sparse -------------------------------------------------------
    def sparse(self, query: str, *, k: int) -> list[tuple[str, float]]:
        return self.bm25.search(query, k=k)

    # --- E3 structured ---------------------------------------------------
    def axis_bucket(self, style: str, sweetness: str, body: str) -> list[str]:
        return list(self.by_axes.get((style, sweetness, body), ()))


def build(index: DatasetIndex, *, dim: int) -> RetrievalIndexes:
    started = time.monotonic()
    embedder = HashingEmbedder(dim=dim)
    out = RetrievalIndexes(dataset_version=index.version, embedder=embedder)

    for row in index.rows:
        text = document_text(row)
        out.vectors[row.row_id] = embedder.encode(text)
        out.bm25.add(row.row_id, text)
        out.by_axes.setdefault((row.style, row.sweetness, row.body), []).append(row.row_id)
    out.bm25.finalize()
    out.build_ms = int((time.monotonic() - started) * 1000)

    log(logger, logging.INFO, "retrieval_indexes_built", **out.describe())
    return out
