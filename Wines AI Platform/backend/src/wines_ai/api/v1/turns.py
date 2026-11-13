"""Send a turn, stream it, cancel it."""

from __future__ import annotations

import asyncio
import hashlib
import json

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import StreamingResponse

from ...db.repositories import conversations as conv_repo
from ...db.repositories import logs as logs_repo
from ...db.repositories import messages as messages_repo
from ...db.repositories import profile as profile_repo
from ...deps import AgeGate, ReadyServicesDep, UserDep
from ...errors import ApiProblem, conversation_not_found, turn_in_flight, turn_not_found
from ...schemas import SendMessageRequest, SendMessageResponse
from ...turns.engine import TurnRequest

router = APIRouter(tags=["turns"], dependencies=[AgeGate])

SEND_ENDPOINT = "POST /conversations/{cid}/messages"
KEEPALIVE_SECONDS = 15.0


def _frame(seq: int, name: str, data: dict) -> bytes:
    return f"id: {seq}\nevent: {name}\ndata: {json.dumps(data, default=str)}\n\n".encode()


def _frame_no_id(name: str, data: dict) -> bytes:
    """An informational frame with no `id:`.

    SSE leaves the client's Last-Event-ID untouched when a frame omits `id:`, which is
    exactly right for a frame that reports state rather than carrying content: it must
    not move the resume cursor, and `id:` stays strictly increasing across the stream.
    """
    return f"event: {name}\ndata: {json.dumps(data, default=str)}\n\n".encode()


