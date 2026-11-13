"""FR-9: a thumbs up or down per recommendation, against a row_id."""

from __future__ import annotations

from fastapi import APIRouter, Response

from ...db.repositories import logs as logs_repo
from ...db.repositories import messages as messages_repo
from ...deps import AgeGate, ReadyServicesDep, UserDep
from ...errors import ApiProblem
from ...schemas import FeedbackRequest

router = APIRouter(tags=["feedback"], dependencies=[AgeGate])


@router.post("/messages/{mid}/feedback", status_code=204)
async def vote(
    mid: str, body: FeedbackRequest, services: ReadyServicesDep, user_id: UserDep
) -> Response:
    from ...db.repositories import conversations as conv_repo

    async with services.db.connect() as conn:
        message = await messages_repo.get_message(conn, message_id=mid)
        if message is None:
            raise ApiProblem(404, "message_not_found", "Message not found", f"No message {mid}.")
        # Scope check: a message in someone else's conversation does not exist here.
        conversation = await conv_repo.get(
            conn, user_id=user_id, cid=message["conversation_id"]
        )
        if conversation is None:
            raise ApiProblem(404, "message_not_found", "Message not found", f"No message {mid}.")
        cited = await messages_repo.message_row_ids(conn, message_id=mid)

    # A vote against a row the message never cited is either a client bug or a forged
    # request, and silently accepting it poisons the only honest signal collected here.
    if body.row_id not in cited:
        raise ApiProblem(
            409,
            "row_not_cited",
            "Row not cited by that message",
            f"Message {mid} did not cite row {body.row_id}.",
        )

    async with services.db.begin() as conn:
        await logs_repo.upsert_feedback(
            conn,
            message_id=mid,
            cid=message["conversation_id"],
            row_id=body.row_id,
            vote=body.vote,
        )
    return Response(status_code=204)
