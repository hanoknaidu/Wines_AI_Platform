"""Stage I: the context packer. The generator sees this and nothing else.

Three jobs, in order:

1. **Enforce the token budget.** `context_token_budget` is 8K, and the reason is in
   `pricing.py`: Haiku 5.5 is tier-priced, and a prompt over 100K tokens costs 5x per
   input token. The budget is nowhere near that line, which is the point - it stays
   there by construction rather than by luck.
2. **Collapse near-duplicates.** Two rows of the same variety and style with the same
   axes are one row as far as the generator is concerned, and packing both spends
   budget to say the same thing twice.
3. **Pack a fixed field set, ordered by score.** Each row arrives carrying exactly:
   row_id, the seven axes with per-axis confidence, the description, regions,
   producers, review_status and dataset_version. Nothing else is in the prompt - no
   conversation, no instructions, no other row's text - because the generator cannot
   reach the index and must not be able to infer anything it was not handed.

The row_id goes first on every line. That is what makes the verifier's job checkable:
a claim either names an id that is in this block or it does not.
"""

from __future__ import annotations

from ...dataset.schema import WineRow
from ..gateway import estimate_tokens
from .types import Candidate, PackedContext, PackedRow


def _signature(row: WineRow) -> tuple:
    """What makes two rows near-duplicates for packing purposes."""
    return (
        row.variety.split("(")[0].strip().lower(),
        row.style,
        row.sweetness,
        row.body,
        row.oak,
        row.tannin,
        row.acidity,
        row.fruit_savoury,
    )


def render_row(row: WineRow, *, threshold: float) -> str:
    """One row, as the generator sees it.

    Confidence is rendered as a word rather than a number: the generator's job is to
    hedge a low-confidence axis in prose, and "0.62" invites it to quote the number at
    a user, which means nothing to them.
    """
    axes = []
    for axis_id in ("sweetness", "body", "oak", "tannin", "acidity", "fruit_savoury"):
        value = getattr(row, axis_id)
        confidence = row.confidence_for(axis_id)
        marker = "certain" if confidence >= threshold else "uncertain"
        axes.append(f"{axis_id}={value} ({marker})")

    producers = ", ".join(row.example_producers) if row.example_producers else "(none on file)"
    regions = ", ".join(row.typical_regions) if row.typical_regions else "(none on file)"
    return "\n".join(
        [
            f"row_id: {row.row_id}",
            f"variety: {row.variety}",
            f"style: {row.style}",
            f"axes: {'; '.join(axes)}",
            f"description: {row.description}",
            f"typical_regions: {regions}",
            f"example_producers: {producers}",
            f"review_status: {row.review_status}",
            f"dataset_version: {row.dataset_version}",
        ]
    )


def pack(
    candidates: list[Candidate], *, budget: int, threshold: float
) -> PackedContext:
    out = PackedContext(budget=budget)
    seen: dict[tuple, str] = {}

    for candidate in candidates:
        signature = _signature(candidate.row)
        if signature in seen:
            out.collapsed_row_ids.append(candidate.row_id)
            continue

        text = render_row(candidate.row, threshold=threshold)
        tokens = estimate_tokens(text)
        if out.tokens + tokens > budget:
            # Dropped rather than truncated: half a row is a row whose axes might be
            # missing, and a generator that cannot see an axis will not hedge it.
            out.dropped_row_ids.append(candidate.row_id)
            continue

        seen[signature] = candidate.row_id
        out.rows.append(PackedRow(row_id=candidate.row_id, text=text, tokens=tokens))
        out.tokens += tokens

    return out
