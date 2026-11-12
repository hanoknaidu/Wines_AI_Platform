"""Parse a refine delta and move exactly one axis.

Anchored to the previous result set: the correction re-ranks what the user actually
saw plus a widened candidate set. It never re-interviews (FR-8).
"""

from __future__ import annotations

from .axes import AXES_BY_ID, REFINE_BY_ID, REFINE_CHIPS, level_at, level_index

# Free-text equivalents of the chips, longest-match first.
_PHRASES: tuple[tuple[str, str], ...] = (
    ("less sweet", "less_sweet"),
    ("not so sweet", "less_sweet"),
    ("too sweet", "less_sweet"),
    ("drier", "less_sweet"),
    ("sweeter", "sweeter"),
    ("more sweet", "sweeter"),
    ("not sweet enough", "sweeter"),
    ("lighter", "lighter"),
    ("less heavy", "lighter"),
    ("too heavy", "lighter"),
    ("bolder", "bolder"),
    ("richer", "bolder"),
    ("fuller", "bolder"),
    ("heavier", "bolder"),
    ("smoother", "smoother"),
    ("less grippy", "smoother"),
    ("too tannic", "smoother"),
    ("less oaky", "less_oaky"),
    ("less oak", "less_oaky"),
    ("too oaky", "less_oaky"),
    ("more fruit", "more_fruit"),
    ("fruitier", "more_fruit"),
    ("more earthy", "more_earthy"),
    ("earthier", "more_earthy"),
    ("more savoury", "more_earthy"),
    ("more savory", "more_earthy"),
)


def detect(text: str, chip_id: str | None = None) -> dict | None:
    """Return the refine chip spec this turn means, or None."""
    if chip_id and chip_id in REFINE_BY_ID:
        return REFINE_BY_ID[chip_id]
    lowered = text.lower()
    best: tuple[int, str] | None = None
    for phrase, chip in _PHRASES:
        if phrase in lowered and (best is None or len(phrase) > best[0]):
            best = (len(phrase), chip)
    return REFINE_BY_ID[best[1]] if best else None


def apply(profile: dict, chip: dict) -> tuple[dict, str | None]:
    """Move one axis one step. Returns (patch, reason-it-could-not-move)."""
    axis_id = chip["axis"]
    axis = AXES_BY_ID.get(axis_id)
    if axis is None:
        return {}, f"unknown axis {axis_id}"

    style = profile.get("style")
    if style is not None and style not in axis.applies_to:
        return {}, f"{axis_id} does not apply to {style}"

    current = profile.get(axis_id)
    if current is None:
        # The axis was never asked (tannin, acidity, fruit/savoury). Start from the
        # middle so the delta has somewhere to move from.
        idx = len(axis.levels) // 2
    else:
        idx = level_index(axis_id, current)
        if idx is None:
            idx = len(axis.levels) // 2

    target_idx = idx + chip["delta"]
    if target_idx < 0 or target_idx > len(axis.levels) - 1:
        return {}, f"already at the {'lowest' if target_idx < 0 else 'highest'} {axis_id}"

    new_value = level_at(axis_id, target_idx)
    return {axis_id: new_value}, None


def chips_payload() -> list[dict]:
    return [{"id": c["id"], "label": c["label"]} for c in REFINE_CHIPS]
