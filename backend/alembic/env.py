"""Alembic environment.

The URL comes from app.config (DATABASE_URL via get_secret), and importing
app.models registers every table on Base.metadata for autogenerate.

Migrations run when the container starts (entrypoint.sh), so every new task
brings the schema up to the code it carries. Tasks can start together: a
deployment runs the new version beside the old one, and a service scaling out
starts several at once. Two `alembic upgrade head` at the same moment would
both find the schema behind, both begin the same revision, and one would fail
half way with "relation already exists".

So a migration takes a lock first. The second task waits for the first to
finish, then looks at the schema, finds it current, and does nothing.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text

import app.models  # noqa: F401 — registers all tables on Base.metadata
from alembic import context
from app.config import DATABASE_URL
from app.database import Base

config = context.config
# set_main_option applies configparser %-interpolation; URL-encoded password
# characters (%40 ...) would crash alembic before any DB contact. %% -> %.
config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# A Postgres advisory lock, two-integer form. The first integer is this
# app's namespace for such locks (the scorer uses 5171, ingest 5172), so the
# pair cannot collide with a lock taken for anything else.
MIGRATION_LOCK = (5173, 1)


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
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
        # Session-level, so it outlives the transaction the migration runs
        # in, and is held from before the first look at the schema until
        # after the last change to it. Waits for as long as it takes: a task
        # that gave up here would start serving against a schema that is
        # still being changed. If this process dies, the connection goes and
        # Postgres releases the lock with it.
        keys = {"a": MIGRATION_LOCK[0], "b": MIGRATION_LOCK[1]}
        connection.execute(text("SELECT pg_advisory_lock(:a, :b)"), keys)
        connection.commit()
        try:
            context.configure(
                connection=connection, target_metadata=target_metadata, compare_type=True
            )
            with context.begin_transaction():
                context.run_migrations()
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:a, :b)"), keys)
            connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
