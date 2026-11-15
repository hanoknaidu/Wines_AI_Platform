"""The intent router: classify the turn, extract the slots it states.

The model call is Haiku, made through LangChain with a forced tool call when the
`anthropic` provider is live (`gateway/langchain_router.py`), and through the offline
provider's deterministic equivalent otherwise. Either way it goes through
`gateway.complete_route()`, so it counts toward the turn's ceiling, the breaker and
the cost trace like every other call. It returns the same
four intents the keyword router returns, with a confidence.

## The keyword router is not replaced - it becomes the baseline and the floor

`turns/intent.py` stays, and it is consulted on every turn, for three reasons:

1. **A chip is not a judgement.** When the user taps "Not sweet at all", the intent is
   known exactly. Paying a model to classify a button press is pure waste, and a model
   that disagrees with the button is wrong by construction.
2. **Safety is not probabilistic.** The out-of-scope topics - price, availability,
   health, purchase, vintage - are matched lexically and that match WINS. A router
   that classifies "is this good for my liver" as `recommend` with confidence 0.7
   produces a health claim; the keyword lane cannot. So the two are combined with
   safety first, not averaged.
3. **The confusion matrix needs a baseline.** `intent_eval` has been collecting the
   keyword router's predictions since lane 2. Logging both lets the model be measured
   against it instead of simply trusted.

Low model confidence falls back to the keyword answer, and a router failure is not a
turn failure: the keyword lane answers every turn on its own.
"""

from __future__ import annotations

import logging

from ..observability import METRICS, log
from ..taste import interview, refine
from ..turns.intent import classify as keyword_classify
from ..turns.intent import safety_topic
from .gateway import GatewayError, ModelGateway, TurnLedger
from .prompts import ROUTE
from .state import GraphState

logger = logging.getLogger("wines_ai.router")

VALID_INTENTS = ("interview", "recommend", "refine", "out_of_scope")

# Below this, the keyword answer is used instead. Set where it is because the keyword
# router's own floor is 0.8: a model less sure than that has added nothing.
MIN_MODEL_CONFIDENCE = 0.6


def _safety_topic(utterance: str) -> str | None:
    # Delegates rather than re-implements: a second copy of the loop is how the two
    # lanes would come to disagree about what is unsafe.
    return safety_topic(utterance)


async def route(
    gateway: ModelGateway,
    ledger: TurnLedger,
    state: GraphState,
    *,
    model: str,
) -> None:
    """Fill `state.intent`, `.intent_confidence`, `.intent_source`, `.slots`."""
    keyword_intent, keyword_confidence, keyword_topic = keyword_classify(
        state.utterance,
        state.profile,
        selected_chip_id=state.selected_chip_id,
        has_results=bool(state.previous_row_ids),
    )

    # 1. Safety first, lexically, unconditionally.
    topic = _safety_topic(state.utterance)
    if topic is not None:
        state.intent, state.intent_confidence = "out_of_scope", 0.99
        state.intent_source, state.out_of_scope_topic = "keyword", topic
        METRICS.incr("router.safety_shortcut")
        return

    # 2. An explicit chip is an exact answer, not a classification problem.
    if state.selected_chip_id:
        if state.selected_chip_id in refine.REFINE_BY_ID:
            state.intent, state.intent_confidence, state.intent_source = "refine", 1.0, "chip"
            return
        if (read := interview.read_chip(state.selected_chip_id)) is not None:
            axis, value = read
            state.slots[axis] = value
            state.intent, state.intent_confidence, state.intent_source = (
                "interview",
                1.0,
                "chip",
            )
            return

    # 3. Free text: ask the model, keep the keyword answer as the floor.
    payload = {
        "utterance": state.utterance,
        "profile": {k: v for k, v in sorted(state.profile.items()) if v},
        "selected_chip_id": state.selected_chip_id,
        "previous_row_ids": state.previous_row_ids[:5],
        "history": state.history[-6:],
    }
    try:
        result = await gateway.complete_route(ROUTE.build(model, payload), ledger)
    except GatewayError as exc:
        log(logger, logging.WARNING, "route_failed", error=repr(exc))
        METRICS.incr("router.fallback_keyword")
        state.intent, state.intent_confidence = keyword_intent, keyword_confidence
        state.intent_source, state.out_of_scope_topic = "keyword", keyword_topic
        state.slots.update(interview.read_any(state.utterance))
        return

    data = result.structured or {}
    intent = str(data.get("intent") or "")
    confidence = float(data.get("confidence") or 0.0)

    slots = {
        axis: value
        for axis, value in (data.get("slots") or {}).items()
        if isinstance(value, str) and _valid_slot(axis, value)
    }
    # The keyword harvest is merged in rather than replaced: it reads phrasings the
    # model may miss, and neither is a superset of the other.
    merged = {**interview.read_any(state.utterance), **slots}
    state.slots.update(merged)

    if intent not in VALID_INTENTS or confidence < MIN_MODEL_CONFIDENCE:
        METRICS.incr("router.below_floor")
        state.intent, state.intent_confidence = keyword_intent, keyword_confidence
        state.intent_source, state.out_of_scope_topic = "keyword", keyword_topic
        return

    # A refine with nothing to refine against is not a refine. The model cannot know
    # this; the registry of what the user was shown does.
    if intent == "refine" and not state.previous_row_ids:
        intent = keyword_intent if keyword_intent != "refine" else "interview"
        METRICS.incr("router.refine_without_results")

    state.intent, state.intent_confidence, state.intent_source = intent, confidence, "model"
    state.out_of_scope_topic = (
        str(data.get("out_of_scope_topic") or "") or None if intent == "out_of_scope" else None
    )
    if intent == "out_of_scope" and not state.out_of_scope_topic:
        state.out_of_scope_topic = "generic"

    if intent != keyword_intent:
        # Logged rather than resolved: this is the confusion matrix's raw material.
        log(
            logger,
            logging.INFO,
            "router_disagreement",
            model_intent=intent,
            model_confidence=confidence,
            keyword_intent=keyword_intent,
        )
        METRICS.incr(f"router.disagree.{keyword_intent}_vs_{intent}")


def _valid_slot(axis: str, value: str) -> bool:
    from ..taste.axes import AXES_BY_ID

    axis_def = AXES_BY_ID.get(axis)
    if axis_def is None:
        return False
    return value in [level.value for level in axis_def.levels]
