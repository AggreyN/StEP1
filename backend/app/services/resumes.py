"""Saved, tailored resumes: queries shared by the resume routes and the
admin pages."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models import Posting, TailoredResume
from app.schemas import ResumePostingRef, ResumeSummaryOut


def counts(db: Session, user_ids: list[int]) -> dict[int, int]:
    rows = db.execute(
        select(TailoredResume.user_id, func.count())
        .where(TailoredResume.user_id.in_(user_ids))
        .group_by(TailoredResume.user_id)
    )
    return {user_id: value for user_id, value in rows.all()}


def last_changed(db: Session, user_ids: list[int]) -> dict[int, datetime]:
    rows = db.execute(
        select(TailoredResume.user_id, func.max(TailoredResume.updated_at))
        .where(TailoredResume.user_id.in_(user_ids))
        .group_by(TailoredResume.user_id)
    )
    return {user_id: value for user_id, value in rows.all()}


def summary(resume: TailoredResume) -> ResumeSummaryOut:
    posting = resume.posting
    return ResumeSummaryOut(
        id=resume.id,
        name=resume.name,
        created_at=resume.created_at,
        updated_at=resume.updated_at,
        posting=(
            ResumePostingRef(
                id=posting.public_id,
                title=posting.title,
                company=posting.company_name or "Unknown",
            )
            if posting is not None
            else None
        ),
    )


def owned(db: Session, user_id: int):
    """Newest first: the order every list of them is shown in."""
    return db.scalars(
        select(TailoredResume)
        .options(joinedload(TailoredResume.posting).joinedload(Posting.company))
        .where(TailoredResume.user_id == user_id)
        .order_by(TailoredResume.updated_at.desc(), TailoredResume.id.desc())
    ).all()


def summaries(db: Session, user_id: int) -> list[ResumeSummaryOut]:
    return [summary(r) for r in owned(db, user_id)]
