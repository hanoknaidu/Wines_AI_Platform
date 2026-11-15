"""Async SQLAlchemy Core engine over SQLite with WAL."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine

from ..config import Settings
from .database import Database
from .tables import metadata


def _ensure_parent(url: str) -> None:
    marker = "sqlite+aiosqlite:///"
    if url.startswith(marker):
        path = url[len(marker) :]
        if path and path != ":memory:":
            Path(path).resolve().parent.mkdir(parents=True, exist_ok=True)


def create_engine(settings: Settings) -> Database:
    _ensure_parent(settings.database_url)
    engine = create_async_engine(settings.database_url, future=True, pool_pre_ping=True)

    @event.listens_for(engine.sync_engine, "connect")
    def _pragmas(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    return Database(engine)


async def create_all(db: Database) -> None:
    """Used by tests and first boot. Production schema changes go through Alembic."""
    async with db.engine.begin() as conn:
        await conn.run_sync(metadata.create_all)


async def ping(db: Database) -> str:
    try:
        async with db.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:  # noqa: BLE001
        return f"error: {type(exc).__name__}"
