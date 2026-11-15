"""Unit tests for the AI layer: the gateway, the prompts, and stages A-K.

These are the properties that are cheap to assert here and expensive to discover in
production - a cache prefix that inverted, a budget ceiling that does not bound, a
fusion that normalises scores it must not normalise.
"""

from __future__ import annotations

import asyncio

import pytest

from wines_ai.dataset.loader import load
from wines_ai.orchestrator import pipeline
from wines_ai.orchestrator.gateway import (
    Block,
    BudgetExceeded,
    ModelGateway,
    ModelRequest,
    ModelResult,
    OfflineProvider,
    ProviderDown,
    TurnLedger,
)
from wines_ai.orchestrator.gateway.types import ModelDelta
from wines_ai.orchestrator.pipeline.rerank import mmr, rerank
from wines_ai.orchestrator.pipeline.types import Candidate
from wines_ai.orchestrator.prompts import PROMPTS, ROUTE
from wines_ai.orchestrator.retrieval import HashingEmbedder, cosine
from wines_ai.orchestrator.retrieval import build as build_indexes


@pytest.fixture
def index(settings):
    return load(settings.resolved_dataset_path)


@pytest.fixture
def indexes(index, settings):
    return build_indexes(index, dim=settings.embedding_dim)


# --- the prompt registry: cache order is a cost control -----------------

def test_a_volatile_block_before_a_cacheable_one_is_refused():
    """The cache keys on a byte-exact prefix, so this ordering is not a style choice.

    A cacheable block placed after a per-turn block never caches, and the failure is
    silent: the turn works and costs 10x. Refusing the request is the only way that
    mistake announces itself.
    """
    req = ModelRequest(
        model="claude-haiku-5-5",
        system=[
            Block(text="this turn's question", cacheable=False, label="volatile"),
            Block(text="the standing instructions", cacheable=True, label="rules"),
        ],
        prompt_id="test@1",
    )
    with pytest.raises(ValueError, match="byte-stable"):
        req.validate_cache_order()


@pytest.mark.parametrize("prompt", list(PROMPTS.values()), ids=lambda p: p.id)
def test_every_registered_prompt_puts_the_turn_payload_last(prompt):
    req = prompt.build("claude-haiku-5-5", {"kind": "probe", "utterance": "x"})
    req.validate_cache_order()
    assert all(block.cacheable for block in req.system), "the prefix must be stable"
    assert req.user[-1].label == "turn_payload"
    assert not req.user[-1].cacheable
    assert prompt.version in req.prompt_id


def test_the_cacheable_prefix_is_identical_across_turns():
    a = ROUTE.build("claude-haiku-5-5", {"utterance": "a red"})
    b = ROUTE.build("claude-haiku-5-5", {"utterance": "something sweet"})
    assert [blk.text for blk in a.system] == [blk.text for blk in b.system]
    assert a.user[0].text != b.user[0].text


# --- the gateway ---------------------------------------------------------

class _Flaky:
    name = "flaky"

    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls = 0

    async def complete(self, req):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("upstream exploded")
        return ModelResult(model=req.model, text="ok", tokens_in=10, tokens_out=5)

    async def stream(self, req):
        yield ModelDelta(text="ok")
        yield ModelResult(model=req.model, tokens_in=10, tokens_out=1)


def _gateway(provider, **kwargs):
    defaults = dict(
        timeout_seconds=5.0,
        max_attempts=2,
        breaker_threshold=3,
        breaker_cooldown_seconds=30.0,
    )
    defaults.update(kwargs)
    return ModelGateway(provider, **defaults)


def test_retry_is_bounded_and_then_reports_the_provider_down():
    provider = _Flaky(fail_times=99)
    gateway = _gateway(provider)
    ledger = TurnLedger(ceiling_usd=1.0)
    req = ROUTE.build("claude-haiku-5-5", {"utterance": "x"})

    with pytest.raises(ProviderDown):
        asyncio.run(gateway.complete(req, ledger))
    assert provider.calls == 2, "max_attempts must bound the retry"


def test_the_breaker_opens_and_stops_calling_out():
    provider = _Flaky(fail_times=99)
    gateway = _gateway(provider, max_attempts=1, breaker_threshold=2)
    ledger = TurnLedger(ceiling_usd=1.0)
    req = ROUTE.build("claude-haiku-5-5", {"utterance": "x"})

    for _ in range(2):
        with pytest.raises(ProviderDown):
            asyncio.run(gateway.complete(req, ledger))
    calls_before = provider.calls
    with pytest.raises(ProviderDown, match="breaker is open"):
        asyncio.run(gateway.complete(req, ledger))
    assert provider.calls == calls_before, "an open breaker must not reach the upstream"


