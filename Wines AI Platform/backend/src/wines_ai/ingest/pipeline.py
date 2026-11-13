"""Taste ingestion: a user-uploaded tasting note becomes a searchable row.

Two paths, chosen by the reranker:

    note ─► retrieve (dense + BM25, RRF) ─► rerank ─┬─ KNOWN ──► answer = matched row
                                                    │            row inherits its axes
                                                    │
                                                    └─ UNKNOWN ─► LLM profile (axes,
                                                                 variety, query)
                                                               ─► web search (regions,
                                                                 producers, sources)
                                     both ─► build WineRow (unreviewed) ─► embed ─► upsert
                                             into the vector store + BM25 + axis table
                                             ─► append to the ingest store (JSONL)

KNOWN means the top reranked row is a confident match: calibrated cross-encoder
relevance >= `ingest_known_min_relevance` when the cross-encoder is loaded, or - on the
dependency-free path, where the feature scorer has no absolute scale - the note names
that row's variety outright.

Every ingested row is `review_status="unreviewed"`, so every surface that already
distinguishes reviewed rows flags it. Only reviewed catalogue rows can make a taste
KNOWN; an ingested row never vouches for another upload.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ..dataset.loader import DatasetIndex
from ..dataset.schema import AXIS_FIELDS, WineRow
from ..observability import log
from ..orchestrator.gateway import GatewayError, ModelGateway, TurnLedger
from ..orchestrator.pipeline.rerank import rerank
from ..orchestrator.pipeline.types import Candidate
from ..orchestrator.prompts import TASTE_PROFILE
from ..orchestrator.retrieval import RetrievalIndexes, tokenize
from ..taste.axes import STYLES
from ..taste.interview import read_any
from .web_search import NullWebSearcher, SearchFindings, WebSearcher

logger = logging.getLogger("wines_ai.ingest")

INGESTED_PREFIX = "user-"


class IngestRejected(ValueError):
    """The upload cannot become a row (empty, too long, or not a wine taste)."""


@dataclass
class IngestResult:
    path: Literal["known", "unknown", "duplicate"]
    row: WineRow
    created: bool  # False on a duplicate: this exact note was ingested before
    matched_row: WineRow | None = None
    match_score: float | None = None
    scorer: str = ""
    sources: list[dict] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)


def _normalise(note: str) -> str:
    return " ".join(note.split())


def ingested_row_id(note: str) -> str:
    digest = hashlib.sha256(_normalise(note).lower().encode()).hexdigest()[:12]
    return f"{INGESTED_PREFIX}{digest}"


class IngestStore:
    """Append-only JSONL so ingested rows survive a restart."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, row: WineRow) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(row.model_dump_json() + "\n")

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    log(logger, logging.WARNING, "ingest_store_bad_line", path=str(self.path))
        return out


