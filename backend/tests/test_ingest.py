"""Taste ingestion: known vs unknown routing, storage on every arm, persistence."""

from __future__ import annotations

import pytest

from wines_ai.ingest import (
    IngestRejected,
    IngestStore,
    SearchFindings,
    TasteIngestor,
)


class FakeSearcher:
    name = "fake"

    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, query: str) -> SearchFindings:
        self.queries.append(query)
        return SearchFindings(
            summary="A rare orange-wine style.",
            regions=["Kakheti"],
            producers=["Example Cellar"],
            sources=[{"url": "https://example.org/amber", "title": "Amber wine"}],
        )


@pytest.fixture
def ingestor(settings, tmp_path):
    from wines_ai.dataset.loader import load
    from wines_ai.orchestrator.gateway import build_gateway
    from wines_ai.orchestrator.retrieval import build

    index = load(settings.resolved_dataset_path)
    indexes = build(index, dim=settings.embedding_dim, settings=settings)
    searcher = FakeSearcher()
    ing = TasteIngestor(
        index=index,
        indexes=indexes,
        gateway=build_gateway(settings),
        searcher=searcher,
        store=IngestStore(tmp_path / "store.jsonl"),
        settings=settings,
    )
    ing.searcher_fake = searcher
    return ing


async def test_known_taste_takes_matched_row(ingestor):
    note = "A big Malbec, plummy and dark with soft velvety tannins"
    result = await ingestor.ingest(note)

    assert result.path == "known"
    assert result.matched_row is not None and result.matched_row.variety == "Malbec"
    row = result.row
    assert row.variety == "Malbec" and row.review_status == "unreviewed"
    assert row.example_producers == []  # never copied onto an unsigned row
    assert ingestor.searcher_fake.queries == []  # known path never searches
    # Embedded and stored on every arm.
    assert row.row_id in ingestor.indexes.vectors
    assert ingestor.index.resolve(row.row_id) is row
    assert any(rid == row.row_id for rid, _ in ingestor.indexes.sparse("velvety plummy", k=50))


async def test_unknown_taste_profiles_and_searches(ingestor):
    note = "an amber skin-contact white, dry, tannic and earthy like bruised apple"
    result = await ingestor.ingest(note)

    assert result.path == "unknown"
    assert ingestor.searcher_fake.queries, "unknown path must run the web search"
    row = result.row
    assert row.style == "white" and row.sweetness == "dry"
    assert row.typical_regions == ["Kakheti"]
    assert row.review_status == "unreviewed"
    assert result.sources[0]["url"] == "https://example.org/amber"
    assert row.row_id in ingestor.indexes.documents


async def test_duplicate_note_is_idempotent(ingestor):
    note = "A big Malbec, plummy and dark"
    first = await ingestor.ingest(note)
    again = await ingestor.ingest("  a big   malbec, plummy and dark ")
    assert first.created and not again.created
    assert again.path == "duplicate" and again.row.row_id == first.row.row_id


async def test_rows_survive_restart_via_store(ingestor, settings):
    from wines_ai.dataset.loader import load
    from wines_ai.orchestrator.retrieval import build

    result = await ingestor.ingest("A big Malbec, plummy and dark")
    index = load(settings.resolved_dataset_path)
    fresh = TasteIngestor(
        index=index,
        indexes=build(index, dim=settings.embedding_dim, settings=settings),
        gateway=None, searcher=None, store=ingestor.store, settings=settings,
    )
    assert fresh.replay() == 1
    assert fresh.index.resolve(result.row.row_id) is not None


async def test_empty_note_rejected(ingestor):
    with pytest.raises(IngestRejected):
        await ingestor.ingest("   ")


async def test_tastes_endpoint(aged):
    r = await aged.post("/api/v1/tastes", json={"note": "Crisp Sauvignon Blanc, zesty and grassy"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["path"] == "known"
    assert body["row"]["review_status"] == "unreviewed"
    assert body["matched_row"]["variety"] == "Sauvignon Blanc"


async def test_tastes_endpoint_needs_age_gate(client):
    r = await client.post("/api/v1/tastes", json={"note": "Malbec"})
    assert r.status_code == 403


async def test_known_and_unknown_on_qdrant_and_cross_encoder(settings, tmp_path, monkeypatch):
    """The real stack: fastembed vectors in Qdrant, bge cross-encoder deciding KNOWN."""
    pytest.importorskip("qdrant_client")
    from wines_ai.dataset.loader import load
    from wines_ai.orchestrator.retrieval import build

    monkeypatch.setattr(settings, "retrieval_backend", "qdrant")
    index = load(settings.resolved_dataset_path)
    try:
        indexes = build(index, dim=settings.embedding_dim, settings=settings)
    except Exception as exc:  # model download unavailable offline
        pytest.skip(f"retrieval models unavailable: {exc!r}")
    ing = TasteIngestor(
        index=index, indexes=indexes, gateway=None, searcher=FakeSearcher(),
        store=IngestStore(tmp_path / "q.jsonl"), settings=settings,
    )

    known = await ing.ingest("A big Malbec, plummy and dark with soft velvety tannins")
    assert known.path == "known" and known.scorer == "cross-encoder"
    assert known.matched_row.variety == "Malbec"

    unknown = await ing.ingest("tastes like smoked tea leaves and iodine, nothing like fruit")
    assert unknown.path == "unknown"
    # Both are now retrievable from the vector store itself.
    hits = {rid for rid, _ in indexes.vector_store.search("smoked tea iodine", k=5)}
    assert unknown.row.row_id in hits
