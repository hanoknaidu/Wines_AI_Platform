"""A thin wrapper that serialises writes.

SQLite takes exactly one writer. SQLAlchemy opens a DEFERRED transaction, which starts
as a read and upgrades on the first write - and an upgrade that collides returns
SQLITE_BUSY *immediately*, which `busy_timeout` cannot wait out, because the
transaction's read snapshot is already stale. Under 20 concurrent sessions (NFR-2)
that surfaces as "database is locked" on an ordinary turn.

So writes go through one in-process lock and begin with BEGIN IMMEDIATE (the write
lock is taken up front, no upgrade, nothing to collide with). Reads are untouched and
stay concurrent - WAL allows readers alongside the writer.

This is the same single-writer constraint the architecture already accepts by choosing
SQLite plus a single worker; the lock just makes it explicit instead of intermittent.
Phase 2's Postgres swap removes the need for it, and because every call site already
goes through `begin()` / `connect()`, removing it is a change to this file alone.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class Database:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._write_lock = asyncio.Lock()

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @asynccontextmanager
    async def begin(self):
        """A serialised write transaction."""
        async with self._write_lock:
            async with self._engine.connect() as conn:
                await conn.execute(text("BEGIN IMMEDIATE"))
                try:
                    yield conn
                except BaseException:
                    await conn.rollback()
                    raise
                else:
                    await conn.commit()

    def connect(self):
        """A read connection. Not serialised: WAL permits concurrent readers."""
        return self._engine.connect()

    async def dispose(self) -> None:
        await self._engine.dispose()
