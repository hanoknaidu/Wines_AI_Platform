"""EXPLAIN: a knowledge question ("describe Cabernet Sauvignon"), not a taste answer.

A question about a grape or a wine idea is not a step in the taste interview, and
answering it with "Red, white or rosé?" reads as the system not listening. This module
holds the two lexical pieces both engines share:

* `is_question(utterance)` - does the turn ask to be told about something?
* `find_varieties(utterance, rows)` - which catalogue rows does it name?

Producers ("brands") are only ever taken from the matched rows' `example_producers`,
never generated, so the explain answer stays inside the same grounding guarantee as
the recommendation cards.
"""

from __future__ import annotations

import difflib
import re
import unicodedata

from ..dataset.schema import WineRow

# Phrasings that ask to be TOLD something rather than to be SERVED something.
_EXPLAIN_CUES = (
    "describe",
    "description of",
    "tell me about",
    "tell me more about",
    "explain",
    "what is ",
    "what's ",
    "whats ",
    "what are ",
    "what does",
    "what do ",
    "taste like",
    "tastes like",
    "know about",
    "info on",
    "info about",
    "information on",
    "information about",
    "difference between",
    "how is ",
    "how does",
    "characteristics of",
    "profile of",
)

# A cue word inside a request for wines is still a request: "what's a good red for
# steak" wants cards, and the interview/recommend lanes own it.
_REQUEST_CUES = (
    "recommend",
    "suggest",
    "should i",
    "a good ",
    "some good",
    "show me",
    "find me",
    "give me",
    "what to drink",
    "what goes with",
    "what wine goes",
    "go with",
    "pair with",
    "for dinner",
)

# Everyday names for catalogue varieties. Keys are normalised (lowercase, no accents).
_ALIASES = {
    "cab sav": "cabernet sauvignon",
    "cab sauv": "cabernet sauvignon",
    "cabernet": "cabernet sauvignon",
    "shiraz": "syrah",
    "pinot gris": "pinot grigio",
    "sauv blanc": "sauvignon blanc",
    "savvy b": "sauvignon blanc",
    "zin": "zinfandel",
    "garnacha": "grenache",
    "gruner": "gruner veltliner",
    "port": "tawny port",
    "px": "pedro ximenez",
    "tokaji": "tokaji aszu",
    "moscato": "moscato d'asti",
}


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text.lower()).strip()


def _base(variety: str) -> str:
    """'Chardonnay (oaked)' -> 'chardonnay'; 'Champagne (Brut)' -> 'champagne'."""
    return _norm(re.sub(r"\(.*?\)", "", variety))


def _contains(haystack: str, needle: str) -> bool:
    return re.search(rf"(?<![a-z]){re.escape(needle)}(?![a-z])", haystack) is not None


def is_question(utterance: str) -> bool:
    lowered = f" {_norm(utterance)} "
    if any(cue in lowered for cue in _REQUEST_CUES):
        return False
    return any(cue in lowered for cue in _EXPLAIN_CUES)


def find_varieties(utterance: str, rows: list[WineRow], *, limit: int = 3) -> list[WineRow]:
    """Catalogue rows the utterance names, most specific name first.

    "Pinot Noir" must not also pull in "Rose of Pinot Noir", and "rose of pinot noir"
    must not also pull in "Pinot Noir": a matched name that is contained in a longer
    matched name is dropped.
    """
    text = _norm(utterance)
    for alias, target in _ALIASES.items():
        if _contains(text, alias) and target not in text:
            text = f"{text} | {target}"

    hits: dict[str, list[WineRow]] = {}
    for row in rows:
        base = _base(row.variety)
        if base and _contains(text, base):
            hits.setdefault(base, []).append(row)

    if not hits:
        # Typos and speech-to-text slips ("cabinet sauvignon", "pino noir"): compare
        # each run of words the same length as a variety name, and accept a close one.
        words = re.findall(r"[a-z']+", text)
        bases = {_base(row.variety) for row in rows} | set(_ALIASES)
        for base in sorted(bases, key=len, reverse=True):
            n = len(base.split())
            grams = {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}
            if len(base) >= 5 and difflib.get_close_matches(base, grams, n=1, cutoff=0.8):
                target = _ALIASES.get(base, base)
                matched = [r for r in rows if _base(r.variety) == target]
                if matched:
                    hits[target] = matched
                    break

    names = sorted(hits, key=len, reverse=True)
    kept: list[str] = []
    for name in names:
        if not any(name in longer for longer in kept):
            kept.append(name)

    out: list[WineRow] = []
    for name in kept:
        out.extend(hits[name])
    return out[:limit]


NUDGE = "Want wines matched to your own taste? Just tell me what you usually enjoy."


def producers(rows: list[WineRow], *, limit: int = 5) -> list[str]:
    seen: list[str] = []
    for row in rows:
        for name in row.example_producers:
            if name not in seen:
                seen.append(name)
    return seen[:limit]


def describe(rows: list[WineRow]) -> str:
    """Templated answer, drawn only from the rows. The model-free fallback."""
    if not rows:
        return (
            "That's a good question, but I can only speak to the grapes and styles in my "
            "catalogue. Try asking about a grape like Cabernet Sauvignon, Pinot Noir or "
            "Sauvignon Blanc, or tell me what you like and I'll find wines for you."
        )
    parts = []
    for row in rows:
        style = "sparkling wine" if row.style == "sparkling" else f"{row.style} wine"
        sweet = "not sweet" if row.sweetness == "dry" else row.sweetness.replace("_", "-")
        line = f"{row.variety} is a {sweet}, {row.body}-bodied {style}. {row.description}"
        if row.typical_regions:
            line += f" It is typically grown in {_join(row.typical_regions)}."
        parts.append(line)
    return " ".join(parts)


def producers_line(rows: list[WineRow]) -> str:
    names = producers(rows)
    if not names:
        return ""
    return f"Good examples to look for: {_join(names)}."


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


__all__ = ["describe", "find_varieties", "is_question", "producers", "producers_line"]
