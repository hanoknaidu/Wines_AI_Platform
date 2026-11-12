"""Conversation reads and writes. Every method takes user_id; there is no unscoped read."""

from __future__ import annotations

import base64
import json

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from ..ids import new_id, utcnow
from ..tables import conversation


def encode_cursor(updated_at: str, cid: str) -> str:
    raw = json.dumps([updated_at, cid]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, str] | None:
    try:
        pad = "=" * (-len(cursor) % 4)
        updated_at, cid = json.loads(base64.urlsafe_b64decode(cursor + pad))
        return str(updated_at), str(cid)
    except Exception:  # noqa: BLE001
        return None


async def create(
    conn: AsyncConnection, *, user_id: str, title: str, dataset_version: str
) -> dict:
    now = utcnow()
    row = {
        "id": new_id("c"),
        "user_id": user_id,
        "title": title,
        "created_at": now,
        "updated_at": now,
        "archived_at": None,
        "deleted_at": None,
        "dataset_version": dataset_version,
    }
    await conn.execute(conversation.insert().values(**row))
    return row


async def get(conn: AsyncConnection, *, user_id: str, cid: str) -> dict | None:
    stmt = select(conversation).where(
        and_(
            conversation.c.id == cid,
            conversation.c.user_id == user_id,
            conversation.c.deleted_at.is_(None),
        )
    )
    result = (await conn.execute(stmt)).mappings().first()
    return dict(result) if result else None


async def list_page(
    conn: AsyncConnection,
    *,
    user_id: str,
    limit: int,
    cursor: str | None = None,
    archived: bool = False,
    q: str | None = None,
) -> tuple[list[dict], str | None]:
    conditions = [conversation.c.user_id == user_id, conversation.c.deleted_at.is_(None)]
    if archived:
        conditions.append(conversation.c.archived_at.is_not(None))
    else:
        conditions.append(conversation.c.archived_at.is_(None))
    if q:
        conditions.append(conversation.c.title.ilike(f"%{q}%"))

    # Keyset pagination: strictly after (updated_at, id) descending. Offset paging would
    # skip or duplicate rows while live turns bump updated_at mid-scroll.
    if cursor and (decoded := decode_cursor(cursor)):
        last_updated, last_id = decoded
        conditions.append(
            (conversation.c.updated_at < last_updated)
            | and_(conversation.c.updated_at == last_updated, conversation.c.id < last_id)
        )

    stmt = (
        select(conversation)
        .where(and_(*conditions))
        .order_by(conversation.c.updated_at.desc(), conversation.c.id.desc())
        .limit(limit + 1)
    )
    rows = [dict(r) for r in (await conn.execute(stmt)).mappings().all()]
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = encode_cursor(rows[-1]["updated_at"], rows[-1]["id"])
    return rows, next_cursor


async def touch(conn: AsyncConnection, *, cid: str) -> None:
    await conn.execute(
        update(conversation).where(conversation.c.id == cid).values(updated_at=utcnow())
    )


async def patch(
    conn: AsyncConnection,
    *,
    user_id: str,
    cid: str,
    title: str | None,
    archived: bool | None,
) -> dict | None:
    values: dict[str, object] = {}
    if title is not None:
        values["title"] = title
    if archived is not None:
        values["archived_at"] = utcnow() if archived else None
    if values:
        values["updated_at"] = utcnow()
        await conn.execute(
            update(conversation)
            .where(
                and_(
                    conversation.c.id == cid,
                    conversation.c.user_id == user_id,
                    conversation.c.deleted_at.is_(None),
                )
            )
            .values(**values)
        )
    return await get(conn, user_id=user_id, cid=cid)


async def soft_delete(conn: AsyncConnection, *, user_id: str, cid: str) -> bool:
    result = await conn.execute(
        update(conversation)
        .where(
            and_(
                conversation.c.id == cid,
                conversation.c.user_id == user_id,
                conversation.c.deleted_at.is_(None),
            )
        )
        .values(deleted_at=utcnow())
    )
    return bool(result.rowcount)