def test_a_recovered_upstream_closes_the_breaker():
    provider = _Flaky(fail_times=1)
    gateway = _gateway(provider, max_attempts=3)
    ledger = TurnLedger(ceiling_usd=1.0)
    result = asyncio.run(gateway.complete(ROUTE.build("claude-haiku-5-5", {}), ledger))
    assert result.text == "ok"
    assert ledger.tokens_in == 10 and ledger.tokens_out == 5


def test_the_per_turn_ceiling_bounds_spend_rather_than_reporting_it():
    """The ceiling existed in config with nothing reading it. Now it refuses."""
    ledger = TurnLedger(ceiling_usd=0.0000001)
    gateway = _gateway(_Flaky(fail_times=0))
    with pytest.raises(BudgetExceeded):
        asyncio.run(gateway.complete(ROUTE.build("claude-sonnet-5-5", {"q": "x" * 4000}), ledger))


def test_a_runaway_generator_is_stopped_mid_stream():
    class _Runaway:
        name = "runaway"

        async def complete(self, req):  # pragma: no cover - unused
            raise AssertionError

        async def stream(self, req):
            for _ in range(10_000):
                yield ModelDelta(text="word " * 50)
            yield ModelResult(model=req.model)

    gateway = _gateway(_Runaway())
    ledger = TurnLedger(ceiling_usd=0.01)

    async def drive():
        produced = []
        with pytest.raises(BudgetExceeded):
            # Its own small request, not a registry prompt: what is under test is the
            # mid-stream cut, and borrowing ROUTE tied it to that prompt's size - v2's
            # longer guide prices above this ceiling before a token streams.
            req = ModelRequest(
                model="claude-sonnet-5-5", user=[Block(text="x")], max_tokens=512
            )
            async for item in gateway.stream(req, ledger):
                produced.append(item)
        return produced

    produced = asyncio.run(drive())
    assert produced, "the partial text already streamed must not be retracted"
    assert ledger.spent_usd <= ledger.ceiling_usd * 2, "spend must be bounded, not merely logged"


def test_the_offline_provider_is_free_whatever_model_the_request_names():
    gateway = _gateway(OfflineProvider())
    ledger = TurnLedger(ceiling_usd=0.0001)
    result = asyncio.run(
        gateway.complete(ROUTE.build("claude-sonnet-5-5", {"utterance": "a bold red"}), ledger)
    )
    assert result.degraded is True
    assert ledger.spent_usd == 0.0


def test_the_offline_router_agrees_with_the_keyword_lane():
    """The offline provider is the deterministic baseline, not a second implementation."""
    from wines_ai.turns.intent import classify

    provider = OfflineProvider()
    payload = {"utterance": "how much does it cost", "profile": {}}
    result = asyncio.run(provider.complete(ROUTE.build("claude-haiku-5-5", payload)))
    intent, _, topic = classify("how much does it cost", {})
    assert result.structured["intent"] == intent == "out_of_scope"
    assert result.structured["out_of_scope_topic"] == topic


# --- stage C: the translation layer -------------------------------------

@pytest.mark.parametrize(
    "phrase,axis,value",
    [
        ("something smooth", "tannin", "smooth"),
        ("not too sour", "acidity", "soft"),
        ("buttery", "oak", "pronounced"),
        ("jammy", "fruit_savoury", "fruit_forward"),
        ("earthy", "fruit_savoury", "earthy"),
    ],
)
def test_consumer_words_become_sommelier_axes(phrase, axis, value):
    assert pipeline.harvest_consumer_words(phrase)[axis] == value


def test_hyde_embeds_a_tasting_note_not_a_question():
    note = pipeline.hyde({"style": "red", "body": "full", "oak": "pronounced"}, "what should I get")
    assert "full-bodied" in note and "buttery" in note
    assert "?" not in note


# --- the retrieval arms --------------------------------------------------

def test_the_sparse_arm_finds_an_exact_varietal(indexes, index):
    hits = indexes.sparse("Malbec", k=5)
    assert hits
    top = index.resolve(hits[0][0])
    assert "malbec" in top.variety.lower()


def test_the_dense_arm_survives_morphology():
    embedder = HashingEmbedder(dim=384)
    oaky = embedder.encode("heavily oaked and buttery with vanilla")
    oak = embedder.encode("oak, butter and vanilla notes")
    unrelated = embedder.encode("racy acidity, bone-dry, mineral")
    assert cosine(oaky, oak) > cosine(oaky, unrelated)


