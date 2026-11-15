"""The model gateway and its providers.

`build_gateway` is the only place a provider is chosen, and it is deliberately
forgiving: asking for `anthropic` without a key or without the `orchestrator` extra
installed logs the reason and returns the offline provider rather than failing to
boot. A demo that quietly costs nothing is better than a service that will not start,
and the degradation is visible in `/readyz` and on every `usage` frame.
"""

from __future__ import annotations

import logging

from ...config import Settings
from ...observability import log
from .gateway import (
    BudgetExceeded,
    CallRecord,
    GatewayError,
    ModelGateway,
    ProviderDown,
    TurnLedger,
)
from .offline_provider import OfflineProvider
from .types import Block, ModelDelta, ModelProvider, ModelRequest, ModelResult, estimate_tokens

logger = logging.getLogger("wines_ai.gateway")

__all__ = [
    "Block",
    "BudgetExceeded",
    "CallRecord",
    "GatewayError",
    "ModelDelta",
    "ModelGateway",
    "ModelProvider",
    "ModelRequest",
    "ModelResult",
    "OfflineProvider",
    "ProviderDown",
    "TurnLedger",
    "build_gateway",
    "build_router",
    "estimate_tokens",
    "provider_unavailable_reason",
]


def provider_unavailable_reason(settings: Settings) -> str | None:
    """Why the REQUESTED provider cannot be built, or None if it can.

    Separate from `build_provider` so startup can decide whether to refuse (strict) or
    degrade, and so /readyz can say which it did, without constructing a client twice.
    """
    if settings.llm_provider != "anthropic":
        return None
    if not settings.anthropic_api_key:
        return "WA_ANTHROPIC_API_KEY is not set"
    try:
        import anthropic  # noqa: F401
    except ImportError as exc:
        return f"the orchestrator extra is not installed ({exc})"
    return None


def build_provider(settings: Settings) -> ModelProvider:
    if settings.llm_provider != "anthropic":
        return OfflineProvider()

    if not settings.anthropic_api_key:
        log(
            logger,
            logging.WARNING,
            "provider_downgraded",
            requested="anthropic",
            reason="WA_ANTHROPIC_API_KEY is not set",
        )
        return OfflineProvider()

    try:
        from .anthropic_provider import AnthropicProvider
    except ImportError as exc:
        log(
            logger,
            logging.WARNING,
            "provider_downgraded",
            requested="anthropic",
            reason=f"the orchestrator extra is not installed ({exc})",
        )
        return OfflineProvider()

    return AnthropicProvider(
        api_key=settings.anthropic_api_key, fallbacks=settings.model_server_fallbacks
    )


def build_router(settings: Settings, provider: ModelProvider) -> ModelProvider | None:
    """The LangChain router, when the live provider is Anthropic. Otherwise None.

    None is not a failure: it sends routing through `provider` like every other call,
    which on `offline` is the deterministic router and on `anthropic` without
    `langchain-anthropic` installed is the SDK path. The second case is logged, because
    a deployment that meant to route through LangChain should be able to see it isn't.
    """
    if getattr(provider, "name", "") != "anthropic":
        return None
    try:
        import langchain_anthropic  # noqa: F401

        from .langchain_router import LangChainRouter
    except ImportError as exc:
        log(
            logger,
            logging.WARNING,
            "router_langchain_unavailable",
            reason=f"langchain-anthropic is not installed ({exc}); routing via the SDK",
        )
        return None
    return LangChainRouter(
        api_key=settings.anthropic_api_key, timeout_seconds=settings.model_timeout_seconds
    )


def build_gateway(settings: Settings) -> ModelGateway:
    provider = build_provider(settings)
    return ModelGateway(
        provider,
        timeout_seconds=settings.model_timeout_seconds,
        max_attempts=settings.model_max_attempts,
        breaker_threshold=settings.model_breaker_threshold,
        breaker_cooldown_seconds=settings.model_breaker_cooldown_seconds,
        router=build_router(settings, provider),
    )
