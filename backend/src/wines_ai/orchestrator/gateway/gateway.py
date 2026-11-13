"""Every model call in the system leaves through here.

Per-call timeout, bounded retry, circuit breaker, token and cost accounting, and the
per-turn cost ceiling - in one place, so no workflow can forget one of them. The
diagram draws this as a single box for exactly that reason.

## The per-turn ceiling is enforced here, not after the fact

`cost_ceiling_per_turn_usd` existed in config with nothing reading it, which made it a
number rather than a control: a runaway generator could spend any amount and the
ceiling would be noticed only in the transaction row afterwards. The ledger below is
per-turn and is checked BEFORE each call and again as streamed output accrues, so the
ceiling bounds spend rather than reporting it. Hitting it raises `BudgetExceeded`,
which the workflows treat the way they treat a verifier failure: degrade to templated
copy drawn from the row. A turn that costs too much degrades; it never errors.

## The breaker is per-process and fails open to the offline provider

A broken upstream must not turn into a queue of 30-second timeouts. After
`breaker_threshold` consecutive failures the gateway stops calling out for
`breaker_cooldown_seconds` and raises `ProviderDown` immediately; the orchestrated
engine's response to that is to fall back, so the product keeps working at $0.00.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from ...observability import METRICS, log
from ...pricing import cost_usd
from .types import ModelDelta, ModelProvider, ModelRequest, ModelResult, estimate_tokens

logger = logging.getLogger("wines_ai.gateway")


class GatewayError(RuntimeError):
    """Base for the two failures a caller is expected to handle."""


class ProviderDown(GatewayError):
    """The upstream failed every attempt, or the breaker is open."""


class BudgetExceeded(GatewayError):
    """This turn has spent its ceiling. Degrade; do not error the turn."""


@dataclass
class CallRecord:
    prompt_id: str
    model: str
    tokens_in: int
    tokens_out: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    latency_ms: int
    degraded: bool = False


@dataclass
class TurnLedger:
    """What this one turn has spent so far, and the ceiling it may not cross."""

    ceiling_usd: float
    calls: list[CallRecord] = field(default_factory=list)

    @property
    def spent_usd(self) -> float:
        return round(sum(c.cost_usd for c in self.calls), 8)

    @property
    def tokens_in(self) -> int:
        return sum(c.tokens_in for c in self.calls)

    @property
    def tokens_out(self) -> int:
        return sum(c.tokens_out for c in self.calls)

    @property
    def cache_read_tokens(self) -> int:
        return sum(c.cache_read_tokens for c in self.calls)

    @property
    def cache_write_tokens(self) -> int:
        return sum(c.cache_write_tokens for c in self.calls)

    @property
    def degraded(self) -> bool:
        return any(c.degraded for c in self.calls)

    def dominant_model(self) -> str | None:
        """The model that did the most expensive work this turn, or None if none did.

        `transaction_log.model` and the usage frame are one string, and naming the
        configured generator regardless of what ran is a lie a user can see: an
        interview turn answered by tapping a chip makes NO model call, and reporting
        `claude-sonnet-5-5` against 0 tokens and $0.00 invites exactly the wrong
        conclusion about where the money goes.
        """
        if not self.calls:
            return None
        return max(self.calls, key=lambda c: (c.cost_usd, c.tokens_out)).model

    def headroom_usd(self) -> float:
        return round(self.ceiling_usd - self.spent_usd, 8)

    def check(self, *, about_to_spend: float = 0.0) -> None:
        if self.spent_usd + about_to_spend > self.ceiling_usd:
            raise BudgetExceeded(
                f"turn ceiling ${self.ceiling_usd:.4f} would be exceeded "
                f"(spent ${self.spent_usd:.4f})"
            )

    def trace(self) -> list[dict]:
        return [
            {
                "prompt_id": c.prompt_id,
                "model": c.model,
                "tokens_in": c.tokens_in,
                "tokens_out": c.tokens_out,
                "cache_read": c.cache_read_tokens,
                "cache_write": c.cache_write_tokens,
                "cost_usd": c.cost_usd,
                "latency_ms": c.latency_ms,
                "degraded": c.degraded,
            }
            for c in self.calls
        ]


class _Breaker:
    def __init__(self, *, threshold: int, cooldown_seconds: float) -> None:
        self.threshold = threshold
        self.cooldown = cooldown_seconds
        self.failures = 0
        self.opened_at: float | None = None

    @property
    def open(self) -> bool:
        if self.opened_at is None:
            return False
        if time.monotonic() - self.opened_at >= self.cooldown:
            # Half-open: let the next call through and judge the upstream on it.
            self.opened_at = None
            self.failures = 0
            return False
        return True

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold and self.opened_at is None:
            self.opened_at = time.monotonic()
            METRICS.incr("gateway.breaker_open")
            log(logger, logging.ERROR, "gateway_breaker_open", failures=self.failures)


class ModelGateway:
    def __init__(
        self,
        provider: ModelProvider,
        *,
        timeout_seconds: float,
        max_attempts: int,
        breaker_threshold: int,
        breaker_cooldown_seconds: float,
        router: ModelProvider | None = None,
    ) -> None:
        self.provider = provider
        # Answers `route@N` requests when set (the LangChain router); `None` sends them
        # to `provider` like any other call. Only ever set alongside a provider that
        # calls out, so `free` below is decided by `provider` alone.
        self.router = router
        # A provider that never calls out never costs anything, whatever model id the
        # request names. Pricing the offline provider off `req.model` would bill a
        # free turn at Sonnet rates - which is not merely a cosmetic error: the
        # estimate is checked against the per-turn ceiling BEFORE each call, so a
        # free turn with a large packed context could refuse to run on budget it
        # was never going to spend.
        self.free = getattr(provider, "name", "") == "offline"
        self.timeout = timeout_seconds
        self.max_attempts = max_attempts
        self._breaker = _Breaker(
            threshold=breaker_threshold, cooldown_seconds=breaker_cooldown_seconds
        )

    @property
    def provider_name(self) -> str:
        return self.provider.name

    # --- non-streaming ---------------------------------------------------
    async def complete(self, req: ModelRequest, ledger: TurnLedger) -> ModelResult:
        req.validate_cache_order()
        # Priced on the estimate before the call, so a prompt that cannot afford to run
        # never runs. The real counts replace the estimate immediately afterwards.
        ledger.check(about_to_spend=self._estimate_cost(req))
        started = time.monotonic()
        result = await self._attempt(lambda: self.provider.complete(req), req)
        self._record(ledger, req, result, started)
        return result

    async def complete_route(self, req: ModelRequest, ledger: TurnLedger) -> ModelResult:
        """The router's call. Same pre-call ceiling, retry, breaker and cost record as
        `complete()` - only the object that answers differs.

        The breaker is shared with every other call: one upstream, one breaker. A
        routing call failing against an Anthropic outage is evidence about the same
        upstream the generator is about to call.
        """
        if self.router is None:
            return await self.complete(req, ledger)
        req.validate_cache_order()
        ledger.check(about_to_spend=self._estimate_cost(req))
        started = time.monotonic()
        router = self.router
        result = await self._attempt(lambda: router.complete(req), req)
        self._record(ledger, req, result, started)
        return result

    # --- streaming -------------------------------------------------------
    async def stream(
        self, req: ModelRequest, ledger: TurnLedger
    ) -> AsyncIterator[ModelDelta | ModelResult]:
        """Yields deltas as they arrive, then one terminal ModelResult.

        The ceiling is re-checked as output accrues: a generator that runs away is
        stopped mid-stream rather than after it has finished spending. The partial
        text already yielded stays - the caller has streamed it to a client and
        retracting it would be worse than a short answer.
        """
        req.validate_cache_order()
        ledger.check(about_to_spend=self._estimate_cost(req))
        if self._breaker.open:
            raise ProviderDown(f"{self.provider.name} breaker is open")

        started = time.monotonic()
        produced = 0
        terminal: ModelResult | None = None
        try:
            async for item in self.provider.stream(req):
                if isinstance(item, ModelResult):
                    terminal = item
                    break
                produced += estimate_tokens(item.text)
                # Cheap arithmetic per chunk; the alternative is finding out afterwards.
                running = self._price(req.model, req.prompt_tokens(), produced)
                if ledger.spent_usd + running > ledger.ceiling_usd:
                    self._record_partial(ledger, req, produced, started)
                    raise BudgetExceeded(
                        f"generator stopped mid-stream at turn ceiling "
                        f"${ledger.ceiling_usd:.4f}"
                    )
                yield item
        except BudgetExceeded:
            raise
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            METRICS.incr("gateway.stream_failed")
            raise ProviderDown(f"{self.provider.name} stream failed: {exc!r}") from exc

        self._breaker.record_success()
        if terminal is None:
            terminal = ModelResult(model=req.model, tokens_out=produced)
        self._record(ledger, req, terminal, started)
        yield terminal

    # --- internals -------------------------------------------------------
    async def _attempt(self, call, req: ModelRequest) -> ModelResult:
        if self._breaker.open:
            raise ProviderDown(f"{self.provider.name} breaker is open")

        last: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                result = await asyncio.wait_for(call(), timeout=self.timeout)
                self._breaker.record_success()
                return result
            # TimeoutError is an Exception subclass; CancelledError is not, so a
            # cancelled turn propagates instead of being retried.
            except Exception as exc:  # noqa: BLE001
                last = exc
                self._breaker.record_failure()
                METRICS.incr("gateway.attempt_failed")
                log(
                    logger,
                    logging.WARNING,
                    "gateway_attempt_failed",
                    prompt_id=req.prompt_id,
                    model=req.model,
                    attempt=attempt,
                    error=repr(exc),
                )
                if attempt == self.max_attempts or self._breaker.open:
                    break
                # Exponential backoff with jitter: a retried storm is how one slow
                # upstream becomes an outage.
                await asyncio.sleep(min(2.0, 0.2 * 2 ** (attempt - 1)) * (0.5 + random.random()))
        raise ProviderDown(f"{self.provider.name} failed after {self.max_attempts}: {last!r}")

    def estimate_cost(self, req: ModelRequest) -> float:
        """Worst-case cost of this call, from the prompt size and `max_tokens`.

        Public because a caller that fans several calls out concurrently has to bound
        the whole fan-out before launching it: each call's own pre-check reads the
        ledger before its siblings have recorded anything, so N concurrent calls would
        each see the same headroom and the ceiling would hold N times over.
        """
        return self._price(req.model, req.prompt_tokens(), req.max_tokens)

    def _estimate_cost(self, req: ModelRequest) -> float:
        return self.estimate_cost(req)

    def _price(self, model: str, tokens_in: int, tokens_out: int) -> float:
        if self.free:
            return 0.0
        return cost_usd(model, tokens_in=tokens_in, tokens_out=tokens_out)

    def _record(
        self, ledger: TurnLedger, req: ModelRequest, result: ModelResult, started: float
    ) -> None:
        cost = (
            0.0
            if self.free
            else cost_usd(
                result.model or req.model,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                cache_read_tokens=result.cache_read_tokens,
                cache_write_tokens=result.cache_write_tokens,
            )
        )
        ledger.calls.append(
            CallRecord(
                prompt_id=req.prompt_id,
                model=result.model or req.model,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                cache_read_tokens=result.cache_read_tokens,
                cache_write_tokens=result.cache_write_tokens,
                cost_usd=cost,
                latency_ms=int((time.monotonic() - started) * 1000),
                degraded=result.degraded,
            )
        )
        METRICS.incr(f"gateway.call.{req.prompt_id or 'unknown'}")
        METRICS.observe("gateway.call_ms", (time.monotonic() - started) * 1000)

    def _record_partial(
        self, ledger: TurnLedger, req: ModelRequest, tokens_out: int, started: float
    ) -> None:
        """Account for a stream we cut off. Tokens produced were still billed."""
        tokens_in = req.prompt_tokens()
        ledger.calls.append(
            CallRecord(
                prompt_id=req.prompt_id,
                model=req.model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cache_read_tokens=0,
                cache_write_tokens=0,
                cost_usd=self._price(req.model, tokens_in, tokens_out),
                latency_ms=int((time.monotonic() - started) * 1000),
                degraded=True,
            )
        )
