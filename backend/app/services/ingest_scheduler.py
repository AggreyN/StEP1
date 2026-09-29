"""Automatic refresh: keep the listings no more than a day old.

A background task, started from the FastAPI lifespan, looks at the clock at
startup and then every INGEST_CHECK_MINUTES. For each source whose last
*successful* ingest is older than INGEST_INTERVAL_HOURS (or that has never had
one) it runs the same code as `python -m app.sources.backfill`.

Three properties follow from deciding off the ledger rather than off a timer:

  * A laptop that was closed overnight catches up when the API next starts,
    because the first check happens at startup.
  * A failed run does not count, so it is retried at the next check —
    minutes later, not a day later.
  * Restarts are free. `--reload` can restart the process fifty times in an
    afternoon and the ledger still says the last success was at 9 a.m.

The ingest runs in a worker thread so requests keep being served, and under a
Postgres advisory lock so two processes (several workers, or a restart
overlapping the process it replaces) never ingest at once. A process that
finds the lock taken skips this round and looks again at the next check.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config
from app.database import SessionLocal
from app.models import IngestRun
from app.sources import backfill
from app.sources.backfill import RunResult
from app.sources.base import Source

log = logging.getLogger(__name__)

# A check interval of zero would spin the loop; nothing needs to look at the
# clock more than every few seconds, even in a demo.
_MIN_CHECK_SECONDS = 2.0


@dataclass
class SourceState:
    source: str
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None
    fetched: int = 0
    upserted: int = 0
    deactivated: int = 0
    error: str | None = None
    unfinished: bool = False  # the last attempt has no finished_at


def interval() -> timedelta:
    return timedelta(hours=config.INGEST_INTERVAL_HOURS)


def source_states(db: Session, names: list[str]) -> list[SourceState]:
    """For each source: when it last succeeded, and how its last attempt went.
    Two queries however many sources or runs there are."""
    states = {name: SourceState(name) for name in names}
    if not names:
        return []

    # A success is a run that finished without an error. A run the truncated-
    # file guard flagged carries an error and so is not one: upstream looked
    # broken, and the right response is to look again soon.
    for source, finished in db.execute(
        select(IngestRun.source, func.max(IngestRun.finished_at))
        .where(
            IngestRun.source.in_(names),
            IngestRun.error.is_(None),
            IngestRun.finished_at.is_not(None),
        )
        .group_by(IngestRun.source)
    ):
        states[source].last_success_at = finished

    latest = (
        select(IngestRun)
        .where(IngestRun.source.in_(names))
        .distinct(IngestRun.source)
        .order_by(IngestRun.source, IngestRun.id.desc())
    )
    for run in db.scalars(latest):
        state = states[run.source]
        state.last_attempt_at = run.finished_at or run.started_at
        state.fetched, state.upserted, state.deactivated = (
            run.fetched,
            run.upserted,
            run.deactivated,
        )
        state.error = run.error
        state.unfinished = run.finished_at is None
    return [states[name] for name in names]


def board_updated_at(states: list[SourceState]) -> datetime | None:
    """When the board as a whole was last known to be current: the oldest of
    the sources' last successes. Every source has been refreshed at least
    this recently. None until some source has succeeded once."""
    successes = [s.last_success_at for s in states if s.last_success_at is not None]
    return min(successes) if successes else None


def due_sources(db: Session, names: list[str], now: datetime | None = None) -> list[str]:
    """Sources with no successful ingest inside the interval."""
    now = now or datetime.now(UTC)
    return [
        s.source
        for s in source_states(db, names)
        if s.last_success_at is None or now - s.last_success_at >= interval()
    ]


def run_due(
    registry: dict[str, type[Source]] | None = None, now: datetime | None = None
) -> list[RunResult] | None:
    """One check: ingest whatever is due. Blocking; call it off the event loop.

    Returns the runs it made ([] when nothing was due), or None when another
    process held the lock and this one stood down.
    """
    registry = backfill.SOURCES if registry is None else registry
    names = list(registry)

    # Looked at before the lock: the common case is "nothing is due", and
    # that should cost one query, not a lock round-trip every half hour.
    with SessionLocal() as db:
        if not due_sources(db, names, now):
            return []

    with backfill.ingest_lock(wait=False) as held:
        if not held:
            log.info("ingest skipped: another process is running one")
            return None
        with SessionLocal() as db:
            backfill.close_interrupted_runs(db)
            # Looked at again under the lock: whoever held it a moment ago
            # may have just done this work.
            due = due_sources(db, names, now)
            return [backfill.ingest(db, registry[name]()) for name in due]


# --------------------------------------------------------------------------- #
# The background task
# --------------------------------------------------------------------------- #


async def _loop() -> None:
    pause = max(config.INGEST_CHECK_MINUTES * 60, _MIN_CHECK_SECONDS)
    while True:
        try:
            # A thread, because the ingest is seconds of blocking network,
            # parsing and SQL; on the event loop it would stall every request.
            await asyncio.to_thread(run_due)
        except asyncio.CancelledError:
            raise
        except Exception:
            # The database being down at 3 a.m. must not end automatic
            # refresh for the life of the process. Log it and look again.
            log.exception("ingest check failed")
        await asyncio.sleep(pause)


def start() -> asyncio.Task | None:
    """Start the task if AUTO_INGEST is on. Call from a running event loop."""
    if not config.AUTO_INGEST:
        log.info("automatic refresh is off (AUTO_INGEST=false)")
        return None
    log.info(
        "automatic refresh is on",
        extra={
            "interval_hours": config.INGEST_INTERVAL_HOURS,
            "check_minutes": config.INGEST_CHECK_MINUTES,
        },
    )
    return asyncio.create_task(_loop(), name="ingest-scheduler")


async def stop(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
