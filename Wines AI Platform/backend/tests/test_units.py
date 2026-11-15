"""Unit tests: the ranking function and the dataset schema validator (NFR-6)."""

from __future__ import annotations

import pytest

from wines_ai import pricing
from wines_ai.dataset.loader import DatasetError, load
from wines_ai.dataset.schema import DatasetArtifact, WineRow
from wines_ai.taste import diversify, interview, ranking, refine
from wines_ai.taste.axes import AXES, REFINE_BY_ID, label_for


def row(**over) -> WineRow:
    base = dict(
        row_id="w-1", variety="Test", style="red", sweetness="dry", body="medium",
        oak="none", tannin="smooth", acidity="fresh", fruit_savoury="balanced",
        confidence={}, description="d", dataset_version="v1",
    )
    base.update(over)
    return WineRow(**base)


# --- dataset validator ---------------------------------------------------

def test_validator_rejects_unknown_level():
    with pytest.raises(ValueError, match="sweetness"):
        row(sweetness="bone_dry")


def test_validator_rejects_unknown_style():
    with pytest.raises(ValueError, match="unknown style"):
        row(style="orange")


def test_validator_rejects_out_of_range_confidence():
    with pytest.raises(ValueError, match="out of range"):
        row(confidence={"sweetness": 1.5})


def test_validator_rejects_confidence_for_unknown_axis():
    with pytest.raises(ValueError, match="unknown axis"):
        row(confidence={"colour": 0.5})


def test_validator_rejects_unsigned_review():
    """A reviewed row must name its reviewer: producer names are only trustworthy
    because of that signature (BRD section 8)."""
    with pytest.raises(ValueError, match="reviewed_by"):
        row(review_status="reviewed")


def test_validator_accepts_unsigned_fixture():
    """`fixture` is the one status that carries producers without a signature, so it is
    deliberately exempt from the reviewed_by requirement."""
    r = row(review_status="fixture", example_producers=["Some Estate"])
    assert r.review_status == "fixture" and r.reviewed_by is None


def test_validator_rejects_signed_fixture():
    """The forgery guard, and the reason `fixture` is safe to add at all: populating
    producers and then stamping a reviewer name would forge exactly the signature the
    schema exists to protect."""
    with pytest.raises(ValueError, match="unverified by definition"):
        row(review_status="fixture", reviewed_by="A Person")


def test_validator_rejects_extra_field():
    with pytest.raises(ValueError):
        WineRow(
            row_id="w-1", variety="T", style="red", sweetness="dry", body="medium",
            oak="none", tannin="smooth", acidity="fresh", fruit_savoury="balanced",
            description="d", dataset_version="v1", price=12.0,
        )


def test_artifact_rejects_duplicate_row_ids():
    with pytest.raises(ValueError, match="duplicate row_id"):
        DatasetArtifact(dataset_version="v1", rows=[row(), row()])


def test_artifact_rejects_version_mismatch():
    with pytest.raises(ValueError, match="does not match artifact"):
        DatasetArtifact(dataset_version="v2", rows=[row()])


def test_loader_rejects_missing_file(tmp_path):
    with pytest.raises(DatasetError, match="not found"):
        load(tmp_path / "nope.json")


def test_loader_rejects_bad_row(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"dataset_version":"v1","rows":[{"row_id":"w-1"}]}')
    with pytest.raises(DatasetError, match="failed validation"):
        load(bad)


# --- the shipped seed artifact -------------------------------------------

def test_seed_artifact_is_honest(settings):
    """The seed is a stand-in for band 4's output and must not pretend otherwise."""
    index = load(settings.resolved_dataset_path)
    assert index.row_count >= 30
    assert set(index.review_status_counts) == {"unreviewed"}
    # Producer names are the weakest point in the system and the one field a model
    # confabulates. A fixture must not invent them.
    assert all(r.example_producers == [] for r in index.rows)
    assert all(r.typical_regions for r in index.rows)
    assert len(index.by_style) == 5


# --- generated copy ------------------------------------------------------

def test_lead_in_never_doubles_a_word(settings):
    """Regression: the sentence ends in "for" and the tail used to start with another
    one, so every recommendation with a filled profile read "worth looking for for not
    sweet at all". Asserted as "no word repeats itself" rather than against a fixed
    string, so the next copy edit cannot reintroduce the same class of bug."""
    import re

    from wines_ai.turns.deterministic import DeterministicEngine

    engine = DeterministicEngine.__new__(DeterministicEngine)
    engine.settings = settings

    profiles = [
        {},
        {"sweetness": "dry"},
        {"sweetness": "dry", "body": "full"},
        {"sweetness": "dry", "body": "full", "oak": "pronounced"},
        {"body": "light", "oak": "none"},
        {"sweetness": "sweet"},
    ]
    for profile in profiles:
        text = engine._lead_in(5, profile)
        assert not re.findall(r"\b(\w+)\s+\1\b", text), f"{profile} -> {text!r}"
        assert text.endswith(".") and "  " not in text


