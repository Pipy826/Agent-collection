"""Alembic environment configuration for async SQLAlchemy."""

import asyncio
import re
from logging.config import fileConfig

from alembic import context
from alembic.operations.base import Operations
import sqlalchemy as sa
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.database import Base
from app.config import get_settings

# Import all models so they are registered with Base.metadata.
import app.models  # noqa: F401

config = context.config
settings = get_settings()

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)


def _install_sqlite_execute_compat() -> None:
    """Patch Alembic raw execute calls for SQLite-only compatibility."""
    if not settings.DATABASE_URL.startswith("sqlite"):
        return
    if getattr(Operations, "_clawith_sqlite_execute_compat", False):
        return

    original_execute = Operations.execute

    def _normalize_sqlite_column_spec(spec: str) -> str:
        cleaned = spec.replace("::json", "").replace("::jsonb", "")
        cleaned = cleaned.replace("TIMESTAMPTZ", "TIMESTAMP")
        cleaned = cleaned.replace("TIMESTAMP WITH TIME ZONE", "TIMESTAMP")
        cleaned = cleaned.replace("JSONB", "JSON")
        return cleaned

    def _execute_sqlite_compat(self, sqltext, *args, **kwargs):
        if not isinstance(sqltext, str):
            return original_execute(self, sqltext, *args, **kwargs)

        if "DO $$" in sqltext.upper():
            return None

        bind = self.get_bind()
        inspector = sa.inspect(bind)
        statements = [stmt.strip() for stmt in sqltext.split(";") if stmt.strip()]

        for stmt in statements:
            compact = re.sub(r"\s+", " ", stmt).strip()

            add_col = re.match(
                r"ALTER TABLE ([A-Za-z0-9_]+) ADD COLUMN IF NOT EXISTS ([A-Za-z0-9_]+) (.+)",
                compact,
                flags=re.IGNORECASE,
            )
            if add_col:
                table_name, column_name, column_spec = add_col.groups()
                existing = {col["name"] for col in inspector.get_columns(table_name)}
                if column_name in existing:
                    continue
                rewritten = (
                    f"ALTER TABLE {table_name} ADD COLUMN {column_name} "
                    f"{_normalize_sqlite_column_spec(column_spec)}"
                )
                bind.execute(sa.text(rewritten))
                continue

            if re.match(r"ALTER TABLE .+ DROP CONSTRAINT IF EXISTS .+", compact, flags=re.IGNORECASE):
                continue

            if re.match(r"ALTER TYPE .+ ADD VALUE .+", compact, flags=re.IGNORECASE):
                continue

            if re.match(r"DROP TYPE IF EXISTS .+", compact, flags=re.IGNORECASE):
                continue

            if re.match(r"ALTER TABLE .+ DROP COLUMN IF EXISTS .+", compact, flags=re.IGNORECASE):
                continue

            if re.match(r"ALTER TABLE .+ ALTER COLUMN .+ SET DEFAULT .+", compact, flags=re.IGNORECASE):
                continue

            if re.match(r"ALTER TABLE .+ ALTER COLUMN .+ DROP DEFAULT", compact, flags=re.IGNORECASE):
                continue

            original_execute(self, stmt, *args, **kwargs)

    Operations.execute = _execute_sqlite_compat
    Operations._clawith_sqlite_execute_compat = True


_install_sqlite_execute_compat()


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