def test_negation_is_not_the_same_vector_as_assertion():
    embedder = HashingEmbedder(dim=384)
    assert cosine(embedder.encode("not sweet"), embedder.encode("sweet")) < 0.99


def test_the_structured_arm_is_a_recall_floor(index, indexes, settings):
    """Even when both text sides miss, the axis scan returns something to rank."""
    plan = pipeline.plan(
        query="qwertyuiop zxcvbnm", profile={"style": "red", "sweetness": "dry"},
        settings=settings,
    )
    arms = asyncio.run(
        pipeline.retrieve(index=index, indexes=indexes, plan_=plan, hyde_text="")
    )
    assert arms["structured"], "the floor must hold when the text arms return nothing"


def test_the_hard_filter_runs_inside_the_arms(index, indexes, settings):
    """Filtering after retrieval is how a hybrid returns an empty list."""
    plan = pipeline.plan(
        query="rich and bold", profile={"style": "white", "sweetness": "dry"}, settings=settings
    )
    arms = asyncio.run(
        pipeline.retrieve(index=index, indexes=indexes, plan_=plan, hyde_text="white wine")
    )
    for hits in arms.values():
        for row_id, _ in hits:
            assert index.resolve(row_id).style == "white"


# --- stage F: fusion -----------------------------------------------------

def test_rrf_is_rank_based_not_score_based(index):
    """The arms' score scales are incomparable, so only the ranks may be fused."""
    rows = index.rows[:3]
    ids = [r.row_id for r in rows]
    # The sparse arm reports enormous scores; the dense arm tiny ones. A fusion that
    # read the numbers would let BM25 outvote everything.
    arms = {
        "dense": [(ids[0], 0.012), (ids[1], 0.011)],
        "sparse": [(ids[1], 940.0), (ids[2], 12.0)],
    }
    fused = pipeline.fuse(index=index, arms=arms, rrf_k=60, top_n=10)
    by_id = {c.row_id: c for c in fused}
    # ids[1] is rank 2 in dense and rank 1 in sparse -> two contributions.
    assert by_id[ids[1]].fused == pytest.approx(1 / 62 + 1 / 61)
    assert by_id[ids[0]].fused == pytest.approx(1 / 61)
    assert fused[0].row_id == ids[1]


def test_fusion_dedupes_by_row_id(index):
    rid = index.rows[0].row_id
    arms = {"dense": [(rid, 1.0)], "sparse": [(rid, 1.0)], "structured": [(rid, 1.0)]}
    fused = pipeline.fuse(index=index, arms=arms, rrf_k=60, top_n=10)
    assert len(fused) == 1
    assert fused[0].arms == ["dense", "sparse", "structured"]


# --- stages G and H -----------------------------------------------------

def test_the_reranker_lifts_a_named_varietal(index):
    rows = [r for r in index.rows if r.style == "red"][:6]
    candidates = [Candidate(row=r, fused=0.01) for r in rows]
    target = rows[-1]
    ranked = rerank(
        candidates, query=f"{target.variety} please", profile={"style": "red"}, top_n=6
    )
    assert ranked[0].row_id == target.row_id


def test_mmr_spreads_across_variety(index):
    rows = [r for r in index.rows if r.style == "red"][:8]
    candidates = []
    for i, row in enumerate(rows):
        c = Candidate(row=row)
        c.rerank = 1.0 - i * 0.01
        candidates.append(c)
    chosen = mmr(candidates, want=5, lambda_=0.7, min_results=3)
    assert len(chosen) == 5
    assert pipeline.variety_count(chosen) == 5


def test_mmr_backfills_rather_than_returning_too_few(index):
    row = index.rows[0]
    candidates = []
    for i in range(4):
        c = Candidate(row=row)
        c.rerank = 1.0 - i * 0.01
        candidates.append(c)
    chosen = mmr(candidates, want=5, lambda_=0.7, min_results=3)
    assert len(chosen) >= 3, "the spread is a preference, not a cap on the count"


# --- stage I: packing ----------------------------------------------------

def test_packing_enforces_the_budget_by_dropping_whole_rows(index):
    candidates = [Candidate(row=r) for r in index.rows[:10]]
    packed = pipeline.pack(candidates, budget=120, threshold=0.75)
    assert packed.tokens <= 120
    assert packed.dropped_row_ids, "a row that does not fit must be dropped, not truncated"
    for row in packed.rows:
        # Never a half row: a missing axis is an axis the generator cannot hedge.
        assert "row_id:" in row.text and "axes:" in row.text


