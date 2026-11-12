"""The router's Haiku call, made through LangChain.

Imported only when the `anthropic` provider is live and the `orchestrator` extra is
installed - the same lazy rule as `anthropic_provider.py`, so the base install still
boots with no key and no package (NFR-4).

## Why this is a provider-shaped object and not a call in router.py

`ModelGateway.complete_route()` runs this object's `complete()` exactly where it would
have run the SDK provider's: inside the gateway's timeout, bounded retry, circuit
breaker, per-turn cost ceiling and cost trace. Calling LangChain from `router.py`
directly would have been shorter and would have taken the router out of every one of
those - a routing call that no ceiling sees and no trace records.

The request it receives is the one `ROUTE.build()` produced, so the prompt bytes, the
pre-call cost estimate and the `prompt_id` in the trace are identical whichever path
answers.

## API facts this file depends on

* **No `temperature`.** Haiku 5.5 returns a 400 on any non-default `temperature`,
  `top_p` or `top_k`. Determinism comes from the forced tool call below.
* **Thinking is on by default and spends `max_tokens`.** Turned off here
  (`{"type": "disabled"}`, accepted on Haiku 5.5 at effort `high` or below), with
  effort `low`. A cap exhausted by thinking returns no tool call at all, which this
  file reports as degraded rather than as a classification.
* **`function_calling`, not `json_schema`.** LangChain's profile for Haiku 5.5 reports
  `structured_output: false`, but the model takes a forced `tool_choice`, which is what
  makes `intent` an enum the answer cannot leave.
* **LangChain's `input_tokens` is a TOTAL.** It adds cache reads and cache writes back
  onto Anthropic's fresh-input count. `pricing.cost_usd` prices the three separately,
  so passing the total through would bill every cached token twice - once at the full
  input rate and again at the cache rate. `_usage()` takes them back out.
* **Retries belong to the gateway.** `max_retries=0` here, so a failed call is retried
  by `ModelGateway._attempt` with its backoff, and every failure is counted by the
  breaker. Leaving LangChain's own two retries on would hide failures from the breaker
  and multiply the worst-case wait.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from ...observability import log
from .types import ModelRequest, ModelResult

logger = logging.getLogger("wines_ai.gateway.langchain_router")

Intent = Literal["interview", "recommend", "refine", "out_of_scope"]
Style = Literal["red", "white", "rose", "sparkling", "dessert"]
Sweetness = Literal["dry", "off_dry", "sweet"]
Body = Literal["light", "medium", "full"]
Oak = Literal["none", "subtle", "pronounced"]


def _schema():
    """The structured-output model. Built lazily: pydantic is a base dependency, but
    keeping construction here means importing this module costs nothing until used."""
    from pydantic import BaseModel, Field

    class Slots(BaseModel):
        """Taste axes this turn states. Null for every axis it does not state."""

        style: Style | None = Field(default=None, description="the style the turn states")
        sweetness: Sweetness | None = Field(
            default=None, description="the sweetness the turn states"
        )
        body: Body | None = Field(default=None, description="the body the turn states")
        oak: Oak | None = Field(default=None, description="the oak the turn states")

    class Route(BaseModel):
        """Route this turn of a wine conversation to a workflow."""

        # First on purpose. Thinking is off, so the order of these fields is the
        # order the model commits to them: with `intent` first it chose a route and
        # then reasoned, and a live run produced reasoning that concluded
        # 'sufficient' under an `interview` answer, five times out of five.
        reasoning: str = Field(
            description=(
                "Written before choosing the intent: one or two sentences applying the "
                "decision procedure - the rule that fires, the axis or the topic."
            )
        )
        intent: Intent = Field(
            description=(
                "Which workflow handles this turn. 'interview' keeps learning the "
                "user's taste because the profile is not yet sufficient. 'recommend' "
                "serves wines because it is. 'refine' corrects one axis of a result "
                "set the user has already seen. 'out_of_scope' declines something the "
                "dataset cannot answer."
            )
        )
        confidence: float = Field(
            ge=0.0,
            le=1.0,
            description=(
                "How confident you are, 0 to 1. Honest rather than generous: a low "
                "score routes to the keyword router, which is the safe default."
            ),
        )
        out_of_scope_topic: str | None = Field(
            default=None,
            description=(
                "Only when intent is 'out_of_scope': price, availability, health, "
                "purchase, vintage, injection, or generic."
            ),
        )
        slots: Slots = Field(
            default_factory=Slots,
            description=("Axis values this turn actually states. Never guess one to fill a slot."),
        )

    return Route


class LangChainRouter:
    """Answers `route@N` requests with Haiku through LangChain."""

    name = "langchain"

    def __init__(self, *, api_key: str, timeout_seconds: float) -> None:
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._chains: dict[str, Any] = {}

    def _chain(self, model: str, max_tokens: int, effort: str):
        key = f"{model}|{max_tokens}|{effort}"
        if key not in self._chains:
            from langchain_anthropic import ChatAnthropic

            llm = ChatAnthropic(
                model=model,
                api_key=self._api_key,
                max_tokens=max_tokens,
                thinking={"type": "disabled"},
                reasoning_effort=effort,
                timeout=self._timeout,
                max_retries=0,
            )
            self._chains[key] = llm.with_structured_output(
                _schema(), method="function_calling", include_raw=True
            )
        return self._chains[key]

    @staticmethod
    def _messages(req: ModelRequest) -> list:
        """The request's blocks, in order, with the cache breakpoint after the last
        cacheable system block - the same placement the SDK provider uses."""
        system = [{"type": "text", "text": b.text} for b in req.system if b.text]
        last = max((i for i, b in enumerate(req.system) if b.cacheable and b.text), default=-1)
        if last >= 0:
            system[last]["cache_control"] = {"type": "ephemeral"}
        user = "\n\n".join(b.text for b in req.user if b.text)
        return [("system", system), ("human", user)]

    async def complete(self, req: ModelRequest) -> ModelResult:
        chain = self._chain(req.model, req.max_tokens, req.effort)
        envelope = await chain.ainvoke(self._messages(req))
        raw = envelope.get("raw")
        usage = _usage(getattr(raw, "usage_metadata", None))
        parsed = envelope.get("parsed")

        if parsed is None:
            stop = (getattr(raw, "response_metadata", None) or {}).get("stop_reason")
            log(
                logger,
                logging.ERROR,
                "route_no_tool_call",
                prompt_id=req.prompt_id,
                model=req.model,
                stop_reason=stop,
                parsing_error=repr(envelope.get("parsing_error")),
            )
            # Degraded, not raised: the router treats a missing intent as below the
            # floor and answers from the keyword lane. The tokens were still spent.
            return ModelResult(model=req.model, degraded=True, **usage)

        structured = parsed.model_dump()
        # The router reads `slots` as axis -> value and drops nulls itself; keep only
        # stated axes so the shape matches what the SDK path returns.
        structured["slots"] = {k: v for k, v in structured["slots"].items() if v is not None}
        return ModelResult(model=req.model, structured=structured, **usage)


def _usage(usage_metadata: dict | None) -> dict[str, int]:
    """LangChain's usage -> the gateway's four separately-priced counts."""
    usage = usage_metadata or {}
    details = usage.get("input_token_details") or {}
    cache_read = int(details.get("cache_read") or 0)
    # LangChain zeroes the generic `cache_creation` key when it reports the TTL split.
    cache_write = int(details.get("cache_creation") or 0) or (
        int(details.get("ephemeral_5m_input_tokens") or 0)
        + int(details.get("ephemeral_1h_input_tokens") or 0)
    )
    total_in = int(usage.get("input_tokens") or 0)
    return {
        "tokens_in": max(0, total_in - cache_read - cache_write),
        "tokens_out": int(usage.get("output_tokens") or 0),
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
    }
