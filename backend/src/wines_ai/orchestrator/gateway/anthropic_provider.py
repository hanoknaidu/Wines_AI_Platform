"""The Anthropic SDK, behind the provider seam. Imported only when selected.

`anthropic` is in the `orchestrator` extra, not the base install, so this module is
imported lazily by `build_gateway` and the service still boots on an empty
environment with no key and no package (NFR-4).

## What this file knows that the rest of the system should not

Four API facts are load-bearing here and nowhere else:

* **`temperature` is rejected.** Sending `temperature`, `top_p` or `top_k` returns a
  400 on every current model. Determinism on the router and the extractor comes from
  `output_config.format` - a JSON schema the response is constrained to - and spend is
  tuned with `output_config.effort`, which is what `ModelRequest.effort` carries.
* **Caching is a byte-exact prefix match.** `cache_control` goes on the LAST cacheable
  system block; everything after it is fresh input every turn. `ModelRequest` already
  guarantees the ordering, so all this file does is place the breakpoint.
* **A refusal is an HTTP 200.** `stop_reason == "refusal"` arrives as a successful
  response with no usable content. It is translated here into a degraded
  `ModelResult`, so the workflows handle it through the same path as a verifier
  failure rather than discovering an empty string later.
* **Thinking is ON by default, and it spends `max_tokens`.** Every current model runs
  adaptive thinking unless told otherwise, and thinking tokens come out of the same
  output budget as the answer. With `max_tokens: 200` on the card-reason prompt, the
  model spent all 200 thinking and returned **no text block at all** - so four of five
  cards silently used their templated fallback, and the verifier's JSON was truncated
  into `structured_output_unparseable`. Both looked like success in every log except
  the per-call trace. These calls want no thinking: they are short, mechanical, and
  bounded by a schema or a one-sentence brief. `_thinking()` turns it off per model,
  because the models disagree about how (see the method), and the budgets below carry
  headroom anyway.
* **Server-side fallback is opt-in.** The generator runs on Sonnet 5.5, which can
  decline; `fallbacks="default"` re-runs the same request on a fallback model inside
  the same call, routed by refusal category. It is enabled here by default because a
  refused turn otherwise just stops - see the note in `build_gateway`.

## Streaming

The generator is the only streaming call. `messages.stream()` is used rather than the
raw event iterator because it accumulates the final message, which is where the real
token counts live - and CostGuard's ceilings are only as good as the numbers it is
given.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from ...observability import log
from .types import ModelDelta, ModelRequest, ModelResult

logger = logging.getLogger("wines_ai.gateway.anthropic")

# The generator's model line can decline a request. Routed by category, inside the
# same call, so a refusal degrades instead of ending the turn.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, *, api_key: str, fallbacks: bool = True) -> None:
        from anthropic import AsyncAnthropic

        # The SDK's own retry is left at its default of 2 and the gateway's bounded
        # retry sits on top; both are capped, so the product is bounded too.
        self._client = AsyncAnthropic(api_key=api_key)
        self._fallbacks = fallbacks

    # --- shared request assembly ----------------------------------------
    @staticmethod
    def _thinking(model: str) -> dict | None:
        """How to turn thinking off, which is model-specific and not uniform.

        * Haiku 5.5 accepts `{"type": "disabled"}` at effort `high` or below - ours is
          `low`.
        * Sonnet 5.5 **400s on `disabled`**; `{"type": "between_tools"}` is the way to
          turn it off there, it takes no other field, and it is accepted at effort
          `high` or below.
        * Anything else: leave it adaptive and rely on the `max_tokens` headroom. An
          Opus-tier model cannot disable thinking at all, so a config that points the
          generator at one must not be refused here.
        """
        if model.startswith("claude-haiku"):
            return {"type": "disabled"}
        if model.startswith("claude-sonnet"):
            return {"type": "between_tools"}
        return None
    def _params(self, req: ModelRequest) -> dict[str, Any]:
        system = [{"type": "text", "text": b.text} for b in req.system if b.text]
        # The cache breakpoint goes after the last cacheable system block. Minimum
        # cacheable prefixes are model-dependent (512-4096 tokens); a prefix under the
        # floor simply does not cache, which is why this is unconditional rather than
        # gated on a length guess.
        last_cacheable = max(
            (i for i, b in enumerate(req.system) if b.cacheable and b.text), default=-1
        )
        if last_cacheable >= 0:
            system[last_cacheable]["cache_control"] = {"type": "ephemeral"}

        content = "\n\n".join(b.text for b in req.user if b.text)
        params: dict[str, Any] = {
            "model": req.model,
            "max_tokens": req.max_tokens,
            "messages": [{"role": "user", "content": content}],
            "output_config": {"effort": req.effort},
        }
        thinking = self._thinking(req.model)
        if thinking is not None:
            params["thinking"] = thinking
        if system:
            params["system"] = system
        if req.schema is not None:
            params["output_config"]["format"] = {
                "type": "json_schema",
                "schema": req.schema["schema"],
            }
        return params

    @staticmethod
    def _usage(message: Any, req: ModelRequest) -> dict[str, int]:
        usage = getattr(message, "usage", None)
        # `input_tokens` is the FRESH input only. On a warm prefix it is a small
        # fraction of the prompt - a live router call reported 59 fresh against 1,580
        # cache-read - so reading it alone understates the call by an order of
        # magnitude. All three are carried separately because all three are priced
        # differently.
        return {
            "tokens_in": int(getattr(usage, "input_tokens", 0) or 0),
            "tokens_out": int(getattr(usage, "output_tokens", 0) or 0),
            "cache_read_tokens": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
            "cache_write_tokens": int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
        }

    @staticmethod
    def _text(message: Any) -> str:
        return "".join(
            block.text for block in getattr(message, "content", []) if block.type == "text"
        )

    @staticmethod
    def _refused(message: Any) -> bool:
        return getattr(message, "stop_reason", None) == "refusal"

    # --- structured / non-streaming -------------------------------------
    async def complete(self, req: ModelRequest) -> ModelResult:
        message = await self._client.messages.create(**self._params(req))
        usage = self._usage(message, req)

        if self._refused(message):
            details = getattr(message, "stop_details", None)
            log(
                logger,
                logging.WARNING,
                "model_refusal",
                prompt_id=req.prompt_id,
                category=getattr(details, "category", None),
            )
            return ModelResult(model=req.model, degraded=True, **usage)

        text = self._text(message)
        if not text and getattr(message, "stop_reason", None) == "max_tokens":
            # The silent failure this file's docstring describes. Logged loudly
            # because every other signal looks like success.
            log(
                logger,
                logging.ERROR,
                "max_tokens_before_any_text",
                prompt_id=req.prompt_id,
                model=req.model,
                max_tokens=req.max_tokens,
                tokens_out=usage["tokens_out"],
            )
            return ModelResult(model=req.model, degraded=True, **usage)

        structured: dict | None = None
        if req.schema is not None:
            # output_config.format guarantees valid JSON in the first text block. A
            # parse failure here is a provider contract break, not user input, so it
            # degrades rather than raising into the turn.
            try:
                parsed = json.loads(text)
                structured = parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                log(
                    logger,
                    logging.ERROR,
                    "structured_output_unparseable",
                    prompt_id=req.prompt_id,
                )
                return ModelResult(model=req.model, text=text, degraded=True, **usage)

        return ModelResult(model=req.model, text=text, structured=structured, **usage)

    # --- streaming prose -------------------------------------------------
    async def stream(self, req: ModelRequest) -> AsyncIterator[ModelDelta | ModelResult]:
        params = self._params(req)
        if self._fallbacks:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
            stream_ctx = self._client.beta.messages.stream(**params)
        else:
            stream_ctx = self._client.messages.stream(**params)

        async with stream_ctx as stream:
            async for text in stream.text_stream:
                if text:
                    yield ModelDelta(text=text)
            message = await stream.get_final_message()

        usage = self._usage(message, req)
        if self._refused(message):
            log(logger, logging.WARNING, "model_refusal_stream", prompt_id=req.prompt_id)
            yield ModelResult(model=getattr(message, "model", req.model), degraded=True, **usage)
            return
        yield ModelResult(
            model=getattr(message, "model", req.model), text=self._text(message), **usage
        )
