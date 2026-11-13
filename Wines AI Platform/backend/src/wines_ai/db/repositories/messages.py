"""Messages and parts. seq is allocated inside the write transaction, never from
application state - a gap or a duplicate breaks the SSE `?after=` contract."""

from __future__ import annotations

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from ..ids import new_id, utcnow
from ..tables import message, message_part


async def max_seq(conn: AsyncConnection, *, cid: str) -> int:
    """Highest seq used by this conversation, across messages and parts.

    Both tables draw from one sequence so an SSE `id:` is globally ordered within the
    conversation regardless of which kind of row produced it. This is only used to
    PRIME the in-process allocator in services/seq.py - it is not called per event.
    """
    msg_max = await conn.scalar(
        select(func.coalesce(func.max(message.c.seq), 0)).where(message.c.conversation_id == cid)
    )
    part_max = await conn.scalar(
        select(func.coalesce(func.max(message_part.c.seq), 0)).where(
            message_part.c.conversation_id == cid
        )
    )
    return max(int(msg_max or 0), int(part_max or 0))


async def add_message(
    conn: AsyncConnection, *, cid: str, role: str, seq: int, turn_id: str | None
) -> dict:
    row = {
        "id": new_id("m"),
        "conversation_id": cid,
        "role": role,
        "seq": seq,
        "turn_id": turn_id,
        "created_at": utcnow(),
    }
    await conn.execute(message.insert().values(**row))
    return row


async def add_part(
    conn: AsyncConnection,
    *,
    message_id: str,
    cid: str,
    kind: str,
    seq: int,
    text: str | None = None,
    card_json: dict | None = None,
    chips_json: dict | None = None,
    row_id: str | None = None,
    citation_json: dict | None = None,
) -> dict:
    row = {
        "id": new_id("p"),
        "message_id": message_id,
        "conversation_id": cid,
        "kind": kind,
        "seq": seq,
        "text": text,
        "card_json": card_json,
        "chips_json": chips_json,
        "row_id": row_id,
        "citation_json": citation_json,
    }
    await conn.execute(message_part.insert().values(**row))
    return row


async def transcript(conn: AsyncConnection, *, cid: str) -> list[dict]:
    msgs = [
        dict(r)
        for r in (
            await conn.execute(
                select(message)
                .where(message.c.conversation_id == cid)
                .order_by(message.c.seq.asc())
            )
        )
        .mappings()
        .all()
    ]
    parts = [
        dict(r)
        for r in (
            await conn.execute(
                select(message_part)
                .where(message_part.c.conversation_id == cid)
                .order_by(message_part.c.seq.asc())
            )
        )
        .mappings()
        .all()
    ]
    by_message: dict[str, list[dict]] = {}
    for part in parts:
        by_message.setdefault(part["message_id"], []).append(part)
    for msg in msgs:
        msg["parts"] = by_message.get(msg["id"], [])
    return msgs


async def parts_after(conn: AsyncConnection, *, cid: str, after: int) -> list[dict]:
    """Committed parts with seq > after - the replay half of stream resume."""
    stmt = (
        select(message_part)
        .where(and_(message_part.c.conversation_id == cid, message_part.c.seq > after))
        .order_by(message_part.c.seq.asc())
    )
    return [dict(r) for r in (await conn.execute(stmt)).mappings().all()]


async def message_row_ids(conn: AsyncConnection, *, message_id: str) -> set[str]:
    """Row ids this message actually cited - the guard behind feedback's 409."""
    stmt = select(message_part.c.row_id).where(
        and_(message_part.c.message_id == message_id, message_part.c.row_id.is_not(None))
    )
    return {r[0] for r in (await conn.execute(stmt)).all() if r[0]}


async def get_message(conn: AsyncConnection, *, message_id: str) -> dict | None:
    result = (
        (await conn.execute(select(message).where(message.c.id == message_id))).mappings().first()
    )
    return dict(result) if result else None


async def last_cited_row_ids(conn: AsyncConnection, *, cid: str) -> list[str]:
    """Row ids from the most recent assistant turn that produced cards.

    This is the anchor for refine: the correction re-ranks what the user actually saw,
    not a fresh search.
    """
    last_turn = await conn.scalar(
        select(message.c.turn_id)
        .where(and_(message.c.conversation_id == cid, message.c.role == "assistant"))
        .order_by(message.c.seq.desc())
        .limit(1)
    )
    if not last_turn:
        return []
    stmt = (
        select(message_part.c.row_id)
        .join(message, message.c.id == message_part.c.message_id)
        .where(
            and_(
                message.c.turn_id == last_turn,
                message_part.c.kind == "card",
                message_part.c.row_id.is_not(None),
            )
        )
        .order_by(message_part.c.seq.asc())
    )
    return [r[0] for r in (await conn.execute(stmt)).all() if r[0]]
