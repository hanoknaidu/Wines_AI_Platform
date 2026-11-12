"""The orchestrator: one graph run per user turn.

    route -> slot_merge -> [ safety | refine | interview | ask ] -> usage

## Why this is a node table and not LangGraph

`pyproject.toml` declares `langgraph` in the `orchestrator` extra, and the diagram says
"LangGraph state machine". What LangGraph brings is a graph DSL, a checkpointer, and
conditional-edge routing. This lane needs the last two and already has them: the
checkpointer is `graph_checkpoint` plus `GraphState.snapshot()`, which has been written
on every turn since lane 2, and the routing is a four-way dispatch on one field.

So adopting it here would mean a dependency, a second state representation, and a
second place a turn can be cancelled - to express a graph with one decision point. The
node table below is the same machine with the same checkpoints in ~40 lines, and the
seam it leaves is honest: a node is `async def (ctx) -> AsyncIterator[TurnEvent]`, which
is the shape a LangGraph node adapter would wrap. If the graph ever grows a cycle, a
join, or human-in-the-loop interrupts, that is the moment the dependency earns itself.

The structure is kept explicit anyway - named nodes, recorded in `state.nodes_run`,
snapshotted per node - because the value of the diagram's state machine was never the
library. It was being able to ask which node decided what.

## Cancellation

Nodes are async generators and the runner drives them, so cancelling a turn stops the
generator at its next yield. There is no separate abort protocol: an abandoned turn
stops costing at the next node boundary, which for the generator is the next token.
"""

from __future__ import annotations

import logging

from ..observability import METRICS, log
from ..taste import interview as interview_mod
from ..turns.engine import Checkpoint, ProfilePatch
from .router import route
from .state import Context
from .workflows import WORKFLOWS

logger = logging.getLogger("wines_ai.graph")


async def run(ctx: Context):
    """Drive one turn. Yields TurnEvents; the runner owns everything else."""
    state = ctx.state

    # --- node: route -----------------------------------------------------
    await route(ctx.gateway, ctx.ledger, state, model=ctx.models["router"])
    state.nodes_run.append("route")
    yield Checkpoint(
        node="intent_router",
        state={
            "intent": state.intent,
            "confidence": state.intent_confidence,
            "source": state.intent_source,
            "topic": state.out_of_scope_topic,
            "slots": dict(state.slots),
        },
    )
    METRICS.incr(f"intent.{state.intent}")

    # --- node: slot_merge ------------------------------------------------
    # Everything the turn stated, written into the profile once, before any workflow
    # reads it. Only unfilled axes are written: a stored answer the user gave
    # explicitly outranks one inferred from this turn's phrasing.
    if state.intent != "out_of_scope":
        patch = {
            axis: value
            for axis, value in state.slots.items()
            if state.profile.get(axis) is None
        }
        if patch:
            state.profile.update(patch)
            provenance = "asked" if state.intent_source == "chip" else "inferred"
            yield ProfilePatch(
                values=patch,
                confidence={
                    axis: {
                        "confidence": 1.0 if provenance == "asked" else 0.8,
                        "provenance": provenance,
                    }
                    for axis in patch
                },
            )
        state.nodes_run.append("slot_merge")

    # --- node: dispatch --------------------------------------------------
    workflow_name = _dispatch(state)
    state.nodes_run.append(f"workflow:{workflow_name}")
    log(
        logger,
        logging.INFO,
        "workflow_selected",
        turn_id=state.turn_id,
        intent=state.intent,
        workflow=workflow_name,
        source=state.intent_source,
    )

    async for event in WORKFLOWS[workflow_name](ctx):
        yield event

    yield Checkpoint(node="complete", state=state.snapshot())


def _dispatch(state) -> str:
    """Which workflow runs. Decided on the POST-merge profile.

    The router's `interview` / `recommend` split is a judgement made before the slots
    this turn stated were written down, so it is re-decided here against the one
    question that actually matters: is there enough to recommend? `is_sufficient` is
    the same function lane 2 uses, which is what keeps the two engines' behaviour
    comparable turn for turn.
    """
    if state.intent == "out_of_scope":
        return "out_of_scope"
    if state.intent == "refine" and state.previous_row_ids:
        return "refine"
    if interview_mod.is_sufficient(state.profile):
        return "recommend"
    return "interview"