def test_lead_in_separates_labels_that_contain_and(settings):
    """The second defect on that line: these labels are phrases carrying their own
    "and" ("rich and bold"), so joining them with "and" made two of them unreadable as
    "rich and bold and rounded and buttery"."""
    from wines_ai.turns.deterministic import DeterministicEngine

    engine = DeterministicEngine.__new__(DeterministicEngine)
    engine.settings = settings
    text = engine._lead_in(5, {"sweetness": "dry", "body": "full", "oak": "pronounced"})
    assert text == (
        "Here are 5 grape varieties worth looking for: "
        "not sweet at all, rich and bold, rounded and buttery."
    )


# --- the demo artifact ---------------------------------------------------

def test_demo_artifact_carries_producers_and_claims_no_review():
    """The demo exists so a card looks full. It must not buy that by claiming review."""
    from wines_ai.dataset.build_demo import OUT as DEMO_ARTIFACT

    index = load(DEMO_ARTIFACT)
    assert index.version == "demo-0.1"
    assert set(index.review_status_counts) == {"fixture"}
    assert all(r.example_producers for r in index.rows), "a fixture row with no producers"
    # The signature field stays empty on every row: see test_validator_rejects_signed_fixture.
    assert all(r.reviewed_by is None and r.reviewed_at is None for r in index.rows)
    assert index.review_status_counts.get("reviewed", 0) == 0


def test_demo_artifact_differs_from_the_seed_only_in_the_three_declared_fields(settings):
    """The drift guard. The demo is built from the seed by a script, so a taste axis, a
    description or a region can never diverge between the two - and if a later edit
    makes one diverge, this fails rather than shipping two disagreeing datasets."""
    from wines_ai.dataset.build_demo import OUT as DEMO_ARTIFACT

    seed = {r.row_id: r for r in load(settings.resolved_dataset_path).rows}
    demo = {r.row_id: r for r in load(DEMO_ARTIFACT).rows}
    assert seed.keys() == demo.keys()

    allowed = {"example_producers", "review_status", "dataset_version"}
    for row_id, seed_row in seed.items():
        changed = {
            field
            for field in seed_row.model_dump()
            if getattr(seed_row, field) != getattr(demo[row_id], field)
        }
        assert changed <= allowed, f"{row_id} drifted on {sorted(changed - allowed)}"


# --- ranking -------------------------------------------------------------

def test_hard_filter_is_style_only():
    rows = [row(row_id="a", style="red"), row(row_id="b", style="white")]
    out = ranking.hard_filter(rows, {"style": "white"})
    assert [r.row_id for r in out] == ["b"]


def test_exact_match_ranks_first():
    rows = [
        row(row_id="far", sweetness="sweet", body="full"),
        row(row_id="exact", sweetness="dry", body="light"),
    ]
    scored = ranking.rank(rows, {"style": "red", "sweetness": "dry", "body": "light"})
    assert scored[0].row.row_id == "exact"
    assert scored[0].distance == 0.0


def test_sweetness_outweighs_body():
    """Sweetness is weighted heaviest: it is the one error a novice notices instantly."""
    sweet_miss = row(row_id="sweet_miss", sweetness="sweet", body="light")
    body_miss = row(row_id="body_miss", sweetness="dry", body="full")
    profile = {"style": "red", "sweetness": "dry", "body": "light"}
    scored = ranking.rank([sweet_miss, body_miss], profile)
    assert scored[0].row.row_id == "body_miss"


def test_unspecified_axes_are_skipped_not_defaulted():
    scored = ranking.rank([row()], {"style": "red"})
    assert scored[0].per_axis == {}


def test_ranking_is_deterministic_on_ties():
    rows = [row(row_id="w-2"), row(row_id="w-1")]
    for _ in range(5):
        scored = ranking.rank(rows, {"style": "red", "sweetness": "dry"})
        assert [s.row.row_id for s in scored] == ["w-1", "w-2"]


def test_two_step_sweetness_miss_exceeds_match_floor(settings):
    """This is what makes the FR-13 empty state reachable instead of theoretical."""
    scored = ranking.rank([row(sweetness="sweet")], {"style": "red", "sweetness": "dry"})
    assert scored[0].distance > settings.max_match_distance


def test_one_step_sweetness_miss_is_within_floor(settings):
    scored = ranking.rank([row(sweetness="off_dry")], {"style": "red", "sweetness": "dry"})
    assert scored[0].distance <= settings.max_match_distance


# --- diversify -----------------------------------------------------------

def test_diversify_prefers_distinct_varieties():
    rows = [
        row(row_id="a", variety="Cabernet Sauvignon"),
        row(row_id="b", variety="Cabernet Sauvignon"),
        row(row_id="c", variety="Malbec"),
    ]
    scored = ranking.rank(rows, {"style": "red"})
    chosen = diversify.diversify(scored, want=2)
    assert {c.row.variety for c in chosen} == {"Cabernet Sauvignon", "Malbec"}


def test_diversify_backfills_rather_than_returning_too_few():
    rows = [row(row_id=f"r{i}", variety="Merlot") for i in range(4)]
    scored = ranking.rank(rows, {"style": "red"})
    assert len(diversify.diversify(scored, want=3)) == 3


