"""Lane 3 and lane 4: the orchestrator, the four workflows, the A-to-K pipeline.

    turns/orchestrated.py   the TurnEngine implementation (the lane-2 seam)
      -> graph.py           one graph run per turn: route -> slot_merge -> workflow
        -> router.py        intent + slot extraction (Haiku, keyword floor)
        -> workflows/       interview | ask | refine | safety
          -> pipeline/      stages A-K
            -> retrieval/   dense vectors, BM25, axis composite (band 3)
            -> gateway/     every model call leaves through one place (lane 4)
          -> prompts.py     versioned templates, cache-stable prefixes

Nothing in here touches the database, the SSE bus, or a route. It yields the same
`TurnEvent` protocol lane 2 defined, and `services/runner.py` does the rest - which is
why swapping engines changes no route, no schema and no frontend code.
"""

from __future__ import annotations

from .state import Context, GraphState, initial_state

__all__ = ["Context", "GraphState", "initial_state"]