class TasteIngestor:
    def __init__(
        self,
        *,
        index: DatasetIndex,
        indexes: RetrievalIndexes,
        gateway: ModelGateway | None,
        searcher: WebSearcher | None,
        store: IngestStore | None,
        settings,
    ) -> None:
        self.index = index
        self.indexes = indexes
        self.gateway = gateway
        self.searcher = searcher or NullWebSearcher()
        self.store = store
        self.settings = settings
        # Ingestion mutates process-wide indexes; serialise writers.
        self._lock = asyncio.Lock()

    # --- boot -------------------------------------------------------------
    def replay(self) -> int:
        """Re-admit every stored row onto the freshly built indexes."""
        if self.store is None:
            return 0
        count = 0
        for raw in self.store.load():
            try:
                raw["dataset_version"] = self.index.version
                row = WineRow.model_validate(raw)
            except Exception as exc:  # noqa: BLE001 - one bad line must not block boot
                log(logger, logging.WARNING, "ingest_replay_skipped", error=repr(exc))
                continue
            if self.index.resolve(row.row_id) is None:
                self.index.add_row(row)
                self.indexes.add_row(row)
                count += 1
        if count:
            log(logger, logging.INFO, "ingest_replayed", rows=count)
        return count

    # --- entry point ------------------------------------------------------
    async def ingest(self, note: str) -> IngestResult:
        note = _normalise(note)
        if not note:
            raise IngestRejected("The taste description is empty.")
        if len(note) > self.settings.ingest_max_chars:
            raise IngestRejected(
                f"The taste description is longer than {self.settings.ingest_max_chars} characters."
            )

        row_id = ingested_row_id(note)
        existing = self.index.resolve(row_id)
        if existing is not None:
            return IngestResult(path="duplicate", row=existing, created=False)

        async with self._lock:
            trace: list[dict] = []
            top, scorer, known = await asyncio.to_thread(self._match, note, trace)

            if known and top is not None:
                row = self._row_from_match(row_id, note, top.row)
                result = IngestResult(
                    path="known",
                    row=row,
                    created=True,
                    matched_row=top.row,
                    match_score=_score_of(top),
                    scorer=scorer,
                    trace=trace,
                )
            else:
                result = await self._unknown(row_id, note, trace)
                if top is not None:
                    result.match_score = _score_of(top)
                    result.scorer = scorer

            # Embed + store: every arm, then the durable log.
            await asyncio.to_thread(self.indexes.add_row, result.row)
            self.index.add_row(result.row)
            if self.store is not None:
                await asyncio.to_thread(self.store.append, result.row)
            trace.append({"stage": "store", "row_id": result.row.row_id,
                          "vector_store": self.indexes.vector_store is not None})

        log(
            logger,
            logging.INFO,
            "taste_ingested",
            path=result.path,
            row_id=result.row.row_id,
            matched=result.matched_row.row_id if result.matched_row else None,
            score=result.match_score,
            degraded=result.degraded,
        )
        return result

    # --- KNOWN: retrieve + rerank ----------------------------------------
    def _match(self, note: str, trace: list[dict]) -> tuple[Candidate | None, str, bool]:
        k = self.settings.ingest_candidates_k
        catalogue = {r.row_id for r in self.index.rows if not r.row_id.startswith(INGESTED_PREFIX)}
        dense = self.indexes.dense(note, k=k, allowed=catalogue)
        sparse = [h for h in self.indexes.sparse(note, k=k * 2) if h[0] in catalogue][:k]

        candidates: dict[str, Candidate] = {}
        for arm, hits in (("dense", dense), ("sparse", sparse)):
            for rank, (rid, score) in enumerate(hits, start=1):
                row = self.index.resolve(rid)
                if row is None:
                    continue
                c = candidates.setdefault(rid, Candidate(row=row))
                c.ranks[arm] = rank
                c.arm_scores[arm] = score
                c.fused += 1.0 / (self.settings.rrf_k + rank)
        trace.append({"stage": "retrieve", "dense": len(dense), "sparse": len(sparse),
                      "candidates": len(candidates)})
        if not candidates:
            return None, "", False

        ce = self.indexes.cross_encoder
        ranked = rerank(
            list(candidates.values()),
            query=note,
            profile=read_any(note),
            top_n=5,
            cross_encoder=ce,
            ce_weight=self.settings.cross_encoder_weight,
            min_relevance=0.0,
        )
        top = ranked[0]
        if "cross_encoder" in top.arm_scores:
            scorer = "cross-encoder"
            known = top.arm_scores["cross_encoder"] >= self.settings.ingest_known_min_relevance
        else:
            scorer = "feature-scorer"
            variety_terms = {t for t in tokenize(top.row.variety.split("(")[0]) if len(t) > 3}
            known = bool(variety_terms) and variety_terms <= set(tokenize(note))
        trace.append({"stage": "rerank", "scorer": scorer, "known": known,
                      "top": [c.trace() | {"variety": c.row.variety} for c in ranked[:3]]})
        return top, scorer, known

    def _row_from_match(self, row_id: str, note: str, matched: WineRow) -> WineRow:
        return WineRow(
            row_id=row_id,
            variety=matched.variety,
            style=matched.style,
            **{axis: getattr(matched, axis) for axis in AXIS_FIELDS},
            confidence=dict(matched.confidence),
            description=note,
            typical_regions=list(matched.typical_regions),
            # Producer names are only trustworthy on a signed row; an upload is not one.
            example_producers=[],
            review_status="unreviewed",
            dataset_version=self.index.version,
        )

    # --- UNKNOWN: LLM profile + web search -------------------------------
    async def _unknown(self, row_id: str, note: str, trace: list[dict]) -> IngestResult:
        degraded: list[str] = []
        profile = await self._profile(note, degraded)
        trace.append({"stage": "llm_profile", "variety": profile.get("variety"),
                      "style": profile.get("style"), "confidence": profile.get("confidence")})
        if not profile.get("is_wine_taste", True):
            raise IngestRejected("That doesn't read as a description of a wine's taste.")
        if profile.get("style") not in STYLES:
            raise IngestRejected("Couldn't tell what style of wine that describes.")

        findings: SearchFindings = await self.searcher.search(
            profile.get("search_query") or f"{profile.get('variety')} wine regions"
        )
        if findings.degraded:
            degraded.append(f"web_search: {findings.reason}")
        trace.append({"stage": "web_search", "searcher": self.searcher.name,
                      "sources": len(findings.sources), "degraded": findings.degraded})

        conf = float(profile.get("confidence") or 0.4)
        conf = min(1.0, max(0.0, conf))
        description = str(profile.get("description") or "").strip() or note
        row = WineRow(
            row_id=row_id,
            variety=str(profile.get("variety") or _UNIDENTIFIED).strip()[:80] or _UNIDENTIFIED,
            style=profile["style"],
            **{axis: profile[axis] for axis in AXIS_FIELDS},
            confidence={axis: conf for axis in AXIS_FIELDS},
            # The user's own words go in too: they are what the next user will type.
            description=f"{description} (User note: {note})"[:600],
            typical_regions=findings.regions,
            example_producers=findings.producers,
            review_status="unreviewed",
            dataset_version=self.index.version,
        )
        return IngestResult(
            path="unknown", row=row, created=True, sources=findings.sources,
            trace=trace, degraded=degraded,
        )

    async def _profile(self, note: str, degraded: list[str]) -> dict:
        from ..orchestrator.gateway.offline_provider import _taste_profile

        payload = {"kind": "taste_profile", "note": note}
        if self.gateway is None:
            degraded.append("llm_profile: no gateway")
            return _taste_profile(payload)
        req = TASTE_PROFILE.build(self.settings.model_ingest_profile, payload)
        ledger = TurnLedger(ceiling_usd=self.settings.cost_ceiling_per_turn_usd)
        try:
            result = await self.gateway.complete(req, ledger)
        except GatewayError as exc:
            degraded.append(f"llm_profile: {type(exc).__name__}")
            return _taste_profile(payload)
        if result.structured is None:
            degraded.append("llm_profile: unstructured reply")
            return _taste_profile(payload)
        if result.degraded:
            degraded.append("llm_profile: offline provider")
        return result.structured


_UNIDENTIFIED = "Unidentified (user taste)"


def _score_of(c: Candidate) -> float:
    return round(c.arm_scores.get("cross_encoder", c.rerank), 6)

