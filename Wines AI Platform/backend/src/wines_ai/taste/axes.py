"""The seven axes, their levels, and the consumer-language labels.

This module is the single source of truth for vocabulary. It is served over
/meta/taste-axes so no wine word is ever hardcoded in the frontend.

Two product rules are enforced here rather than left to prose:
  * the word "dry" never appears in a user-facing label (BRD section 3 - it is the most
    misused word in consumer wine language), and
  * every question is phrased as a physical sensation, not a wine term.
A unit test asserts the first of those against this table.
"""

from __future__ import annotations

from dataclasses import dataclass, field

STYLES = ("red", "white", "rose", "sparkling", "dessert")

STYLE_LABELS = {
    "red": "Red",
    "white": "White",
    "rose": "Rosé",
    "sparkling": "Sparkling",
    "dessert": "Something sweet for dessert",
}


@dataclass(frozen=True)
class Level:
    value: str
    label: str
    hedged_label: str


@dataclass(frozen=True)
class Axis:
    id: str
    asked: bool
    levels: tuple[Level, ...]
    question_order: int | None = None
    prompt: str | None = None
    applies_to: tuple[str, ...] = field(default=STYLES)
    weight: float = 1.0


# Ordering within `levels` is meaningful: it is the scale refine deltas move along.
AXES: tuple[Axis, ...] = (
    Axis(
        id="style",
        asked=True,
        question_order=1,
        prompt="What are you in the mood for?",
        weight=0.0,  # a hard filter, never a distance term
        levels=tuple(Level(s, STYLE_LABELS[s], STYLE_LABELS[s]) for s in STYLES),
    ),
    Axis(
        id="sweetness",
        asked=True,
        question_order=2,
        prompt="How sweet?",
        # Heaviest weight: sweetness mismatch is the one error a novice notices instantly.
        weight=3.0,
        levels=(
            Level("dry", "Not sweet at all", "probably not sweet"),
            Level("off_dry", "Just a hint of sweetness", "maybe a hint of sweetness"),
            Level("sweet", "Properly sweet", "likely sweet"),
        ),
    ),
    Axis(
        id="body",
        asked=True,
        question_order=3,
        prompt="How heavy should it feel?",
        applies_to=("red",),
        weight=1.5,
        levels=(
            Level("light", "Light and easy", "probably light"),
            Level("medium", "In the middle", "probably medium-bodied"),
            Level("full", "Rich and bold", "likely full-bodied"),
        ),
    ),
    Axis(
        id="oak",
        asked=True,
        question_order=3,
        prompt="Crisp or rounded?",
        applies_to=("white", "rose", "sparkling"),
        weight=1.5,
        levels=(
            Level("none", "Clean and crisp", "probably crisp"),
            Level("subtle", "In the middle", "lightly rounded"),
            Level("pronounced", "Rounded and buttery", "likely buttery"),
        ),
    ),
    # The four unasked axes: the vocabulary of refine, the driver of diversity, and
    # the source of the "what it tastes like" copy.
    Axis(
        id="tannin",
        asked=False,
        applies_to=("red",),
        weight=1.0,
        levels=(
            Level("smooth", "smooth", "probably smooth"),
            Level("moderate", "some grip", "some grip"),
            Level("grippy", "firm and grippy", "likely grippy"),
        ),
    ),
    Axis(
        id="acidity",
        asked=False,
        weight=1.0,
        levels=(
            Level("soft", "soft", "probably soft"),
            Level("fresh", "fresh", "fresh"),
            Level("racy", "zippy and sharp", "likely sharp"),
        ),
    ),
    Axis(
        id="fruit_savoury",
        asked=False,
        weight=1.0,
        levels=(
            Level("fruit_forward", "fruity", "probably fruity"),
            Level("balanced", "balanced", "balanced"),
            Level("earthy", "earthy and savoury", "likely earthy"),
        ),
    ),
)

AXES_BY_ID = {axis.id: axis for axis in AXES}
SCORED_AXES = tuple(a for a in AXES if a.weight > 0)

# Refine chips. `delta` moves the profile one step along the axis's level ordering.
REFINE_CHIPS: tuple[dict, ...] = (
    {"id": "less_sweet", "label": "less sweet", "axis": "sweetness", "delta": -1},
    {"id": "sweeter", "label": "sweeter", "axis": "sweetness", "delta": 1},
    {"id": "lighter", "label": "lighter", "axis": "body", "delta": -1},
    {"id": "bolder", "label": "bolder", "axis": "body", "delta": 1},
    {"id": "smoother", "label": "smoother", "axis": "tannin", "delta": -1},
    {"id": "less_oaky", "label": "less oaky", "axis": "oak", "delta": -1},
    {"id": "more_fruit", "label": "more fruit", "axis": "fruit_savoury", "delta": -1},
    {"id": "more_earthy", "label": "more earthy", "axis": "fruit_savoury", "delta": 1},
)

REFINE_BY_ID = {chip["id"]: chip for chip in REFINE_CHIPS}


def level_index(axis_id: str, value: str | None) -> int | None:
    axis = AXES_BY_ID.get(axis_id)
    if axis is None or value is None:
        return None
    for idx, level in enumerate(axis.levels):
        if level.value == value:
            return idx
    return None


def level_at(axis_id: str, index: int) -> str | None:
    axis = AXES_BY_ID.get(axis_id)
    if axis is None:
        return None
    index = max(0, min(len(axis.levels) - 1, index))
    return axis.levels[index].value


def applies(axis_id: str, style: str | None) -> bool:
    axis = AXES_BY_ID.get(axis_id)
    if axis is None:
        return False
    if style is None:
        return True
    return style in axis.applies_to


def label_for(axis_id: str, value: str, confidence: float, threshold: float) -> str:
    """'likely dry' is not 'dry'. The hedge is decided here, not in the frontend."""
    axis = AXES_BY_ID.get(axis_id)
    if axis is None:
        return value
    for level in axis.levels:
        if level.value == value:
            return level.label if confidence >= threshold else level.hedged_label
    return value


def asked_axis_for_style(style: str | None) -> list[Axis]:
    """The axes actually asked for a style, in question order.

    Dessert gets style + sweetness only: FR-4 skips the third question entirely,
    because style and sweetness are already enough.
    """
    out = []
    for axis in AXES:
        if not axis.asked:
            continue
        if style is not None and style not in axis.applies_to:
            continue
        out.append(axis)
    return sorted(out, key=lambda a: a.question_order or 99)
