"""Saved, tailored resumes: queries shared by the resume routes and the
admin pages."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.schemas import ResumeSummaryOut


def counts(db: Session, user_ids: list[int]) -> dict[int, int]:
    return {}


def last_changed(db: Session, user_ids: list[int]) -> dict[int, datetime]:
    return {}


def summaries(db: Session, user_id: int) -> list[ResumeSummaryOut]:
    return []
