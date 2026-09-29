"""How fresh the listings are. Read-only: refreshing is the scheduler's job
(services/ingest_scheduler.py) or the command line's."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import config
from app.deps import current_user, get_db
from app.models import User
from app.schemas import IngestSourceOut, IngestStatusOut
from app.services import feed_state, ingest_scheduler
from app.sources import backfill

router = APIRouter(tags=["ingest"])


@router.get("/ingest/status", response_model=IngestStatusOut)
def ingest_status(_: User = Depends(current_user), db: Session = Depends(get_db)):
    running = backfill.is_running(db)
    states = ingest_scheduler.source_states(db, list(backfill.SOURCES))

    sources = []
    for state in states:
        error = state.error
        if state.unfinished:
            # No finish time: either it is the run in progress, or the process
            # doing it died. The lock tells the two apart.
            error = None if running else backfill.INTERRUPTED
        sources.append(
            IngestSourceOut(
                source=state.source,
                last_success_at=state.last_success_at,
                last_attempt_at=state.last_attempt_at,
                fetched=state.fetched,
                upserted=state.upserted,
                deactivated=state.deactivated,
                error=error,
            )
        )

    last_success = ingest_scheduler.board_updated_at(states)
    hours = config.INGEST_INTERVAL_HOURS
    return IngestStatusOut(
        last_success_at=last_success,
        next_due_at=last_success + ingest_scheduler.interval() if last_success else None,
        interval_hours=int(hours) if float(hours).is_integer() else hours,
        auto=config.AUTO_INGEST,
        running=running,
        active_postings=feed_state.open_posting_count(db),
        sources=sources,
    )
