"""The router's Haiku call through LangChain, inside the gateway.

No network: the chain is replaced with a fake wherever a call would leave the process.
What these pin is the contract the swap must not break - the router still counts
toward the ceiling, the breaker and the trace; tokens are priced once; the request
carries none of the parameters Haiku 5.5 rejects; and a key-less deployment still
routes on the offline provider exactly as before.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from wines_ai.config import Settings
from wines_ai.orchestrator.gateway import (
    BudgetExceeded,
    ModelGateway,
    OfflineProvider,
    ProviderDown,
    TurnLedger,
    build_gateway,
    build_router,
)
from wines_ai.orchestrator.gateway.langchain_router import LangChainRouter, _schema, _usage
from wines_ai.orchestrator.gateway.types import ModelResult
from wines_ai.orchestrator.prompts import ROUTE, ROUTE_GUIDE
from wines_ai.orchestrator.router import route
from wines_ai.orchestrator.state import GraphState
from wines_ai.taste.axes import AXES_BY_ID

HAIKU = "claude-haiku-5-5"


def _gateway(provider, router=None, **kwargs):
    defaults = dict(
        timeout_seconds=5.0, max_attempts=2, breaker_threshold=3, breaker_cooldown_seconds=30.0
    )
    defaults.update(kwargs)
    return ModelGateway(provider, router=router, **defaults)


class _Upstream:
    """Stands in for the Anthropic provider: not free, and must never be called for
    routing while a router is set."""

    name = "anthropic"

    def __init__(self):
        self.calls = 0

    async def complete(self, req):
        self.calls += 1
        raise AssertionError("routing must go to the router, not the provider")

    async def stream(self, req):  # pragma: no cover - unused
        raise AssertionError
        yield


class _FakeRouter:
    name = "langchain"

    def __init__(self, structured=None, *, fail_times=0, usage=None):
        self.structured = structured
        self.fail_times = fail_times
        self.usage = usage or dict(tokens_in=60, tokens_out=40, cache_read_tokens=4000)
        self.calls = 0
        self.requests = []

    async def complete(self, req):
        self.calls += 1
        self.requests.append(req)
        if self.calls <= self.fail_times:
            raise RuntimeError("upstream 529")
        return ModelResult(model=req.model, structured=self.structured, **self.usage)


def _state(utterance, profile=None, previous=None):
    return GraphState(
        turn_id="t",
        conversation_id="c",
        utterance=utterance,
        selected_chip_id=None,
        profile=profile or {},
        history=[],
        previous_row_ids=previous or [],
        dataset_version="v",
    )


# --- the prompt -----------------------------------------------------------


def test_route_v2_is_the_tested_guide_from_disk():
    on_disk = (
        Path(__file__).parents[1] / "src" / "wines_ai" / "orchestrator" / "intent_prompt.md"
    ).read_text(encoding="utf-8")
    assert ROUTE.version == "2"
    assert ROUTE.instructions == ROUTE_GUIDE == on_disk
    req = ROUTE.build(HAIKU, {"utterance": "x"})
    assert req.prompt_id == "route@2"
    assert req.system[-1].text == on_disk and req.system[-1].cacheable


# --- wiring: who answers the route call -----------------------------------


def test_offline_deployment_gets_no_router_and_routes_exactly_as_before():
    gateway = build_gateway(Settings(llm_provider="offline"))
    assert gateway.router is None and gateway.provider_name == "offline"
    state = _state("Red")
    asyncio.run(route(gateway, TurnLedger(ceiling_usd=1.0), state, model=HAIKU))
    assert state.intent == "interview"
    assert state.slots.get("style") == "red"


def test_a_missing_key_downgrades_to_offline_with_no_router():
    gateway = build_gateway(Settings(llm_provider="anthropic", anthropic_api_key=""))
    assert gateway.provider_name == "offline" and gateway.router is None


def test_the_anthropic_provider_gets_the_langchain_router():
    settings = Settings(llm_provider="anthropic", anthropic_api_key="sk-ant-test")
    gateway = build_gateway(settings)
    assert gateway.provider_name == "anthropic"
    assert isinstance(gateway.router, LangChainRouter)


def test_build_router_returns_none_for_a_provider_that_is_not_anthropic():
    assert build_router(Settings(), OfflineProvider()) is None


# --- the gateway contract the swap must keep -------------------------------


def test_route_goes_to_the_router_and_is_recorded_in_the_ledger():
    upstream = _Upstream()
    router = _FakeRouter({"intent": "interview", "confidence": 0.9, "slots": {}})
    gateway = _gateway(upstream, router)
    ledger = TurnLedger(ceiling_usd=1.0)

    asyncio.run(gateway.complete_route(ROUTE.build(HAIKU, {"utterance": "x"}), ledger))

    assert router.calls == 1 and upstream.calls == 0
    [call] = ledger.trace()
    assert call["prompt_id"] == "route@2" and call["model"] == HAIKU
    assert call["cache_read"] == 4000 and call["tokens_in"] == 60
    assert call["cost_usd"] > 0, "a live routing call must be priced, not recorded as free"


def test_the_turn_ceiling_refuses_the_route_call_before_it_runs():
    router = _FakeRouter({"intent": "interview", "confidence": 0.9, "slots": {}})
    gateway = _gateway(_Upstream(), router)
    with pytest.raises(BudgetExceeded):
        asyncio.run(gateway.complete_route(ROUTE.build(HAIKU, {}), TurnLedger(ceiling_usd=1e-9)))
    assert router.calls == 0


def test_route_failures_are_retried_by_the_gateway_and_counted_by_the_breaker():
    router = _FakeRouter(fail_times=99)
    gateway = _gateway(_Upstream(), router, max_attempts=2, breaker_threshold=2)
    ledger = TurnLedger(ceiling_usd=1.0)
    req = ROUTE.build(HAIKU, {"utterance": "x"})

    with pytest.raises(ProviderDown):
        asyncio.run(gateway.complete_route(req, ledger))
    assert router.calls == 2, "the gateway's bounded retry owns the route call"

    with pytest.raises(ProviderDown, match="breaker is open"):
        asyncio.run(gateway.complete_route(req, ledger))
    assert router.calls == 2, "an open breaker must stop routing calls reaching upstream"


def test_a_router_failure_falls_back_to_the_keyword_lane_not_a_turn_failure():
    gateway = _gateway(_Upstream(), _FakeRouter(fail_times=99), max_attempts=1)
    state = _state("Red")
    asyncio.run(route(gateway, TurnLedger(ceiling_usd=1.0), state, model=HAIKU))
    assert state.intent_source == "keyword" and state.intent == "interview"


def test_a_confident_model_answer_drives_the_route_and_its_slots():
    router = _FakeRouter(
        {
            "intent": "recommend",
            "confidence": 0.9,
            "reasoning": "Completes body for a red.",
            "out_of_scope_topic": None,
            "slots": {"body": "full"},
        }
    )
    state = _state("Rich and bold", profile={"style": "red", "sweetness": "dry"})
    asyncio.run(route(_gateway(_Upstream(), router), TurnLedger(1.0), state, model=HAIKU))
    assert (state.intent, state.intent_source) == ("recommend", "model")
    assert state.slots["body"] == "full"


def test_a_low_confidence_model_answer_is_floored_to_the_keyword_answer():
    router = _FakeRouter({"intent": "recommend", "confidence": 0.2, "slots": {}})
    state = _state("Hello")
    asyncio.run(route(_gateway(_Upstream(), router), TurnLedger(1.0), state, model=HAIKU))
    assert state.intent_source == "keyword" and state.intent == "interview"


def test_the_safety_table_still_wins_before_any_routing_call():
    router = _FakeRouter({"intent": "recommend", "confidence": 0.99, "slots": {}})
    state = _state("a red under 15")
    asyncio.run(route(_gateway(_Upstream(), router), TurnLedger(1.0), state, model=HAIKU))
    assert state.intent == "out_of_scope" and state.out_of_scope_topic == "price"
    assert router.calls == 0, "a lexical safety match must never reach the model"


# --- the LangChain adapter -------------------------------------------------


def test_usage_prices_each_token_once():
    """LangChain's input_tokens is fresh + cache read + cache write."""
    got = _usage(
        {
            "input_tokens": 4146,
            "output_tokens": 134,
            "input_token_details": {"cache_read": 3890, "cache_creation": 0},
        }
    )
    assert got == dict(tokens_in=256, tokens_out=134, cache_read_tokens=3890, cache_write_tokens=0)


