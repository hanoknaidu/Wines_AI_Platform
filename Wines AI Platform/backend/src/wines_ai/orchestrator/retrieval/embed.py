"""The embedder seam, and a local embedder that needs no model weights.

The diagram specifies a 384-d bi-encoder. Installing one means `torch` plus
`sentence-transformers` - roughly 2 GB of wheels - to embed a corpus of 45 rows that a
brute-force scan reads in under a millisecond. That trade is wrong at this corpus size,
and it is the reason the base install stays small enough to boot anywhere.

So `Embedder` is a protocol with two implementations in mind:

* `HashingEmbedder` (here): deterministic, dependency-free, built from character
  n-grams and word unigrams hashed into a fixed-width vector with signed buckets.
  Catches paraphrase and morphological variation ("buttery" ~ "butter", "oaked" ~
  "oak") because the n-grams overlap, which is most of what the dense side is for in a
  corpus of tasting notes. It does NOT catch taste-adjacency between unrelated words
  ("jammy" ~ "fruit-forward") - that is what stage C's vocabulary expansion is for,
  and why that stage is not optional in this configuration.
* a real bi-encoder, dropped in behind the same protocol when the corpus grows past
  the point where this is honest.

Writing the weaker embedder down with its limits named is the honest version of a
choice everyone makes at this corpus size and few state. `index_kind` reports which
one is loaded, and /readyz serves it, so nobody has to guess from the behaviour.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol, runtime_checkable

_WORD = re.compile(r"[a-z0-9']+")


@runtime_checkable
class Embedder(Protocol):
    dim: int
    kind: str

    def encode(self, text: str) -> list[float]: ...


def _features(text: str) -> list[str]:
    lowered = text.lower()
    words = _WORD.findall(lowered)
    feats: list[str] = list(words)
    # Character 4-grams inside each word: the cheap source of morphological
    # robustness. "oaky"/"oaked"/"oak" share buckets without a stemmer.
    for word in words:
        if len(word) <= 4:
            continue
        for i in range(len(word) - 3):
            feats.append(f"#{word[i : i + 4]}")
    # Word bigrams: "not sweet" must not look like "sweet".
    for a, b in zip(words, words[1:], strict=False):
        feats.append(f"{a}_{b}")
    return feats


class HashingEmbedder:
    kind = "hashing-ngram"

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def encode(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for feature in _features(text):
            digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
            value = int.from_bytes(digest, "big")
            bucket = value % self.dim
            # Signed buckets: collisions cancel on average instead of accumulating.
            sign = 1.0 if (value >> 63) & 1 else -1.0
            vector[bucket] += sign
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:
            return vector
        return [v / norm for v in vector]


def cosine(a: list[float], b: list[float]) -> float:
    """Both sides are unit-normalised by `encode`, so this is a dot product."""
    return sum(x * y for x, y in zip(a, b, strict=False))
