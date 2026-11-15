"""taste_profile: one upserted row per conversation.

confidence_json records per-axis confidence AND provenance (asked / inferred /
refined). Provenance is what lets the interview know not to re-ask an axis and the
refine step know which axis the user has actually touched.
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from ..tables import taste_profile

AXES = ("style", "sweetness", "body", "oak", "tannin", "acidity", "fruit_savoury")


async def ensure(conn: AsyncConnection, *, cid: str) -> dict:
    existing = await get(conn, cid=cid)
    if existing:
        return existing
    row = {"conversation_id": cid, "confidence_json": {}}
    for axis in AXES:
        row[axis] = None
    await conn.execute(taste_profile.insert().values(**row))
    return row


async def get(conn: AsyncConnection, *, cid: str) -> dict | None:
    stmt = select(taste_profile).where(taste_profile.c.conversation_id == cid)
    result = (await conn.execute(stmt)).mappings().first()
    return dict(result) if result else None


async def merge(
    conn: AsyncConnection,
    *,
    cid: str,
    values: dict[str, str | None],
    confidence: dict[str, dict] | None = None,
) -> dict:
    current = await ensure(conn, cid=cid)
    patch = {k: v for k, v in values.items() if k in AXES}
    merged_confidence = dict(current.get("confidence_json") or {})
    if confidence:
        merged_confidence.update(confidence)
    patch["confidence_json"] = merged_confidence
    await conn.execute(
        update(taste_profile).where(taste_profile.c.conversation_id == cid).values(**patch)
    )
    return await get(conn, cid=cid) or current
