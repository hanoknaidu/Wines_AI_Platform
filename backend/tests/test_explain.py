"""EXPLAIN: knowledge questions are answered directly, not routed into the interview."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wines_ai.dataset.schema import WineRow
from wines_ai.taste import explain
from wines_ai.turns.intent import classify

SEED = Path(__file__).parents[1] / "src" / "wines_ai" / "dataset" / "seed" / "wines.demo.json"
ROWS = [WineRow(**r) for r in json.loads(SEED.read_text(encoding="utf-8"))["rows"]]


@pytest.mark.parametrize(
    "utterance",
    [
        "describe about cabernet sauvignon",
        "Tell me about Pinot Noir",
        "what is shiraz?",
        "what are tannins",
        "what does Malbec taste like",
    ],
)
def test_questions_route_to_explain(utterance):
    assert classify(utterance, {})[0] == "explain"


@pytest.mark.parametrize(
    "utterance",
    ["red", "whats a good red for steak", "recommend me a malbec", "not sweet, rich and bold"],
)
def test_requests_and_answers_do_not_route_to_explain(utterance):
    assert classify(utterance, {})[0] != "explain"


def test_safety_still_wins_over_explain():
    assert classify("what is the price of cabernet sauvignon", {})[0] == "out_of_scope"


@pytest.mark.parametrize(
    ("utterance", "expected"),
    [
        ("describe cabernet sauvignon", ["Cabernet Sauvignon"]),
        ("what is cab sav", ["Cabernet Sauvignon"]),
        ("tell me about shiraz", ["Syrah"]),
        ("tell me about pinot noir", ["Pinot Noir"]),
        ("describe rose of pinot noir", ["Rose of Pinot Noir"]),
        ("what are tannins", []),
    ],
)
def test_find_varieties(utterance, expected):
    assert [r.variety for r in explain.find_varieties(utterance, ROWS)] == expected


def test_producers_come_only_from_rows():
    rows = explain.find_varieties("describe cabernet sauvignon", ROWS)
    line = explain.producers_line(rows)
    for name in rows[0].example_producers:
        assert name in line
    assert "Cabernet Sauvignon" in explain.describe(rows)


@pytest.mark.parametrize(
    ("utterance", "expected"),
    [
        ("describe about cabinet sauvignon", ["Cabernet Sauvignon"]),
        ("pino noir?", ["Pinot Noir"]),
        ("red", []),
        ("something light", []),
    ],
)
def test_find_varieties_tolerates_typos(utterance, expected):
    assert [r.variety for r in explain.find_varieties(utterance, ROWS)] == expected
