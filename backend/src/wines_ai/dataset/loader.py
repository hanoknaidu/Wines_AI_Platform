"""Load, validate and index the frozen dataset at startup.

A few hundred rows scan in single-digit milliseconds, so Phase 1 needs no vector
store, no FTS table and no sqlite-vec - exactly as band 3 specifies. The indexes here
are the ones the deterministic engine reads.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from ..observability import log
from .schema import DatasetArtifact, WineRow

logger = logging.getLogger("wines_ai.dataset")


@dataclass
class DatasetIndex:
    version: str
    checksum: str
    built_at: str | None
    rows: list[WineRow]
    by_row_id: dict[str, WineRow] = field(default_factory=dict)
    by_style: dict[str, list[WineRow]] = field(default_factory=dict)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def review_status_counts(self) -> dict[str, int]:
        return dict(Counter(row.review_status for row in self.rows))

    def resolve(self, row_id: str) -> WineRow | None:
        """The grounding guard's lookup. If this returns None the claim does not ship."""
        return self.by_row_id.get(row_id)

    def for_style(self, style: str) -> list[WineRow]:
        return self.by_style.get(style, [])

    def index_sizes(self) -> dict[str, int]:
        return {"by_row_id": len(self.by_row_id), **{
            f"style:{style}": len(rows) for style, rows in sorted(self.by_style.items())
        }}


class DatasetError(RuntimeError):
    pass


def load(path: Path) -> DatasetIndex:
    if not path.exists():
        raise DatasetError(f"dataset artifact not found at {path}")
    raw = path.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()[:16]
    try:
        artifact = DatasetArtifact.model_validate(json.loads(raw))
    except Exception as exc:  # noqa: BLE001
        # Fail loudly: booting with a half-loaded index would let an ungrounded
        # recommendation out, which is the one thing the design exists to prevent.
        raise DatasetError(f"{path.name} failed validation: {exc}") from exc

    index = DatasetIndex(
        version=artifact.dataset_version,
        checksum=checksum,
        built_at=artifact.built_at,
        rows=artifact.rows,
    )
    for row in artifact.rows:
        index.by_row_id[row.row_id] = row
        index.by_style.setdefault(row.style, []).append(row)

    log(
        logger,
        logging.INFO,
        "dataset_loaded",
        dataset_version=index.version,
        row_count=index.row_count,
        checksum=checksum,
        review_status=index.review_status_counts,
    )
    return index
