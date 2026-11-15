"""The four workflows, and the table that routes an intent to one.

The table is the whole dispatch. Adding a fifth workflow is a new module plus a row
here; it is not a change to the engine, the runner, the routes or the wire contract.
"""

from __future__ import annotations

from . import ask, interview, refine, safety

WORKFLOWS = {
    "interview": interview.run,
    "recommend": ask.run,
    "refine": refine.run,
    "out_of_scope": safety.run,
}

__all__ = ["WORKFLOWS", "ask", "interview", "refine", "safety"]
