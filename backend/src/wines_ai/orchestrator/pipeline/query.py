"""Stages A, B and C: the conversation never reaches the retriever raw.

A - REWRITE. Resolve ellipsis and coreference. "something lighter than that" is
    meaningless to a retriever; the standalone query it becomes is not. This is the
    stage naive RAG skips and the reason it fails on turn three.
B - DECOMPOSE. Split a multi-intent ask into independent sub-queries, each of which
    runs the rest of the pipeline on its own. Results merge at stage H.
C - EXPAND. The translation layer the product exists for: consumer words to sommelier
    axes ("smooth" -> low tannin, "not too sour" -> soft acidity), plus HyDE - a
    pseudo tasting-note generated from the profile and embedded INSTEAD of the
    question, so the dense arm matches note-to-note rather than question-to-note.

A and B are model calls (Haiku, the cheapest tier, highest volume). C is a table and a
template: a vocabulary mapping is exactly the kind of thing that must not vary
per-turn, and asking a model to look up a synonym is paying for a dictionary.
"""

from __future__ import annotations

import logging

from ...observability import log
from ..gateway import GatewayError, ModelGateway, TurnLedger
from ..prompts import DECOMPOSE, REWRITE

logger = logging.getLogger("wines_ai.pipeline.query")


# --- C: consumer -> sommelier -------------------------------------------
# Read as: when the user says the key, the wine they want has these axis values. The
# keys are what people actually type; the values are what the corpus is labelled with.
CONSUMER_TO_AXIS: dict[str, dict[str, str]] = {
    "smooth": {"tannin": "smooth"},
    "velvety": {"tannin": "smooth"},
    "soft": {"tannin": "smooth"},
    "not too sour": {"acidity": "soft"},
    "not sour": {"acidity": "soft"},
    "not acidic": {"acidity": "soft"},
    "sharp": {"acidity": "racy"},
    "zippy": {"acidity": "racy"},
    "refreshing": {"acidity": "fresh"},
    "crisp": {"acidity": "fresh", "oak": "none"},
    "buttery": {"oak": "pronounced"},
    "creamy": {"oak": "pronounced"},
    "toasty": {"oak": "pronounced"},
    "vanilla": {"oak": "pronounced"},
    "jammy": {"fruit_savoury": "fruit_forward"},
    "fruity": {"fruit_savoury": "fruit_forward"},
    "earthy": {"fruit_savoury": "earthy"},
    "savoury": {"fruit_savoury": "earthy"},
    "savory": {"fruit_savoury": "earthy"},
    "funky": {"fruit_savoury": "earthy"},
    "easy drinking": {"body": "light", "tannin": "smooth"},
    "big": {"body": "full"},
    "bold": {"body": "full"},
    "chewy": {"tannin": "grippy", "body": "full"},
    "grippy": {"tannin": "grippy"},
}

# The words the dense arm should see for a given axis value. Separate from the UI
# labels in `taste/axes.py` on purpose: those are written to be read by a novice, and
# these are written to match a tasting note.
AXIS_TO_CORPUS: dict[tuple[str, str], tuple[str, ...]] = {
    ("sweetness", "dry"): ("no residual sugar", "savoury finish", "not sweet"),
    ("sweetness", "off_dry"): ("a touch of sweetness", "faintly sweet"),
    ("sweetness", "sweet"): ("sweet", "honeyed", "luscious", "dessert"),
    ("body", "light"): ("light-bodied", "delicate", "pale"),
    ("body", "medium"): ("medium-bodied", "balanced weight"),
    ("body", "full"): ("full-bodied", "rich", "powerful", "concentrated"),
    ("oak", "none"): ("unoaked", "clean", "mineral", "stainless"),
    ("oak", "subtle"): ("lightly oaked", "restrained oak"),
    ("oak", "pronounced"): ("oak", "buttery", "toasty", "vanilla", "creamy"),
    ("tannin", "smooth"): ("soft tannins", "supple", "smooth"),
    ("tannin", "moderate"): ("moderate tannins", "some grip"),
    ("tannin", "grippy"): ("firm tannins", "grippy", "structured"),
    ("acidity", "soft"): ("soft acidity", "round"),
    ("acidity", "fresh"): ("fresh acidity", "bright"),
    ("acidity", "racy"): ("racy acidity", "zesty", "sharp"),
    ("fruit_savoury", "fruit_forward"): ("fruit-forward", "jammy", "ripe fruit"),
    ("fruit_savoury", "balanced"): ("balanced fruit",),
    ("fruit_savoury", "earthy"): ("earthy", "savoury", "herbal", "mineral"),
}


