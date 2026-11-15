"""The grounding guard, enforced at the engine boundary.

The diagram draws this in lane 3. It lives here instead, because lane 2 is the only
lane every engine must pass through. A guard inside the orchestrator protects against
the orchestrator's mistakes; a guard here protects against ANY engine, including the
Sonnet generator that lands next phase and is the one component actually capable of
inventing a bottle.

'No invented bottle' therefore becomes a structural property of the transport rather
than a promise made by the component most likely to break it.
"""

from __future__ import annotations

import logging

from ..dataset.loader import DatasetIndex
from ..observability import METRICS, log
from ..taste import copy as copytext
from .engine import CardEvent

logger = logging.getLogger("wines_ai.grounding")

# Fields a card may carry that must come from the row verbatim, never from an engine.
_ROW_OWNED = ("variety", "style", "description", "typical_regions", "example_producers",
              "review_status", "dataset_version")


def check_card(index: DatasetIndex, event: CardEvent, *, turn_id: str) -> CardEvent | None:
    """Resolve the card's row_id and rebuild row-owned fields from the row itself.

    Returns a corrected card, or None if the row does not resolve - in which case the
    caller drops the card. An engine cannot smuggle a claim past this by formatting it
    nicely: the text fields that assert facts about a wine are overwritten from the
    dataset, so the only thing an engine controls is `why_it_matches` and the axis
    labels, both of which are derived from the user's own selections.
    """
    row = index.resolve(event.row_id)
    if row is None:
        METRICS.incr("grounding.drop")
        log(
            logger,
            logging.ERROR,
            "grounding_drop",
            turn_id=turn_id,
            row_id=event.row_id,
            reason="row_id does not resolve in the loaded dataset",
        )
        return None

    payload = dict(event.payload)
    # Producer names are copied verbatim from the row - never generated, because that is
    # exactly what a model confabulates (BRD section 8, FR-11).
    payload["variety"] = row.variety
    payload["style"] = row.style
    payload["description"] = row.description
    payload["typical_regions"] = list(row.typical_regions)
    payload["example_producers"] = list(row.example_producers)
    payload["review_status"] = row.review_status
    payload["dataset_version"] = row.dataset_version
    payload["row_id"] = row.row_id

    if not payload.get("why_it_matches"):
        payload["why_it_matches"] = (
            "This row matched your selections; see the taste profile for the detail."
        )
    if not payload.get("axes"):
        payload["axes"] = {}

    METRICS.incr("grounding.pass")
    return CardEvent(row_id=row.row_id, payload=payload)


def fallback_text(index: DatasetIndex, row_id: str) -> str | None:
    """Templated copy drawn straight from the row, for a card that lost its source."""
    row = index.resolve(row_id)
    if row is None:
        return None
    return f"{row.variety} - {copytext.tastes_like(row)}"