def test_variety_key_collapses_parenthetical_styles():
    rows = [
        row(row_id="a", variety="Chardonnay (oaked)", style="white"),
        row(row_id="b", variety="Chardonnay (unoaked)", style="white"),
        row(row_id="c", variety="Riesling", style="white"),
    ]
    scored = ranking.rank(rows, {"style": "white"})
    chosen = diversify.diversify(scored, want=2)
    assert diversify.variety_count(chosen) == 2


# --- interview -----------------------------------------------------------

def test_style_is_asked_first():
    q = interview.next_question({}, 0, 3)
    assert q.axis == "style"


def test_reds_get_body_as_third_question():
    q = interview.next_question({"style": "red", "sweetness": "dry"}, 2, 3)
    assert q.axis == "body"


def test_whites_get_oak_as_third_question():
    q = interview.next_question({"style": "white", "sweetness": "dry"}, 2, 3)
    assert q.axis == "oak"


def test_dessert_skips_the_third_question():
    """FR-4: style and sweetness are already enough for dessert."""
    profile = {"style": "dessert", "sweetness": "sweet"}
    assert interview.next_question(profile, 2, 3) is None
    assert interview.is_sufficient(profile)


def test_question_cap_is_three():
    assert interview.next_question({"style": "red"}, 3, 3) is None


def test_longest_match_wins_on_negation():
    """'not sweet' must not be read as 'sweet'."""
    assert interview.read_answer("sweetness", "nothing too sweet please") == "dry"
    assert interview.read_answer("sweetness", "properly sweet") == "sweet"
    assert interview.read_answer("sweetness", "just a hint of sweetness") == "off_dry"


def test_read_any_harvests_several_axes_at_once():
    found = interview.read_any("a bold red, not sweet")
    assert found["style"] == "red"
    assert found["body"] == "full"
    assert found["sweetness"] == "dry"


def test_read_chip_rejects_unknown_level():
    assert interview.read_chip("sweetness:bone_dry") is None
    assert interview.read_chip("style:red") == ("style", "red")


# --- refine --------------------------------------------------------------

def test_refine_moves_one_axis_one_step():
    profile = {"style": "red", "sweetness": "sweet"}
    patch, blocked = refine.apply(profile, REFINE_BY_ID["less_sweet"])
    assert patch == {"sweetness": "off_dry"} and blocked is None


def test_refine_blocks_at_the_end_of_a_scale():
    patch, blocked = refine.apply({"style": "red", "sweetness": "dry"}, REFINE_BY_ID["less_sweet"])
    assert patch == {} and "lowest" in blocked


def test_refine_rejects_an_axis_that_does_not_apply():
    patch, blocked = refine.apply({"style": "white"}, REFINE_BY_ID["smoother"])
    assert patch == {} and "does not apply" in blocked


def test_refine_starts_unasked_axes_from_the_middle():
    patch, blocked = refine.apply({"style": "red"}, REFINE_BY_ID["smoother"])
    assert patch == {"tannin": "smooth"} and blocked is None


def test_refine_detects_free_text():
    assert refine.detect("can I have something lighter")["id"] == "lighter"
    assert refine.detect("too sweet for me")["id"] == "less_sweet"
    assert refine.detect("hello") is None


# --- vocabulary ----------------------------------------------------------

def test_no_user_facing_label_says_dry():
    """'dry' is the most misused word in consumer wine language (BRD section 3)."""
    for axis in AXES:
        for level in axis.levels:
            assert "dry" not in level.label.lower()
            assert "dry" not in level.hedged_label.lower()


def test_hedged_label_below_threshold():
    assert label_for("sweetness", "dry", 0.9, 0.75) == "Not sweet at all"
    assert label_for("sweetness", "dry", 0.5, 0.75) == "probably not sweet"


# --- pricing -------------------------------------------------------------

def test_haiku_tier_break_is_priced():
    """Above 100K input tokens Haiku's input rate is 5x - the trap worth guarding."""
    small = pricing.cost_usd("claude-haiku-5-5", 100_000, 0)
    big = pricing.cost_usd("claude-haiku-5-5", 100_001, 0)
    assert big > small * 4.9


def test_batch_discount_is_half():
    full = pricing.cost_usd("claude-sonnet-5-5", 10_000, 1_000)
    batched = pricing.cost_usd("claude-sonnet-5-5", 10_000, 1_000, batch=True)
    assert batched == pytest.approx(full * 0.5)


def test_cache_read_is_cheaper_than_fresh_input():
    fresh = pricing.cost_usd("claude-sonnet-5-5", 10_000, 0)
    cached = pricing.cost_usd("claude-sonnet-5-5", 0, 0, cache_read_tokens=10_000)
    assert cached < fresh / 5


def test_deterministic_engine_is_free():
    assert pricing.cost_usd("deterministic", 10**6, 10**6) == 0.0


def test_unknown_model_costs_zero_rather_than_raising():
    """A pricing gap must not be able to fail a user's turn."""
    assert pricing.cost_usd("some-future-model", 1000, 1000) == 0.0