def test_packing_collapses_near_duplicates(index, settings):
    row = index.rows[0]
    packed = pipeline.pack(
        [Candidate(row=row), Candidate(row=row)],
        budget=settings.context_token_budget,
        threshold=0.75,
    )
    assert len(packed.rows) == 1
    assert packed.collapsed_row_ids == [row.row_id]


def test_the_packed_row_carries_exactly_the_contracted_fields(index):
    text = pipeline.render_row(index.rows[0], threshold=0.75)
    for field in (
        "row_id", "variety", "style", "axes", "description",
        "typical_regions", "example_producers", "review_status", "dataset_version",
    ):
        assert f"{field}:" in text
    # Confidence reaches the model as a word, not a number to quote at a user.
    assert "certain" in text or "uncertain" in text


# --- stage K: verification and the eval tap -----------------------------

def test_an_unpacked_row_id_is_unsupported_by_construction(index, settings):
    packed = pipeline.pack(
        [Candidate(row=index.rows[0])], budget=settings.context_token_budget, threshold=0.75
    )
    gateway = _gateway(OfflineProvider())
    grounded, unsupported, source = asyncio.run(
        pipeline.verify(
            gateway,
            TurnLedger(ceiling_usd=1.0),
            model="claude-haiku-5-5",
            packed=packed,
            claims=[{"row_id": "w-9999", "text": "an invented bottle"}],
        )
    )
    assert grounded is False
    assert unsupported == ["w-9999"]
    assert source == "model"


def test_a_verifier_outage_falls_back_to_the_structural_check(index, settings):
    packed = pipeline.pack(
        [Candidate(row=index.rows[0])], budget=settings.context_token_budget, threshold=0.75
    )
    gateway = _gateway(_Flaky(fail_times=99), max_attempts=1)
    grounded, unsupported, source = asyncio.run(
        pipeline.verify(
            gateway,
            TurnLedger(ceiling_usd=1.0),
            model="claude-haiku-5-5",
            packed=packed,
            claims=[{"row_id": "w-9999", "text": "x"}],
        )
    )
    assert source == "structural"
    assert grounded is False and unsupported == ["w-9999"]


def test_unmeasured_retrieval_metrics_are_none_not_one():
    """An unmeasured metric must not be able to masquerade as a measured one."""
    assert pipeline.ndcg_at_k(["a", "b"], set()) is None
    assert pipeline.recall_at_k(["a", "b"], set(), k=10) is None
    assert pipeline.ndcg_at_k(["a", "b"], {"a"}) == pytest.approx(1.0)
    assert pipeline.recall_at_k(["b", "a"], {"a", "c"}, k=2) == pytest.approx(0.5)


# --- regressions found by reading a real response ------------------------

def test_a_prose_call_is_not_answered_with_json():
    """`why_it_matches` arrived as the literal text `{}` on every card.

    The offline provider dispatched on its schema handlers and fell through to
    `json.dumps({})` for any call without a schema - which is every non-streaming
    prose call, and the card reason is one of those per card. Nothing in the test
    suite looked at the text, so it took reading an actual SSE frame to see it.
    """
    from wines_ai.orchestrator.prompts import CARD_REASON

    provider = OfflineProvider()
    req = CARD_REASON.build(
        "claude-sonnet-5-5",
        {"kind": "card_reason", "fallback": "Smooth and not sweet, as you asked."},
    )
    result = asyncio.run(provider.complete(req))
    assert result.text == "Smooth and not sweet, as you asked."
    assert result.structured is None


