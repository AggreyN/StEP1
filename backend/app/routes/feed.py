"""The scored feed and the status endpoint behind the "building" screen."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.deps import current_user, get_db
from app.models import INTEREST_ROLES, MatchScore, Posting, Profile, User
from app.schemas import FeedOut, FeedStatusOut
from app.services import feed_state, postings
from app.sources.roles import OTHER

router = APIRouter(tags=["feed"])

_FILTERABLE_ROLES = {*INTEREST_ROLES, OTHER}


def onboarded_profile(user: User = Depends(current_user), db: Session = Depends(get_db)) -> Profile:
    profile = db.get(Profile, user.id)
    if profile is None or profile.onboarded_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Complete onboarding first")
    return profile


_NEWEST = Posting.date_posted.desc().nulls_last()
_BEST = MatchScore.score.desc()
# Posting.id last in both: many postings share a date or a score, and without
# a final unique key Postgres may order ties differently from one page to the
# next, so a posting could appear twice or not at all while paging.
_ORDER = {
    "recent": (_NEWEST, _BEST, Posting.id),
    "score": (_BEST, _NEWEST, Posting.id),
}


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/feed", response_model=FeedOut)
def feed(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    roles: str | None = Query(None, description="Comma-separated role keys; any match."),
    location: str | None = Query(None, description="Substring of any location."),
    term: str | None = Query(None, description='Exact term, e.g. "Summer 2027".'),
    min_score: int | None = Query(None, ge=0, le=100),
    remote: bool | None = Query(None, description="true -> remote postings only."),
    sort: Literal["recent", "score"] = Query(
        "recent", description="recent: newest first (default). score: best match first."
    ),
    profile: Profile = Depends(onboarded_profile),
    db: Session = Depends(get_db),
):
    # Cheap when current; when stale the rescore takes well under a second,
    # so the feed never serves scores from an older profile.
    feed_state.ensure_current(db, profile)

    conditions = [
        MatchScore.user_id == profile.user_id,
        # Filtered on read: a posting that closed since scoring drops out now,
        # not at the next rescore.
        Posting.active.is_(True),
        Posting.is_visible.is_(True),
    ]
    wanted = [r.strip() for r in (roles or "").split(",") if r.strip()]
    if wanted:
        unknown = sorted(set(wanted) - _FILTERABLE_ROLES)
        if unknown:
            raise HTTPException(422, f"roles: unknown role '{unknown[0]}'")
        conditions.append(Posting.roles.overlap(wanted))
    if location and location.strip():
        loc = func.unnest(Posting.locations).column_valued("loc")
        pattern = f"%{_escape_like(location.strip())}%"
        conditions.append(select(1).where(loc.ilike(pattern, escape="\\")).exists())
    if term and term.strip():
        conditions.append(Posting.terms.any(term.strip()))
    if min_score is not None:
        conditions.append(MatchScore.score >= min_score)
    if remote:
        conditions.append(Posting.is_remote.is_(True))

    joined = select(Posting, MatchScore.score, MatchScore.reasons).join(
        MatchScore, MatchScore.posting_id == Posting.id
    )
    total = db.scalar(
        select(func.count())
        .select_from(Posting)
        .join(MatchScore, MatchScore.posting_id == Posting.id)
        .where(*conditions)
    )
    rows = db.execute(
        joined.options(joinedload(Posting.company))
        .where(*conditions)
        .order_by(*_ORDER[sort])
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()

    scores = {p.id: (score, reasons) for p, score, reasons in rows}
    items = postings.serialize([p for p, _, _ in rows], db, profile.user_id, scores)
    return FeedOut(items=items, page=page, total=total, has_more=page * page_size < total)


@router.get("/feed/status", response_model=FeedStatusOut)
def feed_status(profile: Profile = Depends(onboarded_profile), db: Session = Depends(get_db)):
    return feed_state.status(db, profile)
