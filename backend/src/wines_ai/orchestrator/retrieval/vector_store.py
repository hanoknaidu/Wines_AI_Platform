"""E1 on a real vector database, and G on a real cross-encoder.

* `QdrantDense` - embedded Qdrant (in-process, no server) holding one 768-d point per
  dataset row, embedded with fastembed's ONNX `BAAI/bge-base-en-v1.5`. One row is one
  chunk: the longest tasting note in the seed is 82 characters, so there is nothing to
  split. Filtering by the planner's row-id allow-list happens inside the query, so
  top-K is K *eligible* rows rather than K rows followed by a filter that empties them.
* `CrossEncoderReranker` - fastembed's ONNX `BAAI/bge-reranker-base` cross-encoder. Reads
  (query, document) together, which is what the hand-built feature scorer in
  `pipeline/rerank.py` approximated.

Both are optional: they need the `retrieval` extra and a one-time model download.
`load_backends()` returns None for either one it cannot build, and the caller keeps
the dependency-free implementation - the base install must still boot offline.
"""

from __future__ import annotations

import logging
import math
import uuid

from ...observability import log

logger = logging.getLogger("wines_ai.retrieval.vector_store")

COLLECTION = "wines"


def _point_id(row_id: str) -> str:
    # Qdrant ids must be ints or UUIDs; derive a stable UUID from the row id.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"wines-ai:{row_id}"))


class QdrantDense:
    kind = "qdrant"

    def __init__(self, *, model_name: str, path: str = "") -> None:
        from fastembed import TextEmbedding
        from qdrant_client import QdrantClient

        self._embedder = TextEmbedding(model_name)
        self.model_name = model_name
        self.dim = len(next(iter(self._embedder.embed(["probe"]))))
        self._client = QdrantClient(path=path) if path else QdrantClient(":memory:")

    def build(self, docs: dict[str, str]) -> None:
        from qdrant_client import models

        if self._client.collection_exists(COLLECTION):
            self._client.delete_collection(COLLECTION)
        self._client.create_collection(
            COLLECTION,
            vectors_config=models.VectorParams(size=self.dim, distance=models.Distance.COSINE),
        )
        ids = list(docs)
        vectors = list(self._embedder.embed([docs[i] for i in ids]))
        self._client.upsert(
            COLLECTION,
            points=[
                models.PointStruct(
                    id=_point_id(row_id), vector=vec.tolist(), payload={"row_id": row_id}
                )
                for row_id, vec in zip(ids, vectors, strict=True)
            ],
        )

    def upsert(self, docs: dict[str, str]) -> None:
        """Embed and add (or replace) points without rebuilding the collection."""
        from qdrant_client import models

        if not docs:
            return
        ids = list(docs)
        vectors = list(self._embedder.embed([docs[i] for i in ids]))
        self._client.upsert(
            COLLECTION,
            points=[
                models.PointStruct(
                    id=_point_id(row_id), vector=vec.tolist(), payload={"row_id": row_id}
                )
                for row_id, vec in zip(ids, vectors, strict=True)
            ],
        )

    def search(
        self, query: str, *, k: int, allowed: set[str] | None = None
    ) -> list[tuple[str, float]]:
        from qdrant_client import models

        vector = next(iter(self._embedder.embed([query]))).tolist()
        query_filter = None
        if allowed is not None:
            if not allowed:
                return []
            query_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="row_id", match=models.MatchAny(any=sorted(allowed))
                    )
                ]
            )
        hits = self._client.query_points(
            COLLECTION, query=vector, limit=k, query_filter=query_filter, with_payload=True
        ).points
        return [(str(h.payload["row_id"]), round(float(h.score), 6)) for h in hits]


class CrossEncoderReranker:
    kind = "cross-encoder"

    def __init__(self, *, model_name: str) -> None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self._model = TextCrossEncoder(model_name)
        self.model_name = model_name

    def score_logits(self, query: str, documents: list[str]) -> list[float]:
        """Raw model output: unbounded logits, comparable only within one model."""
        if not documents:
            return []
        return [float(s) for s in self._model.rerank(query, documents)]

    def score(self, query: str, documents: list[str]) -> list[float]:
        """Relevance in [0, 1]: sigmoid of the logit, as the bge-reranker card specifies.

        Unlike min-max over the candidate set, this is absolute: a candidate pool with
        nothing relevant in it scores low across the board instead of handing its best
        row a 1.0.
        """
        return [sigmoid(x) for x in self.score_logits(query, documents)]


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


def load_backends(settings) -> tuple[QdrantDense | None, CrossEncoderReranker | None]:
    """Build what the settings ask for; degrade to (None, None) rather than fail boot."""
    if settings.retrieval_backend == "local":
        return None, None
    try:
        dense = QdrantDense(model_name=settings.embedding_model, path=settings.qdrant_path)
        reranker = CrossEncoderReranker(model_name=settings.reranker_model)
        return dense, reranker
    except Exception as exc:  # ImportError, or a model download that failed
        if settings.retrieval_backend == "qdrant":
            raise
        log(logger, logging.WARNING, "retrieval_backend_fallback", error=repr(exc))
        return None, None
