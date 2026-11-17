"""Is this turn about the user's own taste, or a one-off request?

"A sweet wine for a tasting" or "a gift for my dad" says what THIS answer should be,
not what the user likes. Writing it into the stored taste profile would make every
later turn in the session inherit a preference the user never had. A one-off turn
still shapes its own answer; it just is not persisted.

Lexical on purpose: the phrasings are few and fixed, the check runs on every turn, and
it must work on the offline path where no model is available.
"""

from __future__ import annotations

import re

_ONE_OFF = re.compile(
    r"""
    \b(
        for\ (a|the|our|my)\ (wine\ )?tasting
      | (wine\ )?tasting\ (event|party|night|session)
      | for\ tasting
      | (as\ |for\ )?(a\ )?gift\b
      | for\ (a|the|our)\ (party|event|celebration|wedding|occasion|guest|guests)
      | for\ guests
      | for\ (my|a|our)\ (dad|father|mum|mom|mother|parents|friend|friends|boss
                        |partner|wife|husband|girlfriend|boyfriend|host|colleague|client)s?
      | for\ someone\ else
      | for\ tonight
      | this\ (one\ )?time
      | just\ this\ once
      | (just\ )?for\ (a\ )?change
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def is_one_off(text: str) -> bool:
    """True when the utterance frames its request as an occasion, not a preference."""
    return bool(text) and _ONE_OFF.search(text) is not None


__all__ = ["is_one_off"]
