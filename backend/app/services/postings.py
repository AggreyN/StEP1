"""Posting lookup and serialization, shared by every route that returns one.

A posting is addressed in the API as "{source}:{source_id}". Every posting
object carries `saved` and `application` for the *current* user, so a card can
render its buttons without a second request.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app import limits
from app.models import Application, MatchScore, Posting, SavedPosting
from app.schemas import ApplicationRef, CompanyOut, PostingOut, SalaryOut
from app.sources.roles import ROLE_LABELS


def get_by_public_id(db: Session, public_id: str) -> Posting:
    """Resolve "{source}:{source_id}" or raise 404. Inactive postings resolve
    too: a saved or applied-to posting must stay reachable after it closes."""
    source, sep, source_id = (public_id or "").partition(":")
    posting = None
    # Nothing longer than the columns can exist, so it is not looked up.
    if sep and source and source_id and len(public_id) <= limits.POSTING_ID_MAX:
        posting = db.scalar(
            select(Posting)
            .options(joinedload(Posting.company))
            .where(Posting.source == source, Posting.source_id == source_id)
        )
    if posting is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That posting doesn't exist.")
    return posting


def _salary(p: Posting) -> SalaryOut | None:
    if p.salary_min is None and p.salary_max is None:
        return None
    return SalaryOut(
        min=float(p.salary_min) if p.salary_min is not None else None,
        max=float(p.salary_max) if p.salary_max is not None else None,
        unit=p.salary_unit,
    )


def serialize(
    postings: list[Posting],
    db: Session,
    user_id: int,
    scores: dict[int, tuple[int, list]] | None = None,
) -> list[PostingOut]:
    """Postings -> contract shape, in the order given. Three queries for the
    whole page (scores, saved, applications), never one per posting."""
    ids = [p.id for p in postings]
    if not ids:
        return []
    if scores is None:
        scores = {
            pid: (score, reasons)
            for pid, score, reasons in db.execute(
                select(MatchScore.posting_id, MatchScore.score, MatchScore.reasons).where(
                    MatchScore.user_id == user_id, MatchScore.posting_id.in_(ids)
                )
            )
        }
    saved = set(
        db.scalars(
            select(SavedPosting.posting_id).where(
                SavedPosting.user_id == user_id, SavedPosting.posting_id.in_(ids)
            )
        )
    )
    applications = {
        pid: ApplicationRef(id=aid, status=st)
        for pid, aid, st in db.execute(
            select(Application.posting_id, Application.id, Application.status).where(
                Application.user_id == user_id, Application.posting_id.in_(ids)
            )
        )
    }

    out = []
    for p in postings:
        score, reasons = scores.get(p.id, (None, []))
        out.append(
            PostingOut(
                id=p.public_id,
                title=p.title,
                company=CompanyOut(
                    name=p.company_name or (p.company.name if p.company else "Unknown"),
                    url=p.company.url if p.company else None,
                ),
                roles=list(p.roles),
                role_labels=[ROLE_LABELS.get(r, r) for r in p.roles],
                locations=list(p.locations),
                is_remote=p.is_remote,
                terms=list(p.terms),
                degrees=list(p.degrees),
                url=p.url,
                date_posted=p.date_posted,
                salary=_salary(p),
                source=p.source,
                score=score,
                reasons=reasons,
                saved=p.id in saved,
                application=applications.get(p.id),
            )
        )
    return out
