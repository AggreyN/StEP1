"""Saved postings. Save and unsave are idempotent: the button can be clicked
twice, or retried after a timeout, without an error."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, joinedload

from app.database import SessionLocal
from app.deps import current_user, get_db
from app.models import Posting, SavedPosting, User
from app.schemas import FeedOut
from app.services import matching, postings

router = APIRouter(tags=["saved"])


def refresh_company_scores(user_id: int, company_id: int | None) -> None:
    """Saving or applying changes the company signal for that company's other
    postings, and nothing else — so rescore just those."""
    if company_id is None:
        return
    with SessionLocal() as db:
        matching.rescore(db, user_id, company_id=company_id)


@router.get("/saved", response_model=FeedOut)
def list_saved(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    total = db.scalar(select(func.count()).where(SavedPosting.user_id == user.id))
    rows = db.scalars(
        select(Posting)
        .join(SavedPosting, SavedPosting.posting_id == Posting.id)
        .options(joinedload(Posting.company))
        .where(SavedPosting.user_id == user.id)
        # Closed postings stay listed: the student saved them, and "this one
        # closed" is worth knowing.
        .order_by(SavedPosting.created_at.desc(), Posting.id)
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()
    return FeedOut(
        items=postings.serialize(list(rows), db, user.id),
        page=page,
        total=total,
        has_more=page * page_size < total,
    )


@router.post("/saved/{posting_id}", status_code=status.HTTP_204_NO_CONTENT)
def save_posting(
    posting_id: str,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    posting = postings.get_by_public_id(db, posting_id)
    db.execute(
        pg_insert(SavedPosting)
        .values(user_id=user.id, posting_id=posting.id)
        .on_conflict_do_nothing()
    )
    db.commit()
    background.add_task(refresh_company_scores, user.id, posting.company_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/saved/{posting_id}", status_code=status.HTTP_204_NO_CONTENT)
def unsave_posting(
    posting_id: str,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    posting = postings.get_by_public_id(db, posting_id)
    db.execute(
        delete(SavedPosting).where(
            SavedPosting.user_id == user.id, SavedPosting.posting_id == posting.id
        )
    )
    db.commit()
    background.add_task(refresh_company_scores, user.id, posting.company_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
