"""Keyword + slot-state intent router.

Returns the same four intents lane 3's Haiku router returns, with a confidence, so
transaction_log.intent and intent_eval have real data before the model exists and the
confusion matrix can be built against this baseline.
"""

from __future__ import annotations

import re

from ..taste import interview, refine

OUT_OF_SCOPE_TOPICS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("price", ("how much", "price", "cost", "cheap", "expensive", "budget", "$", "£", "under 20")),
    ("availability", ("in stock", "available", "stocked", "carry", "find it at", "near me")),
    ("health", ("healthy", "health", "calories", "hangover", "sulphite", "sulfite", "good for you",
                "bad for you", "liver", "pregnan")),
    ("purchase", ("buy", "purchase", "order", "ship", "delivery", "add to cart", "checkout")),
    ("vintage", ("vintage", "what year", "which year", "2019", "2020", "2021")),
    # Prompt injection. Lexical and first, because this is the one topic where the
    # classifier being asked to judge IS the attack: an utterance whose purpose is to
    # change the instructions must be refused before it is rewritten into a retrieval
    # query, embedded, or packed into a prompt. Matching it here means it never
    # reaches stage A at all - see orchestrator/workflows/safety.py.
    ("injection", ("ignore previous", "ignore your", "ignore all previous",
                   "disregard the above", "disregard previous", "disregard your",
                   "system prompt", "your instructions", "new instructions",
                   "you are now", "pretend you are", "act as if you",
                   "reveal your prompt", "repeat your prompt", "jailbreak")),
)


# A budget stated as a bare number. The table above carries the literal "under 20",
# which matched exactly one phrasing: "under 15", "under 30" and "up to 25" all
# slipped past the lexical lane and were left to the model's judgement - on the one
# topic the router's docstring says must not be probabilistic. The currency symbols
# in the table already catch "under £15"; this catches the symbol-less form, and the
# "15 quid" form.
#
# The negative lookahead is what keeps this from eating taste language: "under 13%"
# is alcohol, "about 10 years old" is age, "around 6 people" is a party size. None of
# those is a price, and a false positive here refuses a perfectly answerable question.
# `\.\d` in the lookahead stops "12.5 percent" backtracking to a bare "12".
_BUDGET = re.compile(
    r"\b(?:under|below|less than|no more than|max(?:imum)?|around|about|up to)\s+"
    r"[£$€]?\s?\d+(?:\.\d+)?"
    r"(?!\.\d|\s*(?:%|percent|degrees|°|years?|yrs?|minutes?|mins?|people|guests))\b"
    r"|\b\d+(?:\.\d+)?\s*(?:bucks|dollars|pounds|quid|euros?|usd|gbp|eur)\b",
    re.IGNORECASE,
)


def safety_topic(utterance: str) -> str | None:
    """The out-of-scope topic this utterance lexically matches, or None.

    The single implementation: the keyword router and the model router both call
    this, so the two lanes cannot disagree about what is unsafe.
    """
    lowered = utterance.lower()
    for topic, needles in OUT_OF_SCOPE_TOPICS:
        for needle in needles:
            if needle in lowered:
                return topic
    if _BUDGET.search(utterance):
        return "price"
    return None


def classify(
    utterance: str, profile: dict, *, selected_chip_id: str | None = None, has_results: bool = False
) -> tuple[str, float, str | None]:
    """-> (intent, confidence, out_of_scope_topic).

    Order matters. Safety first, then an explicit chip, then refine-against-results,
    then the interview/recommend decision from slot state.
    """
    topic = safety_topic(utterance)
    if topic is not None:
        return "out_of_scope", 0.9, topic

    if selected_chip_id:
        if selected_chip_id in refine.REFINE_BY_ID:
            return "refine", 1.0, None
        if interview.read_chip(selected_chip_id):
            return "interview", 1.0, None

    if has_results and refine.detect(utterance) is not None:
        return "refine", 0.9, None

    harvested = interview.read_any(utterance)
    merged = {**profile, **harvested}
    if interview.is_sufficient(merged):
        return "recommend", 0.85, None

    return "interview", 0.8, None
