"""The owner's view of every user. Admins only.

    GET /admin/users                       everyone, newest first, searchable
    GET /admin/users/{id}                  one person: profile, saved,
                                           applications, resumes, reviews
    GET /admin/users/{id}/resume-file      a short-lived link to their resume
    GET /admin/resume-files/{token}        local storage only: that link

To anyone who is not an admin, signed in or not, every one of these answers
as a path that does not exist (auth.current_admin).

Every read of a person's data writes one audit line: who read, whose, which
route. Never what was read.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app import config
from app.auth import NOT_FOUND, current_admin
from app.deps import get_db
from app.models import Application, Posting, Profile, Review, SavedPosting, User
from app.routes.applications import _detail
from app.routes.profile import profile_out
from app.schemas import (
    AdminResumeFileOut,
    AdminUserDetailOut,
    AdminUserIdentity,
    AdminUserReviewOut,
    AdminUserRow,
    AdminUsersOut,
    ResumeSummaryOut,
)
from app.services import postings, storage

router = APIRouter(tags=["admin"])
log = logging.getLogger(__name__)
audit = logging.getLogger("audit")

# Signs the local-storage download links. Per process: a restart only
# invalidates links that live five minutes anyway, and nothing configured
# (JWT_SECRET is the public default in cognito mode) can forge one.
_LOCAL_LINK_KEY = secrets.token_bytes(32)
_LOCAL_LINK_AUDIENCE = "admin-resume-file"


def _audit(request: Request, admin: User, target_id: int, route: str) -> None:
    audit.info(
        "admin read",
        extra={"admin_email": admin.email, "target_user_id": target_id, "route": route},
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)


# --------------------------------------------------------------------------- #
# Tailored resumes. Filled in by the resume feature; until then, none.
# --------------------------------------------------------------------------- #


def resume_counts(db: Session, user_ids: list[int]) -> dict[int, int]:
    from app.services import resumes

    return resumes.counts(db, user_ids)


def resume_summaries(db: Session, user_id: int) -> list[ResumeSummaryOut]:
    from app.services import resumes

    return resumes.summaries(db, user_id)


def resume_last_changed(db: Session, user_ids: list[int]) -> dict[int, datetime]:
    from app.services import resumes

    return resumes.last_changed(db, user_ids)


# --------------------------------------------------------------------------- #
# The list
# --------------------------------------------------------------------------- #


def _latest(*values: datetime | None) -> datetime | None:
    present = [v for v in values if v is not None]
    return max(present) if present else None


@router.get("/admin/users", response_model=AdminUsersOut)
def list_users(
    q: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1, le=100_000),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(current_admin),
    db: Session = Depends(get_db),
):
    where = []
    if q and q.strip():
        pattern = f"%{_escape_like(q.strip())}%"
        where.append(
            or_(
                User.email.ilike(pattern, escape="\\"),
                User.display_name.ilike(pattern, escape="\\"),
            )
        )
    total = db.scalar(select(func.count(User.id)).where(*where))
    users = db.scalars(
        select(User)
        .options(joinedload(User.profile))
        .where(*where)
        .order_by(User.created_at.desc(), User.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()
    ids = [u.id for u in users]

    def grouped(query) -> dict[int, tuple]:
        return {row[0]: tuple(row[1:]) for row in db.execute(query)} if ids else {}

    applications = grouped(
        select(Application.user_id, func.count(), func.max(Application.last_event_at))
        .where(Application.user_id.in_(ids))
        .group_by(Application.user_id)
    )
    saved = grouped(
        select(SavedPosting.user_id, func.count(), func.max(SavedPosting.created_at))
        .where(SavedPosting.user_id.in_(ids))
        .group_by(SavedPosting.user_id)
    )
    reviews = grouped(
        select(Review.user_id, func.max(Review.created_at))
        .where(Review.user_id.in_(ids))
        .group_by(Review.user_id)
    )
    tailored = resume_counts(db, ids) if ids else {}
    tailored_at = resume_last_changed(db, ids) if ids else {}

    items = []
    for u in users:
        p = u.profile
        n_apps, apps_at = applications.get(u.id, (0, None))
        n_saved, saved_at = saved.get(u.id, (0, None))
        items.append(
            AdminUserRow(
                id=u.id,
                email=u.email,
                display_name=u.display_name,
                created_at=u.created_at,
                onboarded=bool(p and p.onboarded_at),
                school=p.school if p else None,
                major=p.major if p else None,
                grad_year=p.grad_year if p else None,
                applications=n_apps,
                saved=n_saved,
                tailored_resumes=tailored.get(u.id, 0),
                has_resume=bool(p and p.resume_s3_key and p.resume_uploaded_at),
                last_active_at=_latest(
                    apps_at,
                    saved_at,
                    reviews.get(u.id, (None,))[0],
                    tailored_at.get(u.id),
                    p.onboarded_at if p else None,
                    p.resume_uploaded_at if p else None,
                ),
            )
        )
    return AdminUsersOut(items=items, page=page, total=total, has_more=page * page_size < total)


# --------------------------------------------------------------------------- #
# One person
# --------------------------------------------------------------------------- #


def _target(db: Session, user_id: int) -> User:
    user = db.scalar(select(User).options(joinedload(User.profile)).where(User.id == user_id))
    if user is None:
        raise _not_found()
    return user


@router.get("/admin/users/{user_id}", response_model=AdminUserDetailOut)
def get_user(
    user_id: int,
    request: Request,
    admin: User = Depends(current_admin),
    db: Session = Depends(get_db),
):
    user = _target(db, user_id)
    _audit(request, admin, user.id, "GET /admin/users/{id}")

    profile = db.scalar(
        select(Profile).options(selectinload(Profile.interests)).where(Profile.user_id == user.id)
    )
    saved_rows = db.scalars(
        select(Posting)
        .join(SavedPosting, SavedPosting.posting_id == Posting.id)
        .options(joinedload(Posting.company))
        .where(SavedPosting.user_id == user.id)
        .order_by(SavedPosting.created_at.desc(), Posting.id)
    ).all()
    applications = db.scalars(
        select(Application)
        .options(
            joinedload(Application.posting).joinedload(Posting.company),
            selectinload(Application.events),
        )
        .where(Application.user_id == user.id)
        .order_by(Application.last_event_at.desc().nulls_last(), Application.id.desc())
    ).all()
    reviews = db.scalars(
        select(Review)
        .where(Review.user_id == user.id)
        .order_by(Review.created_at.desc(), Review.id.desc())
    ).all()

    return AdminUserDetailOut(
        user=AdminUserIdentity(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            created_at=user.created_at,
            is_admin=user.email.lower() in config.ADMIN_EMAILS,
        ),
        profile=profile_out(profile) if profile and profile.onboarded_at else None,
        # The person's own saved and applied flags; no score, which is theirs
        # to compute and not the owner's to see out of date.
        saved=postings.serialize(list(saved_rows), db, user.id, scores={}),
        applications=[_detail(db, a, user.id, scores={}) for a in applications],
        resumes=resume_summaries(db, user.id),
        reviews=[
            AdminUserReviewOut(id=r.id, rating=r.rating, body=r.body, created_at=r.created_at)
            for r in reviews
        ],
    )


# --------------------------------------------------------------------------- #
# Their uploaded resume
# --------------------------------------------------------------------------- #


@router.get("/admin/users/{user_id}/resume-file", response_model=AdminResumeFileOut)
def resume_file(
    user_id: int,
    request: Request,
    admin: User = Depends(current_admin),
    db: Session = Depends(get_db),
):
    user = _target(db, user_id)
    p = user.profile
    if p is None or not p.resume_s3_key or p.resume_uploaded_at is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This person has no resume.")
    _audit(request, admin, user.id, "GET /admin/users/{id}/resume-file")

    filename = p.resume_filename or "resume.pdf"
    expires = datetime.now(UTC).replace(microsecond=0) + timedelta(
        seconds=config.PRESIGN_EXPIRY_SECONDS
    )
    if config.STORAGE_BACKEND == "s3":
        url = storage.presign_get(p.resume_s3_key, filename)
    else:
        token = jwt.encode(
            {"k": p.resume_s3_key, "f": filename, "aud": _LOCAL_LINK_AUDIENCE, "exp": expires},
            _LOCAL_LINK_KEY,
            algorithm="HS256",
        )
        url = f"{config.PUBLIC_API_BASE}/admin/resume-files/{token}"
    return AdminResumeFileOut(url=url, filename=filename, expires_at=expires)


@router.get(
    "/admin/resume-files/{token}",
    response_class=FileResponse,
    responses={200: {"content": {"application/pdf": {}}}},
)
def local_resume_file(token: str):
    """Local storage's stand-in for the presigned GET above: the link is the
    permission, signed by this process and good for a few minutes. Anything
    else, and in S3 mode always, it is not there."""
    if config.STORAGE_BACKEND != "local":
        raise _not_found()
    try:
        claims = jwt.decode(
            token, _LOCAL_LINK_KEY, algorithms=["HS256"], audience=_LOCAL_LINK_AUDIENCE
        )
        path = storage.local_path(claims["k"])
    except (jwt.PyJWTError, KeyError, storage.StorageError):
        raise _not_found() from None
    if not path.is_file():
        raise _not_found()
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={"Content-Disposition": storage.attachment(str(claims.get("f") or "resume.pdf"))},
    )
