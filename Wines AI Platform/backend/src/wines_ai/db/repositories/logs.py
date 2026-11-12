"""transaction_log, retrieval_log, graph_checkpoint, feedback, idempotency_key."""

from __future__ import annotations

import datetime as _dt

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from ..ids import new_id, utcnow
from ..tables import (
    feedback,
    graph_checkpoint,
    idempotency_key,
    intent_eval,
    retrieval_log,
    transaction_log,
)


async def write_turn(
    conn: AsyncConnection,
    *,
    cid: str,
    user_id: str,
    turn_id: str,
    intent: str | None,
    intent_confidence: float | None,
    model: str,
    engine: str,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
    latency_ms: int,
    status: str,
    error_code: str | None = None,
    cache_hit: bool = False,
) -> None:
    await conn.execute(
        transaction_log.insert().values(
            id=new_id("tx"),
            conversation_id=cid,
            user_id=user_id,
            turn_id=turn_id,
            intent=intent,
            intent_confidence=intent_confidence,
            model=model,
            engine=engine,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            status=status,
            error_code=error_code,
            cache_hit=cache_hit,
            created_at=utcnow(),
        )
    )


async def write_retrieval(
    conn: AsyncConnection,
    *,
    turn_id: str,
    stage: str,
    query_text: str | None,
    candidate_row_ids: list[str] | None,
    ranks: list[int] | None = None,
    scores: list[float] | None = None,
) -> None:
    await conn.execute(
        retrieval_log.insert().values(
            id=new_id("r"),
            turn_id=turn_id,
            stage=stage,
            query_text=query_text,
            candidate_row_ids=candidate_row_ids,
            ranks=ranks,
            scores=scores,
            created_at=utcnow(),
        )
    )


async def write_checkpoint(
    conn: AsyncConnection, *, turn_id: str, node: str, state: dict
) -> None:
    await conn.execute(
        graph_checkpoint.insert()
        .prefix_with("OR REPLACE")
        .values(turn_id=turn_id, node=node, state_json=state, created_at=utcnow())
    )


async def write_intent_eval(
    conn: AsyncConnection, *, utterance: str, predicted: str, confidence: float
) -> None:
    """Populated from day one so the intent confusion matrix has data before the
    Haiku router exists. true_intent is filled later by a labeller."""
    await conn.execute(
        intent_eval.insert().values(
            id=new_id("ie"),
            utterance=utterance,
            true_intent=None,
            predicted=predicted,
            confidence=confidence,
            created_at=utcnow(),
        )
    )


async def upsert_feedback(
    conn: AsyncConnection, *, message_id: str, cid: str, row_id: str, vote: str
) -> None:
    existing = (
        (
            await conn.execute(
                select(feedback.c.id).where(
                    and_(feedback.c.message_id == message_id, feedback.c.row_id == row_id)
                )
            )
        )
        .mappings()
        .first()
    )
    if existing:
        from sqlalchemy import update

        await conn.execute(
            update(feedback)
            .where(feedback.c.id == existing["id"])
            .values(vote=vote, created_at=utcnow())
        )
        return
    await conn.execute(
        feedback.insert().values(
            id=new_id("f"),
            message_id=message_id,
            conversation_id=cid,
            row_id=row_id,
            vote=vote,
            created_at=utcnow(),
        )
    )


async def session_usage(conn: AsyncConnection, *, user_id: str) -> dict:
    stmt = select(
        func.count().label("turns"),
        func.coalesce(func.sum(transaction_log.c.tokens_in), 0).label("tokens_in"),
        func.coalesce(func.sum(transaction_log.c.tokens_out), 0).label("tokens_out"),
        func.coalesce(func.sum(transaction_log.c.cost_usd), 0.0).label("cost_usd"),
        func.coalesce(func.sum(transaction_log.c.cache_hit), 0).label("cache_hits"),
    ).where(transaction_log.c.user_id == user_id)
    row = (await conn.execute(stmt)).mappings().first()
    return dict(row) if row else {}


async def global_cost_today(conn: AsyncConnection) -> float:
    start = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT00:00:00Z")
    total = await conn.scalar(
        select(func.coalesce(func.sum(transaction_log.c.cost_usd), 0.0)).where(
            transaction_log.c.created_at >= start
        )
    )
    return float(total or 0.0)


async def idempotency_get(
    conn: AsyncConnection, *, key: str, endpoint: str
) -> dict | None:
    stmt = select(idempotency_key).where(
        and_(idempotency_key.c.key == key, idempotency_key.c.endpoint == endpoint)
    )
    result = (await conn.execute(stmt)).mappings().first()
    if not result:
        return None
    row = dict(result)
    if row["expires_at"] < utcnow():
        return None
    return row


async def idempotency_put(
    conn: AsyncConnection,
    *,
    key: str,
    endpoint: str,
    user_id: str,
    request_hash: str,
    response_json: dict,
    turn_id: str,
    retention_seconds: int,
) -> None:
    expires = (
        _dt.datetime.now(_dt.UTC) + _dt.timedelta(seconds=retention_seconds)
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    await conn.execute(
        idempotency_key.insert()
        .prefix_with("OR REPLACE")
        .values(
            key=key,
            endpoint=endpoint,
            user_id=user_id,
            request_hash=request_hash,
            response_json=response_json,
            turn_id=turn_id,
            created_at=utcnow(),
            expires_at=expires,
        )
    )
