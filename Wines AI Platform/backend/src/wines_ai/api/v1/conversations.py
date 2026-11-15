"""Conversation CRUD. Every query is session-scoped."""

from __future__ import annotations

from fastapi import APIRouter, Query, Response

from ...db.ids import parse_ts
from ...db.repositories import conversations as repo
from ...db.repositories import messages as messages_repo
from ...db.repositories import profile as profile_repo
from ...deps import AgeGate, ReadyServicesDep, UserDep
from ...errors import ApiProblem, conversation_not_found
from ...schemas import (
    Card,
    Chips,
    ConversationDetail,
    ConversationPage,
    ConversationSummary,
    CreateConversationRequest,
    Message,
    MessagePart,
    PatchConversationRequest,
    TasteProfile,
)

router = APIRouter(prefix="/conversations", tags=["conversations"], dependencies=[AgeGate])

DEFAULT_TITLE = "New conversation"


def _checked_title(title: str | None, limit: int) -> str | None:
    """Validate a client-supplied title against `title_max_chars`.

    The limit existed but was enforced in exactly one place - the auto-naming path in
    `turns.py`, which truncates a generated title. A title the CLIENT sends went
    straight to the column unchecked, so `POST /conversations` and `PATCH` both
    accepted and stored 500 characters while every reader assumed 52.

    Refused rather than truncated: silently rewriting a name someone typed is worse
    than telling them it is too long, and the frontend already caps its rename box at
    the same number, so a 422 here only ever means a non-browser client or a bug.

    A supplied-but-blank title is refused for the same reason - `repo.patch` writes any
    non-None value, so `{"title": ""}` would blank the sidebar entry with no way back.
    Omit the field to leave the title alone; that is what `None` is for.
    """
    if title is None:
        return None
    cleaned = title.strip()
    if not cleaned:
        raise ApiProblem(
            422,
            "title_blank",
            "Title cannot be blank",
            "Omit the title field to leave it unchanged.",
        )
    if len(cleaned) > limit:
        raise ApiProblem(
            422,
            "title_too_long",
            "Title too long",
            f"A conversation title is at most {limit} characters; that one is {len(cleaned)}.",
        )
    return cleaned


def _summary(row: dict) -> ConversationSummary:
    return ConversationSummary(
        id=row["id"],
        title=row["title"],
        created_at=parse_ts(row["created_at"]),
        updated_at=parse_ts(row["updated_at"]),
        archived=row["archived_at"] is not None,
        dataset_version=row["dataset_version"],
    )


@router.post("", response_model=ConversationSummary, status_code=201)
async def create(
    body: CreateConversationRequest, services: ReadyServicesDep, user_id: UserDep
) -> ConversationSummary:
    assert services.index is not None
    title = _checked_title(body.title, services.settings.title_max_chars)
    async with services.db.begin() as conn:
        row = await repo.create(
            conn,
            user_id=user_id,
            title=title or DEFAULT_TITLE,
            # Pinned at creation so a transcript records which artifact it was served from.
            dataset_version=services.index.version,
        )
        await profile_repo.ensure(conn, cid=row["id"])
    return _summary(row)


@router.get("", response_model=ConversationPage)
async def list_conversations(
    services: ReadyServicesDep,
    user_id: UserDep,
    cursor: str | None = None,
    limit: int | None = None,
    archived: bool = False,
    q: str | None = Query(default=None, max_length=120),
) -> ConversationPage:
    settings = services.settings
    size = min(limit or settings.conversation_page_size, settings.conversation_page_size_max)
    async with services.db.connect() as conn:
        rows, next_cursor = await repo.list_page(
            conn, user_id=user_id, limit=size, cursor=cursor, archived=archived, q=q
        )
    return ConversationPage(items=[_summary(r) for r in rows], next_cursor=next_cursor)


@router.get("/{cid}", response_model=ConversationDetail)
async def get_conversation(
    cid: str, services: ReadyServicesDep, user_id: UserDep
) -> ConversationDetail:
    assert services.index is not None
    async with services.db.connect() as conn:
        row = await repo.get(conn, user_id=user_id, cid=cid)
        if row is None:
            raise conversation_not_found(cid)
        msgs = await messages_repo.transcript(conn, cid=cid)
        prof = await profile_repo.get(conn, cid=cid) or {}

    messages: list[Message] = []
    for msg in msgs:
        parts: list[MessagePart] = []
        for part in msg["parts"]:
            parts.append(
                MessagePart(
                    id=part["id"],
                    kind=part["kind"],
                    seq=part["seq"],
                    text=part["text"],
                    card=Card.model_validate(part["card_json"]) if part["card_json"] else None,
                    chips=Chips.model_validate(part["chips_json"]) if part["chips_json"] else None,
                    citation=part["citation_json"],
                    row_id=part["row_id"],
                )
            )
        messages.append(
            Message(
                id=msg["id"],
                role=msg["role"],
                seq=msg["seq"],
                turn_id=msg["turn_id"],
                created_at=parse_ts(msg["created_at"]),
                parts=parts,
            )
        )

    served = services.index.version
    return ConversationDetail(
        id=row["id"],
        title=row["title"],
        created_at=parse_ts(row["created_at"]),
        updated_at=parse_ts(row["updated_at"]),
        archived=row["archived_at"] is not None,
        dataset_version=row["dataset_version"],
        # Reported rather than silently re-served under a different artifact.
        dataset_version_stale=row["dataset_version"] != served,
        served_dataset_version=served,
        taste_profile=TasteProfile(
            style=prof.get("style"),
            sweetness=prof.get("sweetness"),
            body=prof.get("body"),
            oak=prof.get("oak"),
            tannin=prof.get("tannin"),
            acidity=prof.get("acidity"),
            fruit_savoury=prof.get("fruit_savoury"),
            confidence=prof.get("confidence_json") or {},
        ),
        messages=messages,
    )


@router.patch("/{cid}", response_model=ConversationSummary)
async def patch_conversation(
    cid: str, body: PatchConversationRequest, services: ReadyServicesDep, user_id: UserDep
) -> ConversationSummary:
    title = _checked_title(body.title, services.settings.title_max_chars)
    async with services.db.begin() as conn:
        row = await repo.patch(
            conn, user_id=user_id, cid=cid, title=title, archived=body.archived
        )
    if row is None:
        raise conversation_not_found(cid)
    return _summary(row)


@router.delete("/{cid}", status_code=204)
async def delete_conversation(
    cid: str, services: ReadyServicesDep, user_id: UserDep
) -> Response:
    async with services.db.begin() as conn:
        deleted = await repo.soft_delete(conn, user_id=user_id, cid=cid)
    if not deleted:
        raise conversation_not_found(cid)
    return Response(status_code=204)
