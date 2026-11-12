"""Which question to ask next, and how to read the answer.

Slots unfilled -> ask, never guess. Style is asked first because it gates which of the
remaining axes even apply (tannin is meaningless for a white). Hard cap: 3 questions.
"""

from __future__ import annotations

from dataclasses import dataclass

from .axes import AXES_BY_ID, STYLE_LABELS, STYLES, Axis, asked_axis_for_style


@dataclass(frozen=True)
class Question:
    axis: str
    prompt: str
    options: list[dict]


def _options_for(axis: Axis) -> list[dict]:
    return [
        {"id": f"{axis.id}:{level.value}", "label": level.label, "value": level.value}
        for level in axis.levels
    ]


def next_question(profile: dict, asked_count: int, max_questions: int) -> Question | None:
    """The next most-discriminating unfilled asked-axis, or None when done.

    'Most discriminating' here is simply question order, which encodes it: style gates
    everything, sweetness is the heaviest weighted axis, and the third question is
    whichever one the chosen style makes meaningful.
    """
    if asked_count >= max_questions:
        return None
    style = profile.get("style")
    for axis in asked_axis_for_style(style):
        if profile.get(axis.id) is None:
            return Question(axis=axis.id, prompt=axis.prompt or "", options=_options_for(axis))
    return None


def is_sufficient(profile: dict) -> bool:
    """Enough to recommend: a style, a sweetness, and the style's third axis if it has one.

    Dessert is sufficient on two slots - FR-4 skips its third question entirely.
    """
    if not profile.get("style") or not profile.get("sweetness"):
        return False
    for axis in asked_axis_for_style(profile.get("style")):
        if profile.get(axis.id) is None:
            return False
    return True


# --- reading a free-text answer -----------------------------------------
# The chip path is exact (the id names the axis and the level). This is the fallback for
# people who type, which the architecture makes a first-class input.

_STYLE_WORDS = {
    "red": ["red", "reds"],
    "white": ["white", "whites"],
    "rose": ["rose", "rosé", "pink", "blush"],
    "sparkling": ["sparkling", "bubbles", "bubbly", "fizz", "champagne", "prosecco"],
    "dessert": ["dessert", "pudding", "after dinner", "with pudding"],
}

_SWEET_WORDS = {
    "dry": ["not sweet", "no sweetness", "nothing sweet", "unsweet", "bone dry", "dry"],
    "off_dry": ["hint of sweet", "a bit sweet", "slightly sweet", "touch of sweet", "off dry",
                "little sweet", "lightly sweet", "semi sweet"],
    "sweet": ["properly sweet", "very sweet", "really sweet", "sweet", "sugary", "dessert sweet"],
}

_BODY_WORDS = {
    "light": ["light", "easy", "delicate", "easy drinking", "not heavy"],
    "medium": ["medium", "middle", "in between", "moderate"],
    "full": ["full", "bold", "rich", "heavy", "big", "powerful", "robust"],
}

_OAK_WORDS = {
    "none": ["crisp", "clean", "sharp", "fresh", "no oak", "unoaked", "mineral"],
    "subtle": ["middle", "in between", "balanced", "a little oak"],
    "pronounced": ["buttery", "rounded", "oaky", "creamy", "toasty", "vanilla"],
}

_AXIS_WORDS = {
    "style": _STYLE_WORDS,
    "sweetness": _SWEET_WORDS,
    "body": _BODY_WORDS,
    "oak": _OAK_WORDS,
}


# Negation cues. Longest-match alone is not enough: "nothing too sweet" contains
# "sweet" but not the phrase "nothing sweet", so a pure phrase table reads it as
# SWEET - and gets it wrong in the worst possible direction, serving a dessert wine
# to someone who just said they do not want one.
_NEGATIONS = ("not ", "nothing ", "no ", "without ", "avoid ", "isn't ", "dont ", "don't ")
_NEGATION_WINDOW = 28

# These win over a negation cue: "just a hint of sweetness" is not a refusal.
_EXPLICIT_OFF_DRY = (
    "hint of sweet", "touch of sweet", "slightly sweet", "a bit sweet",
    "little sweet", "lightly sweet", "semi sweet", "off dry",
)


def _negated(lowered: str, needle: str) -> bool:
    """True if a negation cue sits shortly before `needle`."""
    start = 0
    while (idx := lowered.find(needle, start)) != -1:
        window = lowered[max(0, idx - _NEGATION_WINDOW) : idx]
        if any(cue in window for cue in _NEGATIONS):
            return True
        start = idx + len(needle)
    return False


def read_answer(axis_id: str, text: str) -> str | None:
    """Longest-match, with negation handled before the table is consulted."""
    table = _AXIS_WORDS.get(axis_id)
    if not table:
        return None
    lowered = text.lower()

    if axis_id == "sweetness":
        if any(phrase in lowered for phrase in _EXPLICIT_OFF_DRY):
            return "off_dry"
        if _negated(lowered, "sweet"):
            return "dry"

    best: tuple[int, str] | None = None
    for value, phrases in table.items():
        for phrase in phrases:
            if phrase in lowered and (best is None or len(phrase) > best[0]):
                best = (len(phrase), value)
    return best[1] if best else None


def read_chip(chip_id: str) -> tuple[str, str] | None:
    """'sweetness:off_dry' -> ('sweetness', 'off_dry')."""
    if ":" not in chip_id:
        return None
    axis_id, value = chip_id.split(":", 1)
    axis = AXES_BY_ID.get(axis_id)
    if axis is None:
        return None
    if value not in [level.value for level in axis.levels]:
        return None
    return axis_id, value


def read_any(text: str) -> dict[str, str]:
    """Harvest every axis an utterance happens to state, not just the asked one.

    Someone who opens with 'a smooth dry red' has answered two questions and implied a
    third; re-asking what they already said is the fastest way to look stupid.
    """
    found: dict[str, str] = {}
    for axis_id in ("style", "sweetness", "body", "oak"):
        value = read_answer(axis_id, text)
        if value is not None:
            found[axis_id] = value
    return found


def style_options() -> list[dict]:
    return [
        {"id": f"style:{s}", "label": STYLE_LABELS[s], "value": s} for s in STYLES
    ]