def test_mmr_caps_a_variety_the_way_lane_2_does(index):
    """Two rows of one variety must not both be served while another is available.

    A pure MMR penalty let both Chardonnays through when the query named Chardonnay.
    Defensible in isolation, but `taste/diversify.py` caps lane 2 at one row per
    variety - so the two engines would answer the same question differently on FR-7.
    """
    chardonnays = [r for r in index.rows if r.variety.lower().startswith("chardonnay")]
    # Five alternatives of five DISTINCT varieties, so a result set of five can be
    # filled without repeating one. (The seed has three Rieslings, so filtering by
    # style alone does not give five distinct keys.) With fewer, both engines relax
    # the cap to reach the count - that is the backfill, and it is the next test.
    others = []
    seen = {"chardonnay"}
    for row in index.rows:
        key = row.variety.split("(")[0].strip().lower()
        if row.style == "white" and key not in seen:
            seen.add(key)
            others.append(row)
        if len(others) == 5:
            break
    assert len(chardonnays) >= 2 and others

    candidates = []
    for i, row in enumerate(chardonnays):
        c = Candidate(row=row)
        c.rerank = 1.0 - i * 0.001  # near-identical, and the best two scores
        candidates.append(c)
    for i, row in enumerate(others):
        c = Candidate(row=row)
        c.rerank = 0.5 - i * 0.01
        candidates.append(c)

    chosen = mmr(candidates, want=5, lambda_=0.7, min_results=3)
    keys = [c.row.variety.split("(")[0].strip().lower() for c in chosen]
    assert keys.count("chardonnay") == 1, keys


def test_the_cap_relaxes_only_to_reach_the_minimum(index):
    """The spread is a preference, not a cap on the count."""
    chardonnays = [r for r in index.rows if r.variety.lower().startswith("chardonnay")]
    candidates = []
    for i, row in enumerate(chardonnays):
        c = Candidate(row=row)
        c.rerank = 1.0 - i * 0.01
        candidates.append(c)
    chosen = mmr(candidates, want=5, lambda_=0.7, min_results=2)
    assert len(chosen) >= 2


# --- accounting, as corrected by live responses -------------------------

def test_an_unrated_cache_read_is_billed_as_input_not_free():
    """Found by reading a live response, not by a test.

    A Haiku router call reported 1,580 cache-read tokens against 59 fresh ones, and
    `RATES["claude-haiku-5-5"].cache_read` was None - so 96% of that prompt cost
    $0.00 in our own accounting. A ceiling that can under-report is not a ceiling.
    """
    from wines_ai.pricing import RATES, cost_usd

    assert RATES["claude-haiku-5-5"].cache_read is None, "premise of this test"
    billed = cost_usd("claude-haiku-5-5", tokens_in=59, cache_read_tokens=1580)
    as_input = cost_usd("claude-haiku-5-5", tokens_in=59 + 1580)
    assert billed == as_input > 0.0


def test_a_documented_cache_read_rate_is_used_when_there_is_one():
    from wines_ai.pricing import cost_usd

    # Sonnet 5.5 reads cache at $0.10/MTok against $2.00 fresh.
    assert cost_usd("claude-sonnet-5-5", cache_read_tokens=1_000_000) == pytest.approx(0.10)
    assert cost_usd("claude-sonnet-5-5", tokens_in=1_000_000) == pytest.approx(2.00)


def test_a_cache_write_costs_more_than_fresh_input():
    """The first turn is the one that writes the cache; it must not look cheaper."""
    from wines_ai.pricing import CACHE_WRITE_MULTIPLIER, cost_usd

    write = cost_usd("claude-sonnet-5-5", cache_write_tokens=1_000_000)
    fresh = cost_usd("claude-sonnet-5-5", tokens_in=1_000_000)
    assert write == pytest.approx(fresh * CACHE_WRITE_MULTIPLIER)
    assert CACHE_WRITE_MULTIPLIER > 1.0


def test_the_ledger_totals_every_token_class():
    gateway = _gateway(_Flaky(fail_times=0))
    ledger = TurnLedger(ceiling_usd=1.0)

    class _Caching:
        name = "caching"

        async def complete(self, req):
            return ModelResult(
                model=req.model, text="ok", tokens_in=59,
                tokens_out=63, cache_read_tokens=1580, cache_write_tokens=800,
            )

        async def stream(self, req):  # pragma: no cover - unused
            raise AssertionError

    gateway = _gateway(_Caching())
    asyncio.run(gateway.complete(ROUTE.build("claude-haiku-5-5", {}), ledger))
    assert ledger.cache_read_tokens == 1580
    assert ledger.cache_write_tokens == 800
    assert ledger.spent_usd > 0.0
    trace = ledger.trace()[0]
    assert trace["cache_read"] == 1580 and trace["cache_write"] == 800


def test_a_turn_that_called_no_model_does_not_name_one():
    """A chip-answered interview turn makes no model call; reporting the generator
    against 0 tokens and $0.00 invites the wrong conclusion about where money goes."""
    from wines_ai.pricing import cost_usd

    assert TurnLedger(ceiling_usd=1.0).dominant_model() is None
    assert cost_usd("none", tokens_in=10, tokens_out=10) == 0.0


