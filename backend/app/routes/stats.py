"""The board in three numbers, for the public About page.

The only route that needs no token and returns data. So it returns counts of
the shared board and nothing else: no user, no posting, nothing that differs
by who is asking. It is safe for a browser or a CDN to cache and share, and it
says so.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import Posting
from app.ratelimit import limiter, stats_limit
from app.schemas import StatsOut
from app.services import dedupe, ingest_scheduler
from app.sources import backfill
from app.sources.roles import ROLE_LABELS

router = APIRouter(tags=["stats"])

# Five minutes. The numbers change once a day, when the listings refresh;
# this is how stale a cached copy may be just after that.
CACHE_SECONDS = 300


@router.get("/stats", response_model=StatsOut)
@limiter.limit(stats_limit, error_message="Too many requests.")
def stats(request: Request, response: Response, db: Session = Depends(get_db)):
    open_now = (Posting.active.is_(True), Posting.is_visible.is_(True), dedupe.SHOWN)
    postings, companies = db.execute(
        select(func.count(), func.count(func.distinct(Posting.company_id))).where(*open_now)
    ).one()
    states = ingest_scheduler.source_states(db, list(backfill.SOURCES))

    response.headers["Cache-Control"] = f"public, max-age={CACHE_SECONDS}"
    return StatsOut(
        active_postings=postings,
        companies=companies,
        # Counted from the classifier, "other" included: it is a family a
        # posting can be in, and the number should not change when one is.
        role_families=len(ROLE_LABELS),
        updated_at=ingest_scheduler.board_updated_at(states),
    )
