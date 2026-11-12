"""The type universe at the model boundary.

One request shape, one result shape, two providers. Everything above this file is
written against these types and never against a vendor SDK, which is what makes
`offline` and `anthropic` interchangeable and what makes the whole A-to-K pipeline
testable with no key and no network.

## Why prompts are a list of blocks rather than a string

Prompt caching is the single largest cost lever in this lane: a cache read on Sonnet
costs $0.20/MTok against $2.00 for fresh input. The cache keys on a byte-exact
PREFIX, so the ordering rule - instructions first, per-turn content last - has to be
structural rather than a convention someone remembers. `Block.cacheable` marks the
stable prefix; `ModelRequest.validate_cache_order()` refuses a request that puts a
per-turn block before a cacheable one, so the ordering cannot silently regress and
quietly triple the input bill.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# ~4 characters per token is the standard English approximation. Used for budget
# enforcement only - never for billing, which reads the real counts off the response.
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN)


@dataclass(frozen=True)
class Block:
    """One span of a prompt.

    `cacheable` means "identical on every turn": the instruction preamble, the axis
    vocabulary, the output contract. A block carrying this turn's utterance or this
    turn's retrieved rows is not cacheable and must sort after every block that is.
    """

    text: str
    cacheable: bool = False
    label: str = ""


@dataclass
class ModelRequest:
    model: str
    system: list[Block] = field(default_factory=list)
    user: list[Block] = field(default_factory=list)
    max_tokens: int = 1024
    # `effort` replaces the sampling knobs. temperature / top_p / top_k are REJECTED
    # with a 400 on every current Claude model, so a request shape carrying
    # `temperature=0` would be a 400 waiting to happen rather than a determinism
    # setting. Determinism on the structured calls comes from the JSON schema;
    # thoroughness is bought with effort, and the cheap high-volume calls buy none.
    effort: str = "low"
    # Set for a structured call. The provider is responsible for returning JSON that
    # parses; a structured call that cannot parse is a provider failure, not a caller
    # problem, which is the whole point of asking for structure.
    schema: dict | None = None
    # Names the prompt + version that produced this request, for the trace.
    prompt_id: str = ""

    def validate_cache_order(self) -> None:
        for blocks in (self.system, self.user):
            seen_volatile = False
            for block in blocks:
                if not block.cacheable:
                    seen_volatile = True
                elif seen_volatile:
                    raise ValueError(
                        f"{self.prompt_id or self.model}: cacheable block "
                        f"{block.label!r} follows a per-turn block; the cache prefix "
                        "must be byte-stable, so instructions come first and per-turn "
                        "content last"
                    )

    def prompt_tokens(self) -> int:
        return sum(estimate_tokens(b.text) for b in (*self.system, *self.user))


@dataclass
class ModelDelta:
    """A streamed fragment of prose."""

    text: str


@dataclass
class ModelResult:
    model: str
    text: str = ""
    structured: dict | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read_tokens: int = 0
    # Tokens written to the cache on a cold prefix. Billed at ~1.25x input, so a
    # provider that does not report them makes every first turn look cheaper than it
    # was - and the first turn is the one that writes the cache.
    cache_write_tokens: int = 0
    # True when the answer came from the provider's own degraded path rather than a
    # model. Surfaces in the trace so a turn that silently fell back is visible.
    degraded: bool = False


@runtime_checkable
class ModelProvider(Protocol):
    name: str

    async def complete(self, req: ModelRequest) -> ModelResult: ...

    def stream(self, req: ModelRequest) -> AsyncIterator[ModelDelta | ModelResult]:
        """Yields deltas, then exactly one terminal ModelResult carrying the usage."""
        ...
