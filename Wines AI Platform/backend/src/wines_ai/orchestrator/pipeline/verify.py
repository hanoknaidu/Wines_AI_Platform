"""Stage K: the claim-to-source check, and the eval tap.

## The verifier

Every card is a claim bundle: a row_id plus prose about that row. The check is whether
each claim traces to a row that was actually packed. Failure is not an error - it
degrades: one repair pass, then templated copy drawn straight from the row. Degrades,
never invents.

This runs *in addition to* `turns/grounding.py`, which sits at the engine boundary and
rebuilds every row-owned field from the dataset. The two are not redundant:

* the grounding guard is **structural** and unconditional - it cannot be bypassed by
  any engine, and it is what makes "no invented bottle" a property of the transport;
* the verifier is **semantic** and advisory - it catches a card whose prose drifted
  from its row even though the row_id resolves, which the guard cannot see because the
  guard does not read the prose.

A card that fails verification still passes the guard. That is why the verifier's
remedy is to replace the *prose*, which is the only field it owns.

## The eval tap

`retrieval_eval` and `intent_eval` are band 3's eval store, and `retrieval_eval` had
no writer - which meant the retrieval side of the system could not be measured at all.
Every turn now logs its query, the ids it retrieved, their ranks and the ids it chose.
recall@k and nDCG@10 are left NULL until a labelled relevant set exists, because the
honest value of recall against no gold set is unknown, not 1.0. What ships today is
the data a gold set is built FROM: the queries that were actually asked and what was
actually returned.
"""

from __future__ import annotations

import logging
import math

from ...observability import log
from ..gateway import GatewayError, ModelGateway, TurnLedger
from ..prompts import VERIFY
from .types import PackedContext

logger = logging.getLogger("wines_ai.pipeline.verify")


async def verify(
    gateway: ModelGateway,
    ledger: TurnLedger,
    *,
    model: str,
    packed: PackedContext,
    claims: list[dict],
    enabled: bool = True,
) -> tuple[bool, list[str], str]:
    """-> (grounded, unsupported_row_ids, source).

    `source` is "model", "structural" or "skipped". A verifier failure falls back to
    the structural check rather than passing the turn: the cheap check is strictly
    better than no check, and it is the half that can be answered exactly.
    """
    if not enabled or not claims:
        return True, [], "skipped"

    packed_ids = set(packed.row_ids)
    structural = [
        str(claim.get("row_id")) for claim in claims if str(claim.get("row_id")) not in packed_ids
    ]

    payload = {
        "packed_row_ids": sorted(packed_ids),
        "claims": claims,
        "corpus": packed.as_text(),
    }
    try:
        result = await gateway.complete(VERIFY.build(model, payload), ledger)
    except GatewayError as exc:
        log(logger, logging.WARNING, "verify_failed", error=repr(exc))
        return not structural, structural, "structural"

    data = result.structured or {}
    if "grounded" not in data:
        return not structural, structural, "structural"

    unsupported = sorted(
        {str(r) for r in data.get("unsupported_row_ids") or []} | set(structural)
    )
    return (bool(data["grounded"]) and not unsupported), unsupported, "model"


# --- the eval tap --------------------------------------------------------
def ndcg_at_k(ranked_ids: list[str], relevant: set[str], k: int = 10) -> float | None:
    """nDCG@k, or None when there is no labelled relevant set.

    Returning None rather than 0.0 or 1.0 is the whole point: an unmeasured metric
    must not be able to masquerade as a measured one in a dashboard.
    """
    if not relevant:
        return None
    dcg = 0.0
    for idx, row_id in enumerate(ranked_ids[:k], start=1):
        if row_id in relevant:
            dcg += 1.0 / math.log2(idx + 1)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(relevant), k) + 1))
    return round(dcg / ideal, 6) if ideal else None


def recall_at_k(ranked_ids: list[str], relevant: set[str], k: int) -> float | None:
    if not relevant:
        return None
    hit = len(set(ranked_ids[:k]) & relevant)
    return round(hit / len(relevant), 6)
