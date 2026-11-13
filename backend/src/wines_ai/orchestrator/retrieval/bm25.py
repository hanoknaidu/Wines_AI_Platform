"""BM25 over the tasting notes - the sparse side (stage E2).

The diagram specifies SQLite FTS5. FTS5 is the right answer when the corpus is large
enough that an in-process index would not fit, and it is the wrong answer here for the
same reason the vector database is: it would put the ranking function inside SQLite,
where it cannot be inspected, tested, or scored against the eval set without a
database round trip per query.

This is the same ranking function - Okapi BM25 with the standard k1=1.5, b=0.75 - over
the same fields, built at startup from the frozen artifact. It catches the exact
varietal, producer and region terms that the dense side blurs, which is the entire
reason the hybrid has a sparse arm.

Swapping in FTS5 later means replacing `search()` and nothing else.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

_WORD = re.compile(r"[a-z0-9']+")

K1 = 1.5
B = 0.75

# Light stemming: enough to make "oaked"/"oaky"/"oak" and "berries"/"berry" collide,
# with no dependency. Deliberately not Porter - the long tail of a tasting-note
# vocabulary is small, and an aggressive stemmer conflates "fruity" with "fruit" in
# ways that matter less than it breaks "savoury".
def _stem(word: str) -> str:
    for suffix in ("iness", "ness", "ies", "ied", "ing", "ed", "es", "s", "y"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def tokenize(text: str) -> list[str]:
    return [_stem(w) for w in _WORD.findall(text.lower())]


@dataclass
class Bm25Index:
    doc_ids: list[str] = field(default_factory=list)
    lengths: dict[str, int] = field(default_factory=dict)
    term_freqs: dict[str, Counter] = field(default_factory=dict)
    doc_freqs: Counter = field(default_factory=Counter)
    avg_length: float = 0.0

    @property
    def size(self) -> int:
        return len(self.doc_ids)

    def add(self, doc_id: str, text: str) -> None:
        tokens = tokenize(text)
        counts = Counter(tokens)
        self.doc_ids.append(doc_id)
        self.lengths[doc_id] = len(tokens)
        self.term_freqs[doc_id] = counts
        for term in counts:
            self.doc_freqs[term] += 1

    def finalize(self) -> None:
        total = sum(self.lengths.values())
        self.avg_length = (total / len(self.doc_ids)) if self.doc_ids else 0.0

    def search(self, query: str, *, k: int) -> list[tuple[str, float]]:
        terms = tokenize(query)
        if not terms or not self.doc_ids:
            return []
        n = len(self.doc_ids)
        scored: list[tuple[str, float]] = []
        for doc_id in self.doc_ids:
            counts = self.term_freqs[doc_id]
            length = self.lengths[doc_id] or 1
            score = 0.0
            for term in terms:
                tf = counts.get(term, 0)
                if tf == 0:
                    continue
                df = self.doc_freqs.get(term, 0) or 1
                # The +0.5 smoothing is what keeps a term present in most documents
                # from going negative and inverting the ranking.
                idf = math.log(1.0 + (n - df + 0.5) / (df + 0.5))
                denom = tf + K1 * (1 - B + B * length / (self.avg_length or 1))
                score += idf * (tf * (K1 + 1)) / denom
            if score > 0:
                scored.append((doc_id, round(score, 6)))
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored[:k]
