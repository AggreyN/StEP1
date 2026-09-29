"""Whether a student's cached scores are current, and the progress of the
build that makes them so.

`GET /feed/status` drives the "starting your career..." screen. The steps are
real work, reported as it happens:

    Reading your resume  ->  Scanning 4,781 open internships  ->  Ranking your matches

Progress lives in an in-process dict keyed by user id. That is enough for one
worker, and it degrades safely with several: a poll that lands on a worker
with no entry for the user falls back to the database, and if the scores are
stale it simply computes them on the spot (it takes well under a second). So
a lost background task or a restarted process can never leave the screen
spinning.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config
from app.database import SessionLocal
from app.models import IngestRun, Posting, Profile
from app.services import matching

log = logging.getLogger(__name__)

STEP_RESUME = "Reading your resume"
STEP_RANK = "Ranking your matches"

_progress: dict[int, dict] = {}
_lock = threading.Lock()


def step_scan(open_count: int) -> str:
    return f"Scanning {open_count:,} open internships"


def _set(user_id: int, pct: int, step: str) -> None:
    with _lock:
        _progress[user_id] = {"pct": pct, "step": step}


def _clear(user_id: int) -> None:
    with _lock:
        _progress.pop(user_id, None)


def forget(user_id: int) -> None:
    """The account is gone. Nothing about it stays in this process."""
    _clear(user_id)


def begin(user_id: int) -> None:
    """Called by PUT /profile before it returns 202, so the very first poll
    already sees a build in flight."""
    _set(user_id, 5, STEP_RESUME)


def open_posting_count(db: Session) -> int:
    return db.scalar(
        select(func.count()).where(Posting.active.is_(True), Posting.is_visible.is_(True))
    )


def is_current(db: Session, profile: Profile) -> bool:
    """Cached scores are usable when they were computed for this version of
    the profile, against the postings as they are now, recently enough that
    freshness hasn't drifted."""
    if profile.scores_version != profile.profile_version or profile.scores_computed_at is None:
        return False
    age = datetime.now(UTC) - profile.scores_computed_at
    if age > timedelta(hours=config.SCORES_MAX_AGE_HOURS):
        return False
    # An ingest that changed the board since we scored: new postings have no
    # score yet, and closed ones still do.
    changed_at = db.scalar(
        select(func.max(IngestRun.finished_at)).where(
            (IngestRun.upserted > 0) | (IngestRun.deactivated > 0)
        )
    )
    return changed_at is None or changed_at <= profile.scores_computed_at


def ensure_current(db: Session, profile: Profile) -> None:
    """Recompute synchronously if the cache is stale. Used by GET /feed."""
    if not is_current(db, profile):
        # Re-checked under the lock: if a background build was mid-flight, we
        # waited for it and there is nothing left to do.
        matching.rescore(db, profile.user_id, unless=lambda fresh: is_current(db, fresh))
        db.refresh(profile)


def run_build(user_id: int) -> None:
    """The background task behind PUT /profile's 202."""
    try:
        with SessionLocal() as db:
            profile = db.get(Profile, user_id)
            if profile is None:
                return
            _set(user_id, 15, STEP_RESUME)
            # Touch the resume fields the scorer reads, so step one is the
            # actual load and not a label.
            _ = (profile.resume_skills, profile.resume_needs_ocr)
            _set(user_id, 40, step_scan(open_posting_count(db)))
            _set(user_id, 75, STEP_RANK)
            count = matching.rescore(db, user_id)
            log.info("feed built", extra={"user_id": user_id, "scored": count})
    except Exception:
        # Not fatal: the next status poll or feed read finds the cache stale
        # and rebuilds it in the request.
        log.exception("feed build failed", extra={"user_id": user_id})
    finally:
        _clear(user_id)


def status(db: Session, profile: Profile) -> dict:
    with _lock:
        running = _progress.get(profile.user_id)
    if running is not None:
        return {"state": "building", **running}
    ensure_current(db, profile)
    return {"state": "ready", "pct": 100, "step": STEP_RANK}
