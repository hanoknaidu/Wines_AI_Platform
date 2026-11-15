"""The budget gap in the lexical safety table.

The table carried the literal "under 20", so every other bare-number budget slipped
past the lexical lane to the model. These pin both halves: the budgets are caught,
and taste language that merely contains a number is not.
"""

import pytest

from wines_ai.orchestrator.router import _safety_topic
from wines_ai.turns.intent import classify, safety_topic

CAUGHT = [
    "What goes with steak for under 15?",
    "a red under 30",
    "something up to 25",
    "no more than 12.50",
    "around 40 for a gift",
    "a white below 10",
    "max 20 please",
    "15 quid for a bottle",
    "about 30 dollars",
    "under €18",
    "under 20",  # the original literal still matches
]

NOT_CAUGHT = [
    "a red under 13%",
    "something under 12.5 percent",
    "aged about 10 years",
    "around 6 people for dinner",
    "chill it below 8 degrees",
    "a light red",
    "rich and bold",
    "something for 4 guests",
]


@pytest.mark.parametrize("utterance", CAUGHT)
def test_bare_number_budgets_are_price(utterance):
    assert safety_topic(utterance) == "price"


@pytest.mark.parametrize("utterance", NOT_CAUGHT)
def test_taste_language_with_numbers_is_not_price(utterance):
    assert safety_topic(utterance) is None


@pytest.mark.parametrize("utterance", CAUGHT + NOT_CAUGHT)
def test_keyword_and_model_router_agree(utterance):
    # One implementation, two callers: they must never disagree on what is unsafe.
    assert _safety_topic(utterance) == safety_topic(utterance)


def test_keyword_classifier_routes_bare_budget_out_of_scope():
    assert classify("What goes with steak for under 15?", {}) == ("out_of_scope", 0.9, "price")
