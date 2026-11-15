"""The three workflows on the RAG pipeline: interview, recommend, refine.

Covers the guarded rewrite (rewrite@2), the free-text taste path in the interview,
model choice per workflow (Sonnet / Opus), and the Qdrant + cross-encoder backend
(skipped when the `retrieval` extra is not installed).
"""

from __future__ import annotations

import asyncio

import pytest

from wines_ai.dataset.loader import load
from wines_ai.orchestrator import pipeline
from wines_ai.orchestrator.gateway import ModelGateway, OfflineProvider, TurnLedger
from wines_ai.orchestrator.gateway.types import ModelResult
from wines_ai.orchestrator.prompts import REWRITE
from wines_ai.turns.engine import Checkpoint, ChipsEvent, CitationEvent, Token, TurnRequest
from wines_ai.turns.orchestrated import OrchestratedEngine


class Recording(OfflineProvider):
    """The offline provider, plus a log of (prompt_id, model) for every call."""

    def __init__(self, scripted: dict | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.scripted = scripted or {}

    async def complete(self, req):
        self.calls.append((req.prompt_id, req.model))
        name = (req.schema or {}).get("name", "")
        if name in self.scripted:
            data = self.scripted[name]
            return ModelResult(
                model=req.model, text="", structured=data, tokens_in=1, tokens_out=1
            )
        return await super().complete(req)

    async def stream(self, req):
        self.calls.append((req.prompt_id, req.model))
        async for item in super().stream(req):
            yield item

    def models_for(self, prompt: str) -> set[str]:
        return {model for pid, model in self.calls if pid.startswith(f"{prompt}@")}


def _gateway(provider):
    return ModelGateway(
        provider, timeout_seconds=5.0, max_attempts=1,
        breaker_threshold=3, breaker_cooldown_seconds=30.0,
    )


@pytest.fixture
def index(settings):
    return load(settings.resolved_dataset_path)


def _run(index, settings, provider, **req_kwargs):
    engine = OrchestratedEngine(index, settings, gateway=_gateway(provider))
    req = TurnRequest(
        turn_id="t", conversation_id="c", dataset_version=index.version,
        **{"profile": {}, "selected_chip_id": None, **req_kwargs},
    )

    async def drive():
        return [e async for e in engine.run(req)]

    return asyncio.run(drive())


def _text(events) -> str:
    return "".join(e.text for e in events if isinstance(e, Token))


def _node(events, name):
    return next((e for e in events if isinstance(e, Checkpoint) and e.node == name), None)


# --- pre-retrieval: the guarded rewrite ----------------------------------

def _rewrite(provider, **kw):
    args = dict(model="claude-haiku-5-5", profile={}, history=[], previous_row_ids=[])
    args.update(kw)
    return asyncio.run(
        pipeline.rewrite(_gateway(provider), TurnLedger(ceiling_usd=1.0), **args)
    )


def test_empty_history_skips_the_rewrite_call_entirely():
    provider = Recording()
    query, rewritten, source = _rewrite(provider, utterance="something lighter than that")
    assert (query, rewritten, source) == ("something lighter than that", False, "skipped")
    assert provider.calls == []


def test_a_standalone_decision_returns_the_message_verbatim():
    """Even if the model paraphrased in `query`: an independent message is never changed."""
    provider = Recording({"rewrite": {
        "reasoning": "new topic", "decision": "standalone",
        "query": "sparkling wine, festive, dry, light-bodied",
    }})
    query, rewritten, source = _rewrite(
        provider, utterance="actually, a sparkling for a party",
        history=[{"role": "user", "content": "a bold red"}],
    )
    assert query == "actually, a sparkling for a party"
    assert (rewritten, source) == (False, "model")


def test_a_dependent_message_is_rewritten():
    provider = Recording({"rewrite": {
        "reasoning": "resolves 'that'", "decision": "rewritten",
        "query": "light-bodied red with soft tannins, lighter than a Malbec",
    }})
    query, rewritten, _ = _rewrite(
        provider, utterance="something lighter than that",
        history=[{"role": "assistant", "content": "Malbec [r1]"}],
    )
    assert rewritten and "lighter than a Malbec" in query


def test_an_invalid_decision_falls_back_rather_than_trusting_the_query():
    provider = Recording({"rewrite": {"reasoning": "", "decision": "", "query": "x"}})
    _, rewritten, source = _rewrite(
        provider, utterance="that one", history=[{"role": "user", "content": "a red"}]
    )
    assert (rewritten, source) == (False, "fallback")


def test_the_rewrite_prompt_states_every_guardrail():
    text = REWRITE.instructions
    assert REWRITE.version == "2"
    assert "history is empty" in text
    assert "independent of the history" in text
    assert "UNCHANGED" in text
    assert "adds NO preference" in text
    props = list(REWRITE.schema["schema"]["properties"])
    assert props[0] == "reasoning", "reasoning must precede the decision"


# --- retrieval settings ----------------------------------------------------

def test_top_k_and_augmentation_sizes(settings):
    assert settings.retriever_k == 25
    assert settings.rerank_top_n == 10
    assert settings.interview_top_n == 3


# --- interview ---------------------------------------------------------------

def test_a_typed_taste_gets_suggestions_then_the_next_question(index, settings):
    provider = Recording()
    events = _run(index, settings, provider, utterance="something smoky and peppery")

    suggest = _node(events, "interview_suggest")
    assert suggest is not None, "the free-text taste was not read"
    assert provider.models_for("interview_suggest") == {"claude-sonnet-5-5"}
    assert suggest.state["foreign"] == []
    cites = [e for e in events if isinstance(e, CitationEvent)]
    assert cites and all(index.resolve(r) for r in cites[0].row_ids)
    chips = [e for e in events if isinstance(e, ChipsEvent)]
    assert chips and chips[-1].payload["kind"] == "interview", "the interview must continue"
    # Suggestions come first, then the question.
    order = [type(e).__name__ for e in events if isinstance(e, (CitationEvent, ChipsEvent))]
    assert order.index("CitationEvent") < order.index("ChipsEvent")


def test_a_chip_answer_keeps_the_deterministic_path(index, settings):
    provider = Recording()
    events = _run(
        index, settings, provider, utterance="Red", selected_chip_id="style:red"
    )
    assert _node(events, "interview_suggest") is None
    assert provider.calls == [], "a chip press costs no model call"
    assert any(isinstance(e, ChipsEvent) for e in events)


def test_small_talk_is_not_a_taste(index, settings):
    provider = Recording()
    events = _run(index, settings, provider, utterance="hi there, not sure")
    assert _node(events, "interview_suggest") is None


# --- recommend: Sonnet unless complex ----------------------------------------

_FULL = {"style": "red", "sweetness": "dry", "body": "full"}


def test_a_simple_recommend_uses_sonnet(index, settings):
    provider = Recording()
    events = _run(index, settings, provider, utterance="a bold red", profile=dict(_FULL))
    gen = _node(events, "generator")
    assert gen.state["model"] == "claude-sonnet-5-5"
    assert provider.models_for("card_reason") <= {"claude-sonnet-5-5"}


def test_a_pairing_request_escalates_to_opus(index, settings):
    provider = Recording()
    events = _run(
        index, settings, provider, utterance="a bold red to pair with steak",
        profile=dict(_FULL),
    )
    gen = _node(events, "generator")
    assert gen.state == {"model": "claude-opus-5-5", "reason": "comparison_or_pairing"}
    assert provider.models_for("lead_in") == {"claude-opus-5-5"}


# --- refine: Opus --------------------------------------------------------------

def _previous(index):
    return [r.row_id for r in index.rows if r.style == "red"][:3]


def test_an_unreadable_correction_is_read_by_opus(index):
    """The router decides a turn is a refine; this is what reads WHICH refine it is."""
    from types import SimpleNamespace

    from wines_ai.orchestrator.workflows.refine import read_delta

    provider = Recording({"refine_delta": {
        "reasoning": "syrup means too sweet", "adjustment": "less_sweet",
        "also_requested": [],
    }})
    ctx = SimpleNamespace(
        state=SimpleNamespace(
            utterance="hmm, those all tasted like syrup", selected_chip_id=None,
            previous_row_ids=_previous(index), history=[], profile={"style": "red"},
        ),
        index=index,
        models={"refine": "claude-opus-5-5"},
        gateway=_gateway(provider),
        ledger=TurnLedger(ceiling_usd=1.0),
    )
    chip, source = asyncio.run(read_delta(ctx))
    assert (chip["id"], source) == ("less_sweet", "model")
    assert provider.models_for("refine_delta") == {"claude-opus-5-5"}


def test_a_lexical_correction_needs_no_model_to_read_it(index, settings):
    provider = Recording()
    events = _run(
        index, settings, provider, utterance="Lighter", selected_chip_id="lighter",
        profile=dict(_FULL), previous_row_ids=_previous(index),
    )
    assert _node(events, "refine_delta").state == {"chip": "lighter", "source": "lexical"}
    assert provider.models_for("refine_delta") == set()
    assert _node(events, "generator").state["model"] == "claude-opus-5-5"


# --- Qdrant + cross-encoder --------------------------------------------------

@pytest.fixture(scope="module")
def real_backend():
    pytest.importorskip("qdrant_client")
    pytest.importorskip("fastembed")
    from wines_ai.config import Settings
    from wines_ai.orchestrator.retrieval.vector_store import load_backends

    dense, reranker = load_backends(Settings(retrieval_backend="qdrant"))
    return dense, reranker


def test_qdrant_dense_respects_the_allow_list_inside_the_query(real_backend, index):
    from wines_ai.orchestrator.retrieval.index import document_text

    dense, _ = real_backend
    dense.build({r.row_id: document_text(r) for r in index.rows})
    reds = {r.row_id for r in index.rows if r.style == "red"}
    hits = dense.search("full-bodied red with firm tannins", k=25, allowed=reds)
    assert hits and {rid for rid, _ in hits} <= reds
    assert len(hits) == len(reds)  # K=25 > 13 reds: every eligible row is returned
    assert dense.dim == 768


def test_the_cross_encoder_reorders_by_relevance(real_backend, index):
    _, reranker = real_backend
    whites = [r for r in index.rows if r.style == "white"]
    reds = [r for r in index.rows if r.style == "red"]
    candidates = [pipeline.Candidate(row=r) for r in (whites[:4] + reds[:4])]
    top = pipeline.rerank(
        candidates, query="a bold full-bodied red with grippy tannins",
        profile={}, top_n=4, cross_encoder=reranker,
    )
    assert all("cross_encoder" in c.arm_scores for c in top)
    # Calibrated relevance, not min-max: every score is a probability in [0, 1].
    assert all(0.0 <= c.arm_scores["cross_encoder"] <= 1.0 for c in top)
    assert sum(c.row.style == "red" for c in top) >= 3
