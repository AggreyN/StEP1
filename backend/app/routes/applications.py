"""Applications and their event timeline.

Status is never written here. Every change is an event appended through
services/timeline.py, which derives the status and answers what may come next.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.deps import current_user, get_db
from app.models import Application, Posting, User
from app.routes.saved import refresh_company_scores
from app.schemas import (
    ApplicationCreateIn,
    ApplicationDetailOut,
    ApplicationListOut,
    ApplicationSummaryOut,
    EventIn,
    EventOut,
)
from app.services import postings, timeline

router = APIRouter(tags=["applications"])

_WITH_POSTING = joinedload(Application.posting).joinedload(Posting.company)


def _detail(
    db: Session, application: Application, user_id: int, scores: dict | None = None
) -> ApplicationDetailOut:
    posting = postings.serialize([application.posting], db, user_id, scores=scores)[0]
    return ApplicationDetailOut(
        id=application.id,
        posting=posting,
        status=application.status,
        applied_at=application.applied_at,
        last_event_at=application.last_event_at,
        events=[EventOut.model_validate(e) for e in application.events],
        next_transitions=timeline.next_transitions(application.status),
    )


def _owned(db: Session, application_id: int, user_id: int) -> Application:
    application = db.scalar(
        select(Application)
        .options(_WITH_POSTING, selectinload(Application.events))
        .where(Application.id == application_id, Application.user_id == user_id)
    )
    # 404 for someone else's application too: its existence is not theirs to learn.
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That application doesn't exist.")
    return application


@router.get("/applications", response_model=ApplicationListOut)
def list_applications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Application)
        .options(_WITH_POSTING)
        .where(Application.user_id == user.id)
        .order_by(Application.last_event_at.desc().nulls_last(), Application.id.desc())
    ).all()
    serialized = postings.serialize([a.posting for a in rows], db, user.id)
    return ApplicationListOut(
        items=[
            ApplicationSummaryOut(
                id=a.id,
                posting=p,
                status=a.status,
                applied_at=a.applied_at,
                last_event_at=a.last_event_at,
            )
            for a, p in zip(rows, serialized, strict=True)
        ]
    )


@router.post(
    "/applications", response_model=ApplicationDetailOut, status_code=status.HTTP_201_CREATED
)
def create_application(
    body: ApplicationCreateIn,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    posting = postings.get_by_public_id(db, body.posting_id)
    conflict = HTTPException(
        status.HTTP_409_CONFLICT, "You've already recorded an application for this posting."
    )
    if db.scalar(
        select(Application.id).where(
            Application.user_id == user.id, Application.posting_id == posting.id
        )
    ):
        raise conflict

    # "applied" is only a placeholder to satisfy NOT NULL until the first
    # event lands a line later; recompute_status() is what sets the real value.
    application = Application(user_id=user.id, posting_id=posting.id, status="applied")
    db.add(application)
    try:
        db.flush()
        timeline.start_application(db, application, applied_at=body.applied_at)
        db.commit()
    except timeline.TransitionError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from None
    except IntegrityError:
        # Two tabs confirming at once: the unique constraint settles it.
        db.rollback()
        raise conflict from None

    background.add_task(refresh_company_scores, user.id, posting.company_id)
    return _detail(db, _owned(db, application.id, user.id), user.id)


@router.get("/applications/{application_id}", response_model=ApplicationDetailOut)
def get_application(
    application_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    return _detail(db, _owned(db, application_id, user.id), user.id)


@router.post(
    "/applications/{application_id}/events",
    response_model=ApplicationDetailOut,
    status_code=status.HTTP_201_CREATED,
)
def add_event(
    application_id: int,
    body: EventIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    application = _owned(db, application_id, user.id)
    try:
        timeline.record_user_event(
            db, application, kind=body.kind, occurred_at=body.occurred_at, note=body.note
        )
    except timeline.TransitionError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from None
    db.commit()
    return _detail(db, _owned(db, application.id, user.id), user.id)
