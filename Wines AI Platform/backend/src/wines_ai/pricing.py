"""Model pricing, so `cost_usd` in transaction_log is computed rather than guessed.

Rates are USD per million tokens, from the Anthropic pricing reference (cached
2026-10-06; cache-read rates re-checked 2026-11-11). The `offline` provider costs
$0.00 and still writes a transaction row, so the accounting path is exercised before
it becomes expensive to find it wrong - which is how the cache-read gap below was
found, by comparing a live response against what this file charged for it.

Two cost facts worth keeping visible here rather than in a comment somewhere else:

* Haiku 5.5 is tier-priced. The $0.10 / $0.50 rates apply to prompts up to 100K
  tokens; beyond that it is $0.50 / $2.50, a 5x jump on input. The router, rewriter
  and verifier run on Haiku and must stay under that line, which is what
  `context_token_budget` (8K) is for.
* A cache read on Sonnet 5.5 costs $0.20/MTok against $2.00 for fresh input - 10x.
  That is why the prompt registry's cache-stable prefix ordering (instructions first,
  per-turn content last) is a cost requirement and not a style preference.
"""

from __future__ import annotations

from dataclasses import dataclass

# Batch API runs asynchronously at 50% cost. Band 4's offline authoring pass is the
# natural user of this; nothing in the request path can use it.
BATCH_DISCOUNT = 0.50

# Cache writes cost more than fresh input: ~1.25x the base input rate for the default
# 5-minute TTL, per the Anthropic prompt-caching documentation (read 2026-11-11). This
# is now used for billing - lane 3 writes caches on every cold prefix, and a cache
# write that costs nothing in our accounting is a turn that under-reports its own bill.
CACHE_WRITE_MULTIPLIER = 1.25


@dataclass(frozen=True)
class Rate:
    """USD per million tokens."""

    input: float
    output: float
    cache_read: float | None = None
    # Prompt size above which the tier rates below apply (Haiku 5.5 only).
    tier_break_tokens: int | None = None
    tier_input: float | None = None
    tier_output: float | None = None


RATES: dict[str, Rate] = {
    "claude-haiku-5-5": Rate(
        input=0.10,
        output=0.50,
        tier_break_tokens=100_000,
        tier_input=0.50,
        tier_output=2.50,
    ),
    # Sonnet 5.5 reads cache at $0.10/MTok - half the Opus rate, and 20x cheaper
    # than its own fresh input. The generator is the only call that carries a
    # prompt worth caching, so this is the rate the prefix ordering is for.
    "claude-sonnet-5-5": Rate(input=2.00, output=10.00, cache_read=0.10),
    "claude-opus-5-5": Rate(input=4.00, output=20.00, cache_read=0.20),
    # The free ones. Present so cost accounting has no special case: `deterministic`
    # is lane 2, `offline` is lane 3 running its whole pipeline with no provider.
    "deterministic": Rate(input=0.0, output=0.0, cache_read=0.0),
    "offline": Rate(input=0.0, output=0.0, cache_read=0.0),
    # A turn that called no model - a chip-answered interview, for instance. Named so
    # the usage frame can say so, and priced so nothing has to special-case it.
    "none": Rate(input=0.0, output=0.0, cache_read=0.0),
}


def cost_usd(
    model: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    *,
    batch: bool = False,
) -> float:
    """Cost of one call. Unknown models cost 0.0 and are logged by the caller.

    Returning 0.0 for an unknown model rather than raising is deliberate: a pricing
    gap must not be able to fail a user's turn.

    **A missing cache-read rate charges the full input rate, not zero.** Found by
    reading a live response: a Haiku router call reported 1,580 cache-read tokens and
    59 fresh ones, and because `RATES["claude-haiku-5-5"].cache_read` was None, the
    cached 96% of that prompt was billed at $0.00 in our own accounting. A ceiling is
    only a ceiling if it cannot under-report, so an unrated cache read is treated as
    ordinary input - deliberately pessimistic, and wrong in the safe direction until
    the rate is pinned.
    """
    rate = RATES.get(model)
    if rate is None:
        return 0.0

    rate_in, rate_out = rate.input, rate.output
    if rate.tier_break_tokens is not None and tokens_in > rate.tier_break_tokens:
        rate_in = rate.tier_input or rate_in
        rate_out = rate.tier_output or rate_out

    total = (tokens_in / 1_000_000) * rate_in + (tokens_out / 1_000_000) * rate_out
    if cache_read_tokens:
        read_rate = rate.cache_read if rate.cache_read is not None else rate_in
        total += (cache_read_tokens / 1_000_000) * read_rate
    if cache_write_tokens:
        total += (cache_write_tokens / 1_000_000) * rate_in * CACHE_WRITE_MULTIPLIER

    if batch:
        total *= BATCH_DISCOUNT
    return round(total, 8)
