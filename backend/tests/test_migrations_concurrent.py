"""Migrations when several tasks start at once."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app import config

BACKEND = Path(__file__).resolve().parent.parent
TABLES = 16  # fifteen of the application's, and alembic_version
HEAD = "0004"
REVISIONS = 4


@pytest.fixture()
def empty_database():
    """A database with nothing in it, as on the first deploy. Made and
    dropped here, beside the one the rest of the suite uses."""
    name = f"step1_migrate_{os.getpid()}_{int(time.time() * 1000) % 100000}"
    admin = create_engine(config.DATABASE_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(config.DATABASE_URL).set(database=name)
    try:
        yield url.render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def upgrade(url: str) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env=os.environ | {"DATABASE_URL": url},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def state(url: str) -> tuple[int, str]:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            tables = conn.execute(
                text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
            ).scalar()
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        return tables, version
    finally:
        engine.dispose()


def test_tasks_that_start_together_all_migrate_safely(empty_database):
    """Six at once, against an empty database. Without the lock several
    begin the same revision and all but one fail. With it, one does the
    work and the rest find it done."""
    started = [upgrade(empty_database) for _ in range(6)]
    outputs = [p.communicate(timeout=120)[0] for p in started]

    for process, output in zip(started, outputs, strict=True):
        assert process.returncode == 0, output[-1500:]
        assert "already exists" not in output and "Traceback" not in output, output[-1500:]
    assert state(empty_database) == (TABLES, HEAD)

    # Each revision was applied once, by whoever got there first.
    applied = sum(output.count("Running upgrade") for output in outputs)
    assert applied == REVISIONS, outputs


def test_a_second_task_waits_for_the_first_to_finish(empty_database):
    """Held by hand, so the order is certain: a migration started while the
    lock is held does nothing until it is released, and then succeeds."""
    engine = create_engine(empty_database, isolation_level="AUTOCOMMIT")
    holder = engine.connect()
    holder.execute(text("SELECT pg_advisory_lock(5173, 1)"))
    try:
        waiting = upgrade(empty_database)
        time.sleep(2.0)
        assert waiting.poll() is None, "it did not wait for the lock"
        with engine.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
                ).scalar()
                == 0
            )

        holder.execute(text("SELECT pg_advisory_unlock(5173, 1)"))
        output = waiting.communicate(timeout=60)[0]
        assert waiting.returncode == 0, output[-1500:]
    finally:
        holder.close()
        engine.dispose()
    assert state(empty_database) == (TABLES, HEAD)


def test_the_lock_is_released_when_the_migration_is_done(empty_database):
    assert upgrade(empty_database).wait(timeout=60) == 0
    engine = create_engine(empty_database)
    with engine.connect() as conn:
        held = conn.execute(
            text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND classid = 5173")
        ).scalar()
    engine.dispose()
    assert held == 0
    # And so a later start, with nothing to do, is quick.
    begun = time.perf_counter()
    assert upgrade(empty_database).wait(timeout=60) == 0
    assert time.perf_counter() - begun < 10


def test_a_migration_that_dies_does_not_leave_the_lock_behind(empty_database):
    engine = create_engine(empty_database, isolation_level="AUTOCOMMIT")
    holder = engine.connect()
    holder.execute(text("SELECT pg_advisory_lock(5173, 1)"))
    waiting = upgrade(empty_database)
    time.sleep(1.0)
    waiting.kill()
    waiting.wait(timeout=10)
    holder.close()  # the first holder's connection goes, as a dead task's would
    engine.dispose()

    done = upgrade(empty_database)
    assert done.wait(timeout=60) == 0
    assert state(empty_database) == (TABLES, HEAD)


def test_requests_are_served_while_a_later_task_migrates(client, db):
    """The old task keeps answering while the new one starts. The lock is
    its own: it is not one that a request, a rescore or an ingest takes."""
    from app.services import matching
    from app.sources import backfill

    assert {matching._LOCK_NAMESPACE, backfill.LOCK_KEY[0], 5173} == {5171, 5172, 5173}
    holding = threading.Event()
    release = threading.Event()

    def hold():
        engine = create_engine(config.DATABASE_URL, isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            conn.execute(text("SELECT pg_advisory_lock(5173, 1)"))
            holding.set()
            release.wait(10)
            conn.execute(text("SELECT pg_advisory_unlock(5173, 1)"))
        engine.dispose()

    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert holding.wait(5)
        assert client.get("/health").status_code == 200
        assert client.get("/stats").status_code == 200
        assert not backfill.is_running(db)
    finally:
        release.set()
        thread.join()


def test_the_container_migrates_before_it_serves():
    entrypoint = (BACKEND / "entrypoint.sh").read_text()
    assert entrypoint.index("alembic upgrade head") < entrypoint.index("exec uvicorn")
    assert "exit 1" in entrypoint  # a task whose migration failed must not serve
