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
        "http://localhost:5173",
        "http://127.0.0.1:5173",
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
    results_max: int = 5
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
    retriever_k: int = 50
    rrf_k: int = 60
    mmr_lambda: float = 0.7
    rerank_top_n: int = 10
    context_token_budget: int = 8000
    # 384-d matches the bi-encoder the diagram specifies, so the offline embedder and a
    # real one are swappable without rebuilding the index shape.
    embedding_dim: int = 384
    # Stage K. On by default: the verifier is the last thing standing between a model
    # and an unsourced claim, and it runs on the cheapest tier.
    verify_enabled: bool = True

    # --- cost ceilings ---------------------------------------------------
    # Exceeding a ceiling degrades to the deterministic engine; it never errors.
    cost_ceiling_per_turn_usd: float = 0.05
    cost_ceiling_per_session_usd: float = 0.50
    cost_ceiling_global_daily_usd: float = 10.00
    turn_cache_enabled: bool = True
    turn_cache_ttl_seconds: int = 3600
    turn_cache_max_entries: int = 512

    @property
    def resolved_dataset_path(self) -> Path:
        if self.dataset_path:
            return Path(self.dataset_path).expanduser().resolve()
        return Path(__file__).resolve().parent / "dataset" / "seed" / "wines.seed.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
