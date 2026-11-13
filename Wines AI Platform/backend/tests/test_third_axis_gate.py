"""Regression: a stated body/oak at the opposite end is not a match (FR-13).

Live repro: after ingesting a full-bodied Saperavi, "a light red that isn't sweet"
ranked it FIRST - sweetness agreement dragged the axis term to 0.667 and the
cross-encoder did the rest. The gate now drops it; a one-level near-miss survives.
"""

from types import SimpleNamespace

from wines_ai.config import Settings
from wines_ai.orchestrator.workflows.ask import _third_axis_too_far

S = Settings()
LIGHT_RED = {"style": "red", "sweetness": "dry", "body": "light"}


def row(**axes):
    base = {"body": None, "oak": None}
    base.update(axes)
    return SimpleNamespace(**base)


def test_opposite_end_body_is_gated():
    assert _third_axis_too_far(row(body="full"), LIGHT_RED, S.third_axis_tolerance_levels)


def test_one_level_near_miss_survives():
    assert not _third_axis_too_far(row(body="medium"), LIGHT_RED, S.third_axis_tolerance_levels)
    assert not _third_axis_too_far(row(body="light"), LIGHT_RED, S.third_axis_tolerance_levels)


def test_oak_is_gated_for_whites():
    crisp = {"style": "white", "sweetness": "dry", "oak": "none"}
    assert _third_axis_too_far(row(oak="pronounced"), crisp, 1)
    assert not _third_axis_too_far(row(oak="subtle"), crisp, 1)


def test_unstated_axis_and_unlabelled_row_pass():
    assert not _third_axis_too_far(row(body="full"), {"sweetness": "dry"}, 1)
    assert not _third_axis_too_far(row(body=None), LIGHT_RED, 1)
