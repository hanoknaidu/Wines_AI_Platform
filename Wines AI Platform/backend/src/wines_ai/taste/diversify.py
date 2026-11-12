"""Spread the result set across grape variety (FR-7).

Three Cabernets, a Malbec and a Syrah teaches the user something; five Cabernets does
not - and it hedges against one wrong inference.
"""

from __future__ import annotations

from .ranking import Scored


def _variety_key(variety: str) -> str:
    """'Chardonnay (oaked)' and 'Chardonnay (unoaked)' are one variety for diversity."""
    return variety.split("(")[0].strip().lower()


def diversify(scored: list[Scored], *, want: int, max_per_variety: int = 1) -> list[Scored]:
    """Greedy pass taking the best unseen variety first, then backfilling.

    Backfill matters: relaxing to a second row of an already-used variety is better
    than returning two results when five good matches exist. The spread is a
    preference, not a cap on the result count.
    """
    chosen: list[Scored] = []
    counts: dict[str, int] = {}

    for candidate in scored:
        key = _variety_key(candidate.row.variety)
        if counts.get(key, 0) >= max_per_variety:
            continue
        chosen.append(candidate)
        counts[key] = counts.get(key, 0) + 1
        if len(chosen) >= want:
            return chosen

    for candidate in scored:
        if candidate in chosen:
            continue
        chosen.append(candidate)
        if len(chosen) >= want:
            break
    return chosen


def variety_count(scored: list[Scored]) -> int:
    return len({_variety_key(s.row.variety) for s in scored})
