"""Settings. Every provider, limit and model id is a value here, nothing is hardcoded.

Phase 1 boots with an entirely empty environment: no API key, no network, no paths.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WA_", env_file=".env", extra="ignore", env_parse_none_str="null"
    )

    # --- transport -------------------------------------------------------
    cors_origins: list[str] = [
        "http://localhost:5180",
        "http://127.0.0.1:5180",
        "http://localhost:3000",
    ]
    cookie_secret: str = "dev-only-change-me"
    cookie_secure: bool = False
    session_cookie_name: str = "wa_session"
    age_cookie_name: str = "wa_age"
    cookie_max_age_seconds: int = 60 * 60 * 24 * 30

    # The one switch that makes the frontend's casing choice free. `snake` matches the
    # architecture diagram, which writes turn_id / row_id / dataset_version on the wire.
    # Input always accepts both spellings; this controls what is emitted.
    wire_case: Literal["snake", "camel"] = "snake"

    # --- storage ---------------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./var/wines.db"

    # --- dataset ---------------------------------------------------------
    dataset_path: str = ""  # empty -> the bundled seed artifact

    # --- limits ----------------------------------------------------------
    rate_limit_reads_per_min: int = 120
    # 30/min: a real user answers three interview questions then taps refine chips a
    # few times, which clears 12/min easily. Still a hard bound on spend - 30 turns a
    # minute per IP is the ceiling on how fast one client can run up a model bill.
    rate_limit_turns_per_min: int = 30
    conversation_page_size: int = 20
    conversation_page_size_max: int = 100
    title_max_chars: int = 52
    turn_expiry_seconds: int = 120
    idempotency_retention_seconds: int = 60 * 60 * 24
    max_message_chars: int = 2000

    # --- taste / recommendation -----------------------------------------
    confidence_threshold: float = 0.75
    max_interview_questions: int = 3
    results_min: int = 3
    results_max: int = 3
    # The abstention gate (FR-13), in two parts.
    #
    # `sweetness_tolerance_levels` is the real gate and is deliberately NOT a
    # distance: a candidate more than this many levels from the sweetness that was
    # asked for is not a match at all. Serving a properly-sweet dessert wine to
    # someone who said "not sweet at all" is the one error a novice notices
    # instantly, and FR-13 requires saying so rather than widening the filter.
    #
    # `max_match_distance` is only a backstop. It cannot carry the gate on its own,
    # because the weighted distance is normalised over whichever axes the profile
    # happens to have filled - the same one-step sweetness miss scores 0.33 for a
    # red (three questions asked) and 0.50 for a dessert (two), so any single
    # threshold is either too tight for one or too loose for the other.
    sweetness_tolerance_levels: int = 1
    # The same hard rule for the style's third axis (body for red, oak for the rest),
    # for the same reason: a weighted average lets a matching sweetness drag an
    # opposite-end body back up. Found live: a user-uploaded full-bodied Saperavi
    # ranked FIRST for "a light red that isn't sweet" (axis agreement 0.667 with body
    # at the far end). One level keeps the honest near-miss ("a little fuller").
    third_axis_tolerance_levels: int = 1
    max_match_distance: float = 0.6

    # --- engine ----------------------------------------------------------
    engine: Literal["deterministic", "orchestrated"] = "deterministic"
    stream_token_delay_ms: int = 12

    # --- lane 3 / lane 4: read only by the orchestrated engine -----------
    # Model tiering straight from the diagram: the cheapest tier carries the highest
    # call volume, and the expensive model only ever writes the final copy.
    model_router: str = "claude-haiku-5-5"
    model_rewriter: str = "claude-haiku-5-5"
    model_verifier: str = "claude-haiku-5-5"
    model_generator: str = "claude-sonnet-5-5"
    # Per-workflow generators. Interview answers are Sonnet; refine is Opus (the delta
    # has to be read against what the user saw, which is the hardest judgement in the
    # product); recommend is Sonnet and escalates to Opus only on a complex turn - see
    # `workflows/ask.py::choose_generator`.
    model_interview: str = "claude-sonnet-5-5"
    model_recommend: str = "claude-sonnet-5-5"
    model_recommend_complex: str = "claude-opus-5-5"
    model_refine: str = "claude-opus-5-5"

    # Which provider the orchestrated engine's gateway calls.
    #
    # `offline` is the default and is not a mock: the whole A-to-K pipeline runs, the
    # traces and checkpoints are written, and the SSE frames are identical - the three
    # natural-language judgements are answered from structure instead of from a model.
    # So the orchestrated engine is fully exercisable with an empty environment, and
    # NFR-4 (no credentials) still holds until someone deliberately sets a key.
    llm_provider: Literal["offline", "anthropic"] = "offline"
    anthropic_api_key: str = ""
    # What to do when the requested provider cannot be built - no key, or the
    # `orchestrator` extra not installed.
    #
    # False (the default) degrades to `offline` and logs the reason, which is right for
    # a demo: a service that boots and costs nothing beats a service that will not
    # start. True refuses, which is right for a deployment that MEANT to call the
    # models: silently serving templated copy in production is a misconfiguration
    # wearing a working service as a disguise, and it is only visible in the bill
    # that never arrives.
    require_llm_provider: bool = False

    # Gateway resilience. The product of timeout x attempts bounds the worst case a
    # single turn can spend waiting on an upstream.
    model_timeout_seconds: float = 20.0
    model_max_attempts: int = 2
    model_breaker_threshold: int = 4
    model_breaker_cooldown_seconds: float = 30.0
    # Server-side refusal fallback on the generator: a declined request is re-run on a
    # fallback model inside the same call. Without it a refused turn simply stops.
    model_server_fallbacks: bool = True

    # Retrieval knobs (band 2).
    # Top-K per text arm (dense and BM25). 25 of a 45-row corpus whose largest style
    # has 13 rows means every in-style row reaches the reranker today; the setting is
    # sized for the corpus band 4 will ship, not this one.
    retriever_k: int = 25
    rrf_k: int = 60
    mmr_lambda: float = 0.7
    # Rows handed to augmentation after rerank. Recommend/refine need room for MMR to
    # pick 3-5 distinct varieties; an interview suggestion needs fewer.
    rerank_top_n: int = 10
    interview_top_n: int = 3
    # Dense store and reranker. `auto` uses embedded Qdrant + fastembed (bge-base,
    # 768-d) and a local ONNX cross-encoder when the `retrieval` extra is installed,
    # and the dependency-free hashed embedder + feature scorer when it is not - so the
    # base install still boots with no network.
    retrieval_backend: Literal["auto", "qdrant", "local"] = "auto"
    qdrant_path: str = ""  # empty = in-memory; the corpus is rebuilt at boot anyway
    embedding_model: str = "BAAI/bge-base-en-v1.5"
    reranker_model: str = "BAAI/bge-reranker-base"
    # Final rerank score = w * cross-encoder logit (min-max normalised over the
    # candidate set) + (1 - w) * axis agreement. A text cross-encoder cannot see that
    # "dry" and "sweet" are opposites on a labelled axis; the axis term can.
    cross_encoder_weight: float = 0.6
    # Absolute floor on sigmoid(logit): rows the cross-encoder judges below this are
    # dropped after ordering. bge-reranker-base is compressed - a clearly relevant
    # wine scored ~0.07, an unrelated one ~0.001 - so the floor sits low. It never
    # empties the list; abstention stays with the gate. 0 disables it.
    rerank_min_relevance: float = 0.005
    context_token_budget: int = 8000
    # 768-d matches bge-base-en-v1.5, so the offline hashed embedder and the real one
    # produce the same index shape and stay swappable.
    embedding_dim: int = 768
    # Stage K. On by default: the verifier is the last thing standing between a model
    # and an unsourced claim, and it runs on the cheapest tier.
    verify_enabled: bool = True

    # --- cost ceilings ---------------------------------------------------
    # Exceeding a ceiling degrades to the deterministic engine; it never errors.
    cost_ceiling_per_turn_usd: float = 0.05
    cost_ceiling_per_session_usd: float = 0.50
    cost_ceiling_global_daily_usd: float = 10.00
    turn_cache_enabled: bool = True

    # --- taste ingestion (POST /api/v1/tastes) ---------------------------
    # A user-uploaded tasting note is either KNOWN (the reranker matches it to an
    # existing row) or UNKNOWN (an LLM profiles it and a web search enriches it).
    # Either way it is embedded and upserted into the vector store as an
    # `unreviewed` row; the frozen dataset file is never modified.
    ingest_enabled: bool = True
    # Calibrated cross-encoder relevance (sigmoid of the logit) at or above which the
    # top match counts as KNOWN. bge-reranker-base is compressed - a clearly relevant
    # row scores ~0.07 - so this sits well under 0.5. Without a cross-encoder, only an
    # explicitly named variety makes a taste known.
    ingest_known_min_relevance: float = 0.05
    ingest_candidates_k: int = 20
    # Model that profiles an unknown taste (structured output, enum-constrained axes).
    model_ingest_profile: str = "claude-sonnet-5-5"
    # Model that runs the server-side web search tool for an unknown taste.
    model_ingest_search: str = "claude-sonnet-5-5"
    web_search_enabled: bool = True
    web_search_max_uses: int = 3
    # Append-only JSONL of ingested rows, replayed at boot so uploads survive a
    # restart. Empty = <backend>/data/ingested_tastes.jsonl.
    ingest_store_path: str = ""
    # Upper bound on an uploaded note, in characters.
    ingest_max_chars: int = 1200

    turn_cache_ttl_seconds: int = 3600
    turn_cache_max_entries: int = 512

    @property
    def resolved_dataset_path(self) -> Path:
        if self.dataset_path:
            return Path(self.dataset_path).expanduser().resolve()
        return Path(__file__).resolve().parent / "dataset" / "seed" / "wines.seed.json"

    @property
    def resolved_ingest_store_path(self) -> Path:
        if self.ingest_store_path:
            return Path(self.ingest_store_path).expanduser().resolve()
        return Path(__file__).resolve().parents[2] / "data" / "ingested_tastes.jsonl"


@lru_cache
def get_settings() -> Settings:
    return Settings()
