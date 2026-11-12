"""Style hard filter, then weighted distance across the axes.

This is BRD v1.1's serving path: the architecture's Phase-1 engine is not a
placeholder, it is the product the BRD originally specified.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..dataset.schema import WineRow
from .axes import AXES_BY_ID, SCORED_AXES, level_index


@dataclass
class Scored:
    row: WineRow
    distance: float
    per_axis: dict[str, float]

    @property
    def score(self) -> float:
        # Reported as a similarity so higher is better in logs and in MMR.
        return round(1.0 / (1.0 + self.distance), 6)


def _axis_distance(axis_id: str, target: str, actual: str) -> float | None:
    t, a = level_index(axis_id, target), level_index(axis_id, actual)
    if t is None or a is None:
        return None
    span = max(1, len(AXES_BY_ID[axis_id].levels) - 1)
    return abs(t - a) / span


def rank(rows: list[WineRow], profile: dict) -> list[Scored]:
    """Weighted L1 distance over the axes the profile actually specifies.

    Unspecified axes are skipped rather than defaulted - a default would invent a
    preference the user never expressed and then rank on it.
    """
    scored: list[Scored] = []
    for row in rows:
        total = 0.0
        weight_sum = 0.0
        per_axis: dict[str, float] = {}
        for axis in SCORED_AXES:
            target = profile.get(axis.id)
            if target is None:
                continue
            actual = getattr(row, axis.id, None)
            if actual is None:
                continue
            d = _axis_distance(axis.id, target, actual)
            if d is None:
                continue
            per_axis[axis.id] = round(d, 4)
            total += d * axis.weight
            weight_sum += axis.weight
        distance = total / weight_sum if weight_sum else 1.0
        scored.append(Scored(row=row, distance=round(distance, 6), per_axis=per_axis))

    # Ties broken by row_id so identical answers always produce identical output.
    scored.sort(key=lambda s: (s.distance, s.row.row_id))
    return scored


def hard_filter(rows: list[WineRow], profile: dict) -> list[WineRow]:
    """Style is a hard pre-filter (FR-2). Nothing else is."""
    style = profile.get("style")
    if style is None:
        return list(rows)
    return [row for row in rows if row.style == style]


def within_sweetness_tolerance(scored: list[Scored], profile: dict, tolerance: int) -> list[Scored]:
    """Drop candidates whose sweetness is further than `tolerance` levels away.

    Not folded into the distance score on purpose: a weighted average can always be
    dragged back under a threshold by other axes agreeing, and no amount of agreement
    about body makes a sweet wine an answer to "not sweet at all".
    """
    target = profile.get("sweetness")
    if target is None:
        return scored
    t = level_index("sweetness", target)
    if t is None:
        return scored
    keep = []
    for item in scored:
        a = level_index("sweetness", item.row.sweetness)
        if a is not None and abs(a - t) <= tolerance:
            keep.append(item)
    return keep
