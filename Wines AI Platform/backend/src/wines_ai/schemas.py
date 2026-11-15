"""The whole wire contract.

Casing: `wire_case` decides what is emitted. `snake` (the default) matches the
architecture diagram, which writes turn_id / row_id / dataset_version. `camel` emits
camelCase. Input accepts BOTH spellings under either setting, because
`populate_by_name` is on - so a frontend typed against the wrong one still posts
successfully, and only the response shape changes. That is what makes the choice free.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .config import get_settings

Vote = Literal["up", "down"]
Role = Literal["user", "assistant"]
PartKind = Literal["text", "card", "chips", "citation", "error"]
Intent = Literal["interview", "recommend", "refine", "out_of_scope"]
TurnStatus = Literal["ok", "cancelled", "error"]


def _to_camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(word.capitalize() for word in rest)


def _alias(name: str) -> str:
    return _to_camel(name) if get_settings().wire_case == "camel" else name


class Wire(BaseModel):
    """Base for everything on the wire. One alias generator, one switch."""

    model_config = ConfigDict(alias_generator=_alias, populate_by_name=True)


# --- age gate ------------------------------------------------------------


class AgeGateRequest(Wire):
    confirmed: bool


# --- conversations -------------------------------------------------------


class ConversationSummary(Wire):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    archived: bool = False
    dataset_version: str


class ConversationPage(Wire):
    items: list[ConversationSummary]
    next_cursor: str | None = None


class CreateConversationRequest(Wire):
    title: str | None = None


class PatchConversationRequest(Wire):
    title: str | None = None
    archived: bool | None = None


class AxisReading(Wire):
    """One taste axis as served. `label` is already hedged where confidence is low."""

    value: str
    confidence: float
    label: str


class Card(Wire):
    row_id: str
    variety: str
    style: str
    axes: dict[str, AxisReading]
    description: str
    why_it_matches: str
    typical_regions: list[str] = Field(default_factory=list)
    example_producers: list[str] = Field(default_factory=list)
    review_status: str
    dataset_version: str


class ChipOption(Wire):
    id: str
    label: str
    value: str | None = None


class Chips(Wire):
    kind: Literal["interview", "refine"]
    axis: str | None = None
    prompt: str | None = None
    options: list[ChipOption]


class MessagePart(Wire):
    id: str
    kind: PartKind
    seq: int
    text: str | None = None
    card: Card | None = None
    chips: Chips | None = None
    citation: dict[str, Any] | None = None
    row_id: str | None = None


class Message(Wire):
    id: str
    role: Role
    seq: int
    turn_id: str | None = None
    created_at: datetime
    parts: list[MessagePart] = Field(default_factory=list)


class TasteProfile(Wire):
    style: str | None = None
    sweetness: str | None = None
    body: str | None = None
    oak: str | None = None
    tannin: str | None = None
    acidity: str | None = None
    fruit_savoury: str | None = None
    confidence: dict[str, Any] = Field(default_factory=dict)


class ConversationDetail(Wire):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    archived: bool
    dataset_version: str
    dataset_version_stale: bool = False
    served_dataset_version: str
    taste_profile: TasteProfile
    messages: list[Message]


# --- turns ---------------------------------------------------------------


class SendMessageRequest(Wire):
    content: Annotated[str, Field(min_length=1, max_length=2000)]
    selected_chip_id: str | None = None


class SendMessageResponse(Wire):
    turn_id: str
    user_message_id: str
    seq: int


# --- feedback ------------------------------------------------------------


class FeedbackRequest(Wire):
    row_id: str
    vote: Vote


# --- meta ----------------------------------------------------------------


class AxisLevel(Wire):
    value: str
    label: str
    hedged_label: str


class AxisSpec(Wire):
    id: str
    asked: bool
    question_order: int | None = None
    prompt: str | None = None
    applies_to: list[str] = Field(default_factory=list)
    levels: list[AxisLevel]


class RefineChip(Wire):
    id: str
    label: str
    axis: str
    delta: int


class TasteAxesResponse(Wire):
    axes: list[AxisSpec]
    refine_chips: list[RefineChip]
    confidence_threshold: float
    styles: list[ChipOption]


class DatasetVersionResponse(Wire):
    dataset_version: str
    row_count: int
    review_status_counts: dict[str, int]
    built_at: str | None = None
    checksum: str


class UsageResponse(Wire):
    """Session-scoped spend. Cost is only ever visible if something reports it."""

    turns: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    engine: str
    cache_hits: int
    ceiling_per_session_usd: float
    degraded: bool


# --- platform ------------------------------------------------------------


class HealthResponse(Wire):
    status: Literal["ok"]


class ReadyResponse(Wire):
    status: Literal["ready", "not_ready"]
    db: str
    dataset_version: str | None = None
    row_count: int = 0
    indexes: dict[str, int] = Field(default_factory=dict)
    engine: str = "deterministic"
    # What the serving path actually is: the provider behind the orchestrated engine,
    # its four model ids, and the retrieval indexes it loaded. Absent for the
    # deterministic engine, which has none of those. Readiness has to answer "ready to
    # serve WHAT" - an orchestrated engine whose indexes failed to build is up, and
    # cannot retrieve.
    serving: dict[str, Any] = Field(default_factory=dict)
