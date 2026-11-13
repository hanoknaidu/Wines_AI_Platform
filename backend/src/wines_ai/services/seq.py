"""Per-conversation monotonic event sequence.

Every SSE `id:` and every `?after=` value comes from here. It must be strictly
increasing per conversation with no gap and no duplicate, because that sequence is the
whole resume contract.

Why in-process rather than SELECT MAX(seq)+1 per event: token events are never
persisted (they are coalesced into one text part at the end of the turn), so a
database-derived counter would hand out the same number to consecutive tokens. It
would also mean one transaction per token, which for a 300-word answer is 400 write
transactions to produce one row.

Correct because the deployment is single-worker by design (SSE fan-out and the
in-flight registry are in-process, and SQLite takes one writer). The counter is primed
from the database on first touch, so a restart continues the sequence rather than
replaying numbers a client has already seen.
"""

from __future__ import annotations

import asyncio

from ..db.repositories import messages as messages_repo


class SeqAllocator:
    def __init__(self, db) -> None:
        self.db = db
        self._counters: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def next(self, cid: str) -> int:
        async with self._lock:
            current = self._counters.get(cid)
            if current is None:
                async with self.db.connect() as conn:
                    current = (await messages_repo.max_seq(conn, cid=cid))
                self._counters[cid] = current
            nxt = current + 1
            self._counters[cid] = nxt
            return nxt

    async def peek(self, cid: str) -> int:
        async with self._lock:
            current = self._counters.get(cid)
        if current is not None:
            return current
        async with self.db.connect() as conn:
            return await messages_repo.max_seq(conn, cid=cid)

    def forget(self, cid: str) -> None:
        self._counters.pop(cid, None)
