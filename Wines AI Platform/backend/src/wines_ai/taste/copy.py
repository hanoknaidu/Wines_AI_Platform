"""User-facing copy, composed from the row and the user's own selections.

Every string here is templated from dataset fields. Nothing is generated, so nothing
can be invented - which is what makes the Phase-1 engine safe to ship with no
verifier behind it.
"""

from __future__ import annotations

from ..dataset.schema import WineRow
from .axes import AXES_BY_ID, label_for

# "why it matches" is phrased in the words the user chose (FR-6), so the explanation
# uses the asked level's consumer label, never the wine term.
_MATCH_PHRASES = {
    ("sweetness", "dry"): "you asked for nothing sweet, and this is not sweet",
    ("sweetness", "off_dry"): "you asked for just a hint of sweetness, and this has one",
    ("sweetness", "sweet"): "you asked for properly sweet, and this is",
    ("body", "light"): "you wanted light and easy, and this is a light-bodied wine",
    ("body", "medium"): "you wanted something in the middle, and this sits there",
    ("body", "full"): "you wanted rich and bold, and this is full-bodied",
    ("oak", "none"): "you wanted clean and crisp, and this sees no oak",
    ("oak", "subtle"): "you wanted something in the middle, and the oak here is light",
    ("oak", "pronounced"): "you wanted rounded and buttery, and this is oak-aged",
}

_NEAR_MISS = {
    "sweetness": "it is a touch {direction} than you asked for",
    "body": "it is a little {direction} than you asked for",
    "oak": "the oak is a little {direction} than you asked for",
}

_DIRECTION = {
    ("sweetness", -1): "drier", ("sweetness", 1): "sweeter",
    ("body", -1): "lighter", ("body", 1): "fuller",
    ("oak", -1): "crisper", ("oak", 1): "more oaky",
}


def axis_readings(row: WineRow, threshold: float) -> dict[str, dict]:
    """The per-axis block on a card, with the hedge already applied."""
    out: dict[str, dict] = {}
    for axis_id in ("sweetness", "body", "oak", "tannin", "acidity", "fruit_savoury"):
        axis = AXES_BY_ID[axis_id]
        if row.style not in axis.applies_to:
            continue
        value = getattr(row, axis_id, None)
        if value is None:
            continue
        confidence = row.confidence_for(axis_id)
        out[axis_id] = {
            "value": value,
            "confidence": round(confidence, 3),
            "label": label_for(axis_id, value, confidence, threshold),
        }
    return out


def why_it_matches(
    row: WineRow, profile: dict, per_axis: dict[str, float], threshold: float
) -> str:
    """Explain the match in the user's terms, and name the gap where there is one."""
    from .axes import level_index

    hits: list[str] = []
    misses: list[str] = []
    for axis_id in ("sweetness", "body", "oak"):
        target = profile.get(axis_id)
        if target is None:
            continue
        actual = getattr(row, axis_id, None)
        if actual is None:
            continue
        if actual == target:
            phrase = _MATCH_PHRASES.get((axis_id, target))
            if phrase:
                hits.append(phrase)
        else:
            t, a = level_index(axis_id, target), level_index(axis_id, actual)
            if t is None or a is None:
                continue
            direction = _DIRECTION.get((axis_id, 1 if a > t else -1))
            template = _NEAR_MISS.get(axis_id)
            if direction and template:
                misses.append(template.format(direction=direction))

    parts: list[str] = []
    if hits:
        parts.append(_join(hits).capitalize() + ".")
    if misses:
        parts.append(_join(misses).capitalize() + ".")
    if not parts:
        parts.append("This is the closest match in the dataset to what you described.")

    # An honest hedge where an axis the user asked about is low-confidence.
    low = [
        axis_id
        for axis_id in ("sweetness", "body", "oak")
        if profile.get(axis_id) is not None
        and getattr(row, axis_id, None) is not None
        and row.confidence_for(axis_id) < threshold
    ]
    if low:
        names = _join([axis_id.replace("_", " ") for axis_id in low])
        parts.append(f"Worth knowing: the {names} reading on this row is less certain.")
    return " ".join(parts)


def tastes_like(row: WineRow) -> str:
    """Straight from the row's description field. Never rewritten."""
    return row.description


def empty_state(profile: dict) -> str:
    """FR-13: say so honestly rather than silently relaxing the filters."""
    style = profile.get("style")
    sweetness = profile.get("sweetness")
    style_label = AXES_BY_ID["style"].levels
    style_name = next(
        (level.label.lower() for level in style_label if level.value == style), str(style)
    )
    sweet_name = next(
        (
            level.label.lower()
            for level in AXES_BY_ID["sweetness"].levels
            if level.value == sweetness
        ),
        str(sweetness),
    )
    return (
        f"Nothing in the dataset matches {style_name} that is {sweet_name}. "
        "Rather than widen the search and hand you something you did not ask for, "
        "here is the honest answer: that combination is not covered. "
        "Adjust one of the choices below and I will look again."
    )


def out_of_scope(topic: str) -> str:
    """Templated, no retrieval. BRD section 8's posture, in one place."""
    responses = {
        "price": (
            "Price is out of scope here. Nothing in this dataset is checked against what a "
            "shop charges, and a number I cannot verify is worse than no number."
        ),
        "availability": (
            "I cannot tell you what is in stock. Nothing here is checked against a shop's "
            "inventory, so the producers are examples to look for, not a catalogue."
        ),
        "health": (
            "I am not the right source on wine and health, in either direction. "
            "Ask someone qualified."
        ),
        "purchase": (
            "There is no purchase path here. Shipping alcohol is regulated jurisdiction by "
            "jurisdiction, so buying is deliberately not part of this."
        ),
        "vintage": (
            "I do not hold vintage data. Recommendations here name a grape and a producer to "
            "look for, which stays useful without claiming to be current."
        ),
        "injection": (
            "I only recommend grape varieties and styles from this dataset, and I cannot "
            "take instructions that change that. Tell me how you like wine to taste and I "
            "will work from there."
        ),
        "generic": (
            "That is outside what this dataset covers. I can suggest grape varieties and "
            "styles that match how you like wine to taste - ask me about that."
        ),
    }
    return responses.get(topic, responses["generic"])


def _join(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]
