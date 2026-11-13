"""Per-conversation SSE fan-out.

Resume is the hard part and it has three stages, in this order:
  1. replay committed parts with seq > after (from the database),
  2. attach the live buffer of any in-flight turn (tokens sent but not yet committed),
  3. tail new events.

Doing only (1) and (3) leaves a hole between the last committed part and the live tail,
which is precisely the bug the `?after={seq}` contract exists to avoid.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass
class Event:
    seq: int
    name: str
    data: dict


class SseEventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[Event | None]]] = {}

    def subscribe(self, cid: str) -> asyncio.Queue[Event | None]:
        queue: asyncio.Queue[Event | None] = asyncio.Queue(maxsize=1024)
        self._subscribers.setdefault(cid, set()).add(queue)
        return queue

    def unsubscribe(self, cid: str, queue: asyncio.Queue[Event | None]) -> None:
        subscribers = self._subscribers.get(cid)
        if not subscribers:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(cid, None)

    def publish(self, cid: str, event: Event) -> None:
        for queue in list(self._subscribers.get(cid, ())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # A consumer this far behind has effectively dropped; it will resume
                # from its last seq rather than be fed a truncated stream.
                pass

    def subscriber_count(self, cid: str) -> int:
        return len(self._subscribers.get(cid, ()))