def test_usage_reads_cache_writes_from_the_ttl_split():
    got = _usage(
        {
            "input_tokens": 4200,
            "output_tokens": 10,
            "input_token_details": {
                "cache_read": 0,
                "cache_creation": 0,
                "ephemeral_5m_input_tokens": 4000,
                "ephemeral_1h_input_tokens": 0,
            },
        }
    )
    assert got["cache_write_tokens"] == 4000 and got["tokens_in"] == 200


def test_usage_tolerates_a_response_with_no_usage():
    assert _usage(None) == dict(
        tokens_in=0, tokens_out=0, cache_read_tokens=0, cache_write_tokens=0
    )


class _FakeChain:
    def __init__(self, envelope):
        self.envelope = envelope
        self.messages = None

    async def ainvoke(self, messages):
        self.messages = messages
        return self.envelope


class _Raw:
    def __init__(self, usage=None, stop_reason="tool_use"):
        self.usage_metadata = usage or {"input_tokens": 100, "output_tokens": 20}
        self.response_metadata = {"stop_reason": stop_reason}


def _router_with(chain):
    router = LangChainRouter(api_key="sk-ant-test", timeout_seconds=5.0)
    router._chain = lambda *a, **k: chain
    return router


def test_the_adapter_returns_the_shape_the_router_reads():
    Route = _schema()
    parsed = Route(
        intent="recommend",
        confidence=0.9,
        reasoning="r",
        slots={"style": "red", "body": "light"},
    )
    chain = _FakeChain({"raw": _Raw(), "parsed": parsed, "parsing_error": None})
    result = asyncio.run(_router_with(chain).complete(ROUTE.build(HAIKU, {"utterance": "x"})))
    assert result.structured["intent"] == "recommend"
    assert result.structured["slots"] == {"style": "red", "body": "light"}, "nulls dropped"
    assert not result.degraded and result.tokens_in == 100