def test_the_dominant_model_is_the_one_that_spent_the_most():
    ledger = TurnLedger(ceiling_usd=1.0)
    gateway = _gateway(OfflineProvider())

    class _Priced:
        name = "priced"

        def __init__(self, model, cost):
            self.model, self.cost = model, cost

    from wines_ai.orchestrator.gateway import CallRecord

    ledger.calls = [
        CallRecord("route@1", "claude-haiku-5-5", 60, 60, 0, 0, 0.00004, 100),
        CallRecord("card_reason@1", "claude-sonnet-5-5", 300, 60, 0, 0, 0.0027, 1700),
        CallRecord("verify@1", "claude-haiku-5-5", 1300, 250, 0, 0, 0.0004, 3400),
    ]
    assert ledger.dominant_model() == "claude-sonnet-5-5"
    assert gateway.provider_name == "offline"


def test_the_card_fan_out_is_bounded_as_a_group():
    """N concurrent calls must not each spend the same headroom.

    Each call's own pre-check reads the ledger before its siblings have recorded
    anything, so a per-call bound would hold N times over. The fan-out prices itself
    as a group before launching, and degrades to templated copy if it cannot afford
    the whole set.
    """
    from wines_ai.orchestrator.prompts import CARD_REASON
    from wines_ai.orchestrator.state import Context, GraphState
    from wines_ai.orchestrator.workflows.ask import _fan_out
    from wines_ai.turns.engine import TurnRequest

    calls = {"n": 0}

    class _Counting:
        name = "counting"

        async def complete(self, req):
            calls["n"] += 1
            return ModelResult(model=req.model, text="generated", tokens_in=300, tokens_out=90)

        async def stream(self, req):  # pragma: no cover - unused
            raise AssertionError

    gateway = _gateway(_Counting())
    req = TurnRequest(
        turn_id="t", conversation_id="c", utterance="x", selected_chip_id=None, profile={}
    )

    def context(ceiling: float) -> Context:
        return Context(
            req=req,
            state=GraphState(
                turn_id="t", conversation_id="c", utterance="x", selected_chip_id=None,
                profile={}, history=[], previous_row_ids=[], dataset_version="v",
            ),
            settings=None,
            index=None,
            indexes=None,
            gateway=gateway,
            ledger=TurnLedger(ceiling_usd=ceiling),
        )

    requests = [CARD_REASON.build("claude-sonnet-5-5", {"kind": "card_reason"}) for _ in range(5)]
    fallbacks = [f"templated {i}" for i in range(5)]

    # Affordable: every call runs, and order is preserved.
    ctx = context(1.0)
    assert asyncio.run(_fan_out(ctx, requests, fallbacks)) == ["generated"] * 5
    assert calls["n"] == 5

    # Unaffordable as a group: nothing is called, every card gets its own fallback.
    calls["n"] = 0
    ctx = context(0.000001)
    assert asyncio.run(_fan_out(ctx, requests, fallbacks)) == fallbacks
    assert calls["n"] == 0
    assert ctx.state.degraded_reason == "turn_budget"


class _LogitScorer:
    """A cross-encoder stand-in that returns fixed logits, keyed by row position."""

    def __init__(self, logits):
        self._logits = logits

    def score_logits(self, query, documents):
        return list(self._logits[: len(documents)])


def _candidates(index, n):
    return [Candidate(row=r) for r in index.rows[:n]]


def test_rerank_orders_by_logit_and_floors_by_calibrated_relevance(index):
    # sigmoid: 2.0 -> 0.88, -2.0 -> 0.12, -8.0 -> 0.0003 (below a 0.005 floor)
    cands = _candidates(index, 3)
    out = rerank(
        cands, query="q", profile={}, top_n=10,
        cross_encoder=_LogitScorer([-2.0, 2.0, -8.0]), ce_weight=1.0, min_relevance=0.005,
    )
    assert [c.row_id for c in out] == [cands[1].row_id, cands[0].row_id]
    assert out[0].rerank == 1.0  # min-max over logits keeps the ordering's full range
    assert 0.0 <= out[1].arm_scores["cross_encoder"] <= 1.0
    assert out[1].arm_scores["cross_encoder_logit"] == -2.0


def test_the_relevance_floor_never_empties_the_list(index):
    cands = _candidates(index, 3)
    out = rerank(
        cands, query="q", profile={}, top_n=10,
        cross_encoder=_LogitScorer([-9.0, -10.0, -11.0]), min_relevance=0.5,
    )
    assert len(out) == 3  # abstaining is the gate's call, not the reranker's
