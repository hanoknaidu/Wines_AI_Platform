"""In-flight turns: one per conversation, cancellable, expiring.

One in-flight turn per conversation is a correctness requirement, not a policy: two
concurrent turns drawing from the same per-conversation seq counter would interleave
their SSE ids, and the resume contract depends on that sequence being monotonic.
It is also a cost control - a second send cannot start a second paid turn.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field


@dataclass
class InFlight:
    turn_id: str
    conversation_id: str
    user_id: str
    started_at: float
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None
    # Tokens already streamed but not yet committed, with the seq they were sent under.
    # This is what closes the gap between the last committed part and the live tail
    # when a client reconnects mid-turn.
    buffer: list[tuple[int, str, dict]] = field(default_factory=list)


class TurnRegistry:
    def __init__(self, *, expiry_seconds: int) -> None:
        self.expiry = expiry_seconds
        self._by_turn: dict[str, InFlight] = {}
        self._by_conversation: dict[str, str] = {}

    def _expired(self, entry: InFlight) -> bool:
        return (time.monotonic() - entry.started_at) > self.expiry

    def active_for_conversation(self, cid: str) -> InFlight | None:
        turn_id = self._by_conversation.get(cid)
        if turn_id is None:
            return None
        entry = self._by_turn.get(turn_id)
        if entry is None:
            self._by_conversation.pop(cid, None)
            return None
        if self._expired(entry):
            self.finish(turn_id)
            return None
        return entry

    def register(self, *, turn_id: str, cid: str, user_id: str) -> InFlight:
        entry = InFlight(
            turn_id=turn_id, conversation_id=cid, user_id=user_id, started_at=time.monotonic()
        )
        self._by_turn[turn_id] = entry
        self._by_conversation[cid] = turn_id
        return entry

    def get(self, turn_id: str) -> InFlight | None:
        entry = self._by_turn.get(turn_id)
        if entry and self._expired(entry):
            self.finish(turn_id)
            return None
        return entry

    def finish(self, turn_id: str) -> None:
        entry = self._by_turn.pop(turn_id, None)
        if entry and self._by_conversation.get(entry.conversation_id) == turn_id:
            self._by_conversation.pop(entry.conversation_id, None)

    def cancel(self, turn_id: str) -> bool:
        entry = self.get(turn_id)
        if entry is None:
            return False
        entry.cancel.set()
        if entry.task is not None:
            entry.task.cancel()
        return True

    def cancel_all(self) -> None:
        for turn_id in list(self._by_turn):
            self.cancel(turn_id)