def test_no_tool_call_is_degraded_and_still_reports_the_tokens_spent():
    chain = _FakeChain(
        {"raw": _Raw(stop_reason="max_tokens"), "parsed": None, "parsing_error": None}
    )
    result = asyncio.run(_router_with(chain).complete(ROUTE.build(HAIKU, {})))
    assert result.degraded and result.structured is None
    assert result.tokens_in == 100, "tokens spent on a failed parse were still billed"


def test_messages_put_the_cache_breakpoint_after_the_last_cacheable_block():
    chain = _FakeChain({"raw": _Raw(), "parsed": None, "parsing_error": None})
    asyncio.run(_router_with(chain).complete(ROUTE.build(HAIKU, {"utterance": "Red"})))
    (sys_role, system), (user_role, user) = chain.messages
    assert (sys_role, user_role) == ("system", "human")
    assert "cache_control" in system[-1] and all("cache_control" not in b for b in system[:-1])
    assert system[-1]["text"] == ROUTE_GUIDE
    assert '"utterance": "Red"' in user, "the per-turn payload goes after the cached prefix"


def test_the_slot_enums_cannot_drift_from_the_axis_table():
    slots = _schema().model_json_schema()["$defs"]["Slots"]["properties"]
    for axis in ("style", "sweetness", "body", "oak"):
        enum = next(o["enum"] for o in slots[axis]["anyOf"] if "enum" in o)
        assert enum == [level.value for level in AXES_BY_ID[axis].levels], axis


def test_the_request_carries_nothing_haiku_5_5_rejects():
    """temperature/top_p/top_k are a 400 on Haiku 5.5; thinking must be off; retries
    belong to the gateway. Checked on the payload LangChain would actually send."""
    from langchain_anthropic import ChatAnthropic

    router = LangChainRouter(api_key="sk-ant-test", timeout_seconds=5.0)
    req = ROUTE.build(HAIKU, {"utterance": "x"})
    chain = router._chain(req.model, req.max_tokens, req.effort)

    def find(node):
        if isinstance(node, ChatAnthropic):
            return node, {}
        for attr in ("bound", "first", "steps__", "steps"):
            child = getattr(node, attr, None)
            if isinstance(child, dict):  # RunnableParallel keeps its steps in a dict
                child = list(child.values())
            for item in child if isinstance(child, (list, tuple)) else [child]:
                if item is None:
                    continue
                found = find(item)
                if found:
                    llm, kwargs = found
                    return llm, {**getattr(node, "kwargs", {}), **kwargs}
        return None

    found = find(chain)
    assert found, "no ChatAnthropic found in the structured-output chain"
    llm, bound = found
    bound = {k: v for k, v in bound.items() if k != "ls_structured_output_format"}
    payload = llm._get_request_payload(LangChainRouter._messages(req), **bound)

    assert llm.max_retries == 0
    assert not {"temperature", "top_p", "top_k"} & payload.keys()
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["output_config"]["effort"] == "low"
    assert payload["tool_choice"] == {"type": "tool", "name": "Route"}
    intent = payload["tools"][0]["input_schema"]["properties"]["intent"]
    assert intent["enum"] == ["interview", "recommend", "refine", "out_of_scope"]


def test_reasoning_is_written_before_the_intent_is_chosen():
    """Thinking is off, so field order is decision order. With `intent` first, a live
    run concluded 'sufficient' in its reasoning under an `interview` answer, 5/5."""
    fields = list(_schema().model_json_schema()["properties"])
    assert fields.index("reasoning") < fields.index("intent")
