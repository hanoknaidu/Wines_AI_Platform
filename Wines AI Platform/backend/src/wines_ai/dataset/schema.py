"""The frozen-row schema and its validator (NFR-6).

This is the real schema band 4 produces, not a reduced fixture shape - which is what
makes swapping in the reviewed artifact a path change rather than a code change.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..taste.axes import AXES_BY_ID, STYLES

# "fixture" is a fourth state, and the only one that carries producer names without a
# human signature. It exists so a demo artifact can populate `example_producers`
# without ever claiming the review that makes a producer name trustworthy (section 9):
# the names are illustrative, generated rather than verified, and every surface that
# renders a card has to say so. It is deliberately NOT a synonym for "reviewed" - it
# sorts with "unreviewed" everywhere the UI draws a distinction.
ReviewStatus = Literal["unreviewed", "reviewed", "corrected", "fixture"]

# The states that assert a person checked the row, and therefore require a signature.
SIGNED_STATUSES = ("reviewed", "corrected")

AXIS_FIELDS = ("sweetness", "body", "oak", "tannin", "acidity", "fruit_savoury")


class WineRow(BaseModel):
    """One grape-variety-and-style row. Strict: an unknown field is a failed build."""

    model_config = ConfigDict(extra="forbid")

    row_id: str = Field(min_length=1)
    variety: str = Field(min_length=1)
    style: str
    sweetness: str
    body: str
    oak: str
    tannin: str
    acidity: str
    fruit_savoury: str
    confidence: dict[str, float] = Field(default_factory=dict)
    description: str = Field(min_length=1)
    typical_regions: list[str] = Field(default_factory=list)
    example_producers: list[str] = Field(default_factory=list)
    review_status: ReviewStatus = "unreviewed"
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    dataset_version: str

    @field_validator("style")
    @classmethod
    def _known_style(cls, v: str) -> str:
        if v not in STYLES:
            raise ValueError(f"unknown style {v!r}; expected one of {STYLES}")
        return v

    @model_validator(mode="after")
    def _known_levels_and_confidence(self) -> WineRow:
        for axis_id in AXIS_FIELDS:
            value = getattr(self, axis_id)
            axis = AXES_BY_ID[axis_id]
            allowed = [level.value for level in axis.levels]
            if value not in allowed:
                raise ValueError(f"{self.row_id}: {axis_id}={value!r} not in {allowed}")
        for axis_id, conf in self.confidence.items():
            if axis_id not in AXIS_FIELDS:
                raise ValueError(f"{self.row_id}: confidence for unknown axis {axis_id!r}")
            if not 0.0 <= conf <= 1.0:
                raise ValueError(f"{self.row_id}: confidence {conf} out of range for {axis_id}")
        # A reviewed row must say who reviewed it. Producer names are only trustworthy
        # because of that signature (BRD section 8), so an unsigned review is rejected.
        if self.review_status in SIGNED_STATUSES and not self.reviewed_by:
            raise ValueError(f"{self.row_id}: review_status={self.review_status} needs reviewed_by")
        # The converse, which is the trap "fixture" introduces: a fixture row must NOT
        # carry a signature. Without this, populating producers and then stamping a
        # reviewer name would forge exactly the signature this schema exists to protect.
        if self.review_status == "fixture" and self.reviewed_by:
            raise ValueError(
                f"{self.row_id}: review_status=fixture cannot carry reviewed_by="
                f"{self.reviewed_by!r}; a fixture row is unverified by definition"
            )
        return self

    def confidence_for(self, axis_id: str) -> float:
        return float(self.confidence.get(axis_id, 0.5))


class DatasetArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version: str
    built_at: str | None = None
    notes: str | None = None
    rows: list[WineRow]

    @model_validator(mode="after")
    def _unique_ids_and_matching_version(self) -> DatasetArtifact:
        seen: set[str] = set()
        for row in self.rows:
            if row.row_id in seen:
                raise ValueError(f"duplicate row_id {row.row_id!r}")
            seen.add(row.row_id)
            if row.dataset_version != self.dataset_version:
                raise ValueError(
                    f"{row.row_id}: dataset_version {row.dataset_version!r} "
                    f"does not match artifact {self.dataset_version!r}"
                )
        return self