def harvest_consumer_words(utterance: str) -> dict[str, str]:
    """Axis values a consumer phrase implies, longest phrase first.

    This runs alongside the interview's own reader rather than instead of it: the
    interview reads the ASKED axes (style, sweetness, body, oak), and this reads the
    four unasked ones, which are the vocabulary of refine and the ones a user is most
    likely to describe without being asked.
    """
    lowered = utterance.lower()
    found: dict[str, str] = {}
    for phrase in sorted(CONSUMER_TO_AXIS, key=len, reverse=True):
        if phrase in lowered:
            for axis, value in CONSUMER_TO_AXIS[phrase].items():
                found.setdefault(axis, value)
    return found


def hyde(profile: dict, utterance: str) -> str:
    """A pseudo tasting note built from the profile - HyDE without a model call.

    The dense arm then compares a tasting note to tasting notes. Generating this with
    a model would cost a Haiku round trip per turn to assemble a sentence out of a
    lookup table, and would make the embedded text non-deterministic, which makes a
    retrieval regression impossible to attribute.
    """
    pieces: list[str] = []
    style = profile.get("style")
    if style:
        pieces.append(f"a {style} wine")
    for axis_id in ("sweetness", "body", "oak", "tannin", "acidity", "fruit_savoury"):
        value = profile.get(axis_id)
        if not value:
            continue
        words = AXIS_TO_CORPUS.get((axis_id, value))
        if words:
            pieces.append(", ".join(words))
    if utterance.strip():
        pieces.append(utterance.strip())
    return ". ".join(pieces)


# --- A: rewrite ----------------------------------------------------------
async def rewrite(
    gateway: ModelGateway,
    ledger: TurnLedger,
    *,
    model: str,
    utterance: str,
    profile: dict,
    history: list[dict],
    previous_row_ids: list[str],
) -> tuple[str, bool, str]:
    """-> (standalone query, resolved, source).

    `source` is "model" or "fallback": a rewriter failure must not fail the turn, and
    an un-rewritten query still retrieves - worse, but it retrieves. The fallback is
    the profile-derived query, which is the same material the model is given.
    """
    payload = {
        "utterance": utterance,
        "profile": {k: v for k, v in sorted(profile.items()) if v},
        "history": history[-6:],
        "previous_row_ids": previous_row_ids[:5],
    }
    req = REWRITE.build(model, payload)
    try:
        result = await gateway.complete(req, ledger)
    except GatewayError as exc:
        log(logger, logging.WARNING, "rewrite_failed", error=repr(exc))
        return _fallback_query(utterance, profile), False, "fallback"

    data = result.structured or {}
    query = str(data.get("query") or "").strip()
    if not query:
        return _fallback_query(utterance, profile), False, "fallback"
    return query, bool(data.get("resolved")), "model"


def _fallback_query(utterance: str, profile: dict) -> str:
    text = hyde(profile, utterance)
    return text or utterance


# --- B: decompose --------------------------------------------------------
async def decompose(
    gateway: ModelGateway,
    ledger: TurnLedger,
    *,
    model: str,
    utterance: str,
    enabled: bool = True,
) -> list[str]:
    """Sub-queries, or [] when the turn asks for one thing.

    Skipped entirely unless the utterance contains a coordinating 'and': a decompose
    call on "a red for steak" is a Haiku round trip that can only answer "no", and the
    highest-volume call in the lane is the one worth not making.
    """
    if not enabled or " and " not in f" {utterance.lower()} ":
        return []
    req = DECOMPOSE.build(model, {"utterance": utterance})
    try:
        result = await gateway.complete(req, ledger)
    except GatewayError as exc:
        log(logger, logging.WARNING, "decompose_failed", error=repr(exc))
        return []
    raw = (result.structured or {}).get("sub_queries") or []
    subs = [str(item).strip() for item in raw if str(item).strip()]
    return subs[:2]