@router.post(
    "/conversations/{cid}/messages", response_model=SendMessageResponse, status_code=202
)
async def send(
    cid: str,
    body: SendMessageRequest,
    services: ReadyServicesDep,
    user_id: UserDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SendMessageResponse:
    if not idempotency_key:
        raise ApiProblem(
            400,
            "idempotency_key_required",
            "Idempotency-Key required",
            "Send an Idempotency-Key header so a retried send cannot start a second turn.",
        )

    request_hash = hashlib.sha256(
        json.dumps(
            {"cid": cid, "content": body.content, "chip": body.selected_chip_id}, sort_keys=True
        ).encode()
    ).hexdigest()[:32]

    async with services.db.connect() as conn:
        existing = await logs_repo.idempotency_get(
            conn, key=idempotency_key, endpoint=SEND_ENDPOINT
        )
    if existing:
        if existing["request_hash"] != request_hash:
            raise ApiProblem(
                409,
                "idempotency_key_reused",
                "Idempotency-Key reused",
                "That Idempotency-Key was used for a different request body.",
            )
        # Replay: return the original body and start nothing. This is the cheapest
        # cost control in the system - a retried send never pays twice.
        return SendMessageResponse.model_validate(existing["response_json"])

    async with services.db.connect() as conn:
        conversation = await conv_repo.get(conn, user_id=user_id, cid=cid)
    if conversation is None:
        raise conversation_not_found(cid)

    # One in-flight turn per conversation: two concurrent turns drawing on the same
    # seq sequence would interleave their SSE ids and break resume.
    active = services.registry.active_for_conversation(cid)
    if active is not None:
        raise turn_in_flight(active.turn_id)

    from ...db.ids import new_id

    turn_id = new_id("t")
    user_seq = await services.seq.next(cid)

    async with services.db.begin() as conn:
        message = await messages_repo.add_message(
            conn, cid=cid, role="user", seq=user_seq, turn_id=turn_id
        )
        await messages_repo.add_part(
            conn,
            message_id=message["id"],
            cid=cid,
            kind="text",
            seq=await services.seq.next(cid),
            text=body.content,
        )
        # Auto-name from turn 1, mirroring the sidebar's behaviour.
        if conversation["title"] == "New conversation":
            title = body.content.strip()
            limit = services.settings.title_max_chars
            if len(title) > limit:
                title = title[:limit].rstrip() + "..."
            await conv_repo.patch(
                conn, user_id=user_id, cid=cid, title=title or None, archived=None
            )
        else:
            await conv_repo.touch(conn, cid=cid)

        profile_row = await profile_repo.ensure(conn, cid=cid)
        transcript = await messages_repo.transcript(conn, cid=cid)
        previous_row_ids = await messages_repo.last_cited_row_ids(conn, cid=cid)

    skip = ("conversation_id", "confidence_json")
    profile = {k: v for k, v in profile_row.items() if k not in skip}
    asked_count = sum(1 for axis in ("style", "sweetness", "body", "oak") if profile.get(axis))

    entry = services.registry.register(turn_id=turn_id, cid=cid, user_id=user_id)
    req = TurnRequest(
        turn_id=turn_id,
        conversation_id=cid,
        utterance=body.content,
        selected_chip_id=body.selected_chip_id,
        profile=profile,
        history=[
            {"role": m["role"], "seq": m["seq"]} for m in transcript[-10:]
        ],
        previous_row_ids=previous_row_ids,
        asked_count=asked_count,
        dataset_version=conversation["dataset_version"],
    )

    assert services.runner is not None
    entry.task = asyncio.create_task(
        services.runner.run(entry=entry, req=req, user_id=user_id)
    )

    out = SendMessageResponse(turn_id=turn_id, user_message_id=message["id"], seq=user_seq)
    async with services.db.begin() as conn:
        await logs_repo.idempotency_put(
            conn,
            key=idempotency_key,
            endpoint=SEND_ENDPOINT,
            user_id=user_id,
            request_hash=request_hash,
            response_json=out.model_dump(mode="json", by_alias=True),
            turn_id=turn_id,
            retention_seconds=services.settings.idempotency_retention_seconds,
        )
    return out


@router.get("/conversations/{cid}/stream")
async def stream(
    cid: str,
    request: Request,
    services: ReadyServicesDep,
    user_id: UserDep,
    after: int = 0,
) -> StreamingResponse:
    async with services.db.connect() as conn:
        conversation = await conv_repo.get(conn, user_id=user_id, cid=cid)
    if conversation is None:
        raise conversation_not_found(cid)

    queue = services.bus.subscribe(cid)

    async def publisher():
        try:
            # 1. Replay committed parts with seq > after.
            async with services.db.connect() as conn:
                parts = await messages_repo.parts_after(conn, cid=cid, after=after)
            replayed_upto = after
            replayed_count = 0
            for part in parts:
                name, data = _part_to_event(part)
                if name is None:
                    continue
                replayed_upto = max(replayed_upto, part["seq"])
                replayed_count += 1
                yield _frame(part["seq"], name, data)

            # 2. Attach the live buffer of an in-flight turn, so there is no hole
            #    between the last committed part and the live tail.
            active = services.registry.active_for_conversation(cid)
            if active is not None:
                for seq, name, data in list(active.buffer):
                    if seq > replayed_upto:
                        yield _frame(seq, name, data)
                        replayed_upto = max(replayed_upto, seq)
            elif replayed_count:
                # We replayed history and nothing is running, so no `done` will ever
                # arrive for those turns: `usage` and `done` are transport frames and
                # are deliberately not persisted as message parts. Without this, a
                # client that reconnects to a finished conversation renders the
                # transcript and then waits on a spinner forever. `status: "idle"`
                # says the stream is caught up and nothing is pending - derived from
                # the registry, not stored, and it keeps the frame set exactly as the
                # diagram draws it rather than inventing a new event name.
                #
                # Only when something was actually replayed: a client that opens the
                # stream and THEN sends its turn has nothing to catch up on, and an
                # idle frame there would end its read before the turn even starts.
                yield _frame_no_id(
                    "done",
                    {"turn_id": None, "status": "idle", "replay": True, "seq": replayed_upto},
                )

            # 3. Tail.
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
                except TimeoutError:
                    yield b": keep-alive\n\n"
                    continue
                if event is None:
                    break
                if event.seq <= replayed_upto:
                    continue
                replayed_upto = event.seq
                yield _frame(event.seq, event.name, event.data)
        finally:
            services.bus.unsubscribe(cid, queue)

    return StreamingResponse(
        publisher(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _part_to_event(part: dict) -> tuple[str | None, dict]:
    """Map a persisted part back onto its SSE frame for replay.

    A coalesced text part replays as a single `token` event carrying the whole text:
    the client's reducer appends either way, so one big token and many small ones
    render identically.
    """
    kind = part["kind"]
    if kind == "text":
        return "token", {"text": part["text"] or ""}
    if kind == "card":
        return "card", dict(part["card_json"] or {})
    if kind == "chips":
        return "chips", dict(part["chips_json"] or {})
    if kind == "citation":
        return "citation", dict(part["citation_json"] or {})
    if kind == "error":
        return "error", {"detail": part["text"] or ""}
    return None, {}


@router.post("/turns/{turn_id}/cancel", status_code=204)
async def cancel(turn_id: str, services: ReadyServicesDep, user_id: UserDep) -> Response:
    entry = services.registry.get(turn_id)
    if entry is None or entry.user_id != user_id:
        raise turn_not_found(turn_id)
    services.registry.cancel(turn_id)
    return Response(status_code=204)
