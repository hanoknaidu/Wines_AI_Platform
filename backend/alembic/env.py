"""Alembic environment.

Migrations run against a SYNCHRONOUS sqlite URL - the async driver is only needed by
the application. The URL is derived from WA_DATABASE_URL so there is one source of
truth: `sqlite+aiosqlite://` becomes `sqlite://`, and a Postgres URL in Phase 2 has
its async driver stripped the same way.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from wines_ai.config import get_settings
from wines_ai.db.tables import metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _sync_url() -> str:
    url = get_settings().database_url
    for async_driver, sync_driver in (
        ("sqlite+aiosqlite", "sqlite"),
        ("postgresql+asyncpg", "postgresql"),
    ):
        if url.startswith(async_driver):
            return url.replace(async_driver, sync_driver, 1)
    return url


config.set_main_option("sqlalchemy.url", _sync_url())
target_metadata = metadata


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite cannot ALTER most things in place; batch mode rewrites the table.
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
