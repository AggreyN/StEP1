"""Profile, ranked interests, and the resume upload flow.

Upload is three calls, identical in local and S3 mode:

    POST /profile/resume/presign   -> where to PUT the file
    PUT  <upload_url>              -> the browser sends the bytes
    POST /profile/resume/commit    -> we verify the object, extract text + skills

In S3 mode the PUT goes straight to S3. In local mode it comes back to
PUT /profile/resume/local/{key} below.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from app import config
from app.deps import current_user, get_db
from app.models import Profile, ProfileInterest, User
from app.schemas import (
    CommitIn,
    InterestOut,
    PresignIn,
    PresignOut,
    ProfileAccepted,
    ProfileIn,
    ProfileOut,
    ResumeOut,
)
from app.services import resume_parse, storage
from app.sources.roles import ROLE_LABELS

router = APIRouter(prefix="/profile", tags=["profile"])

PDF = "application/pdf"
_MB = 1024 * 1024


def _limit_text() -> str:
    return f"{config.RESUME_MAX_BYTES / _MB:g} MB"


def resume_out(profile: Profile) -> ResumeOut | None:
    if not profile.resume_s3_key or profile.resume_uploaded_at is None:
        return None
    return ResumeOut(
        filename=profile.resume_filename or "resume.pdf",
        uploaded_at=profile.resume_uploaded_at,
        skills=list(profile.resume_skills or []),
        needs_ocr=profile.resume_needs_ocr,
    )


def profile_out(profile: Profile) -> ProfileOut:
    return ProfileOut(
        school=profile.school,
        major=profile.major,
        minor=profile.minor,
        degree_level=profile.degree_level,
        grad_year=profile.grad_year,
        gpa=float(profile.gpa) if profile.gpa is not None else None,
        target_terms=list(profile.target_terms or []),
        preferred_locations=list(profile.preferred_locations or []),
        remote_ok=profile.remote_ok,
        interests=[
            InterestOut(role=i.role, label=ROLE_LABELS[i.role], rank=i.rank)
            for i in sorted(profile.interests, key=lambda i: i.rank)
        ],
        resume=resume_out(profile),
        profile_version=profile.profile_version,
    )


def _get_or_create(db: Session, user: User) -> Profile:
    profile = db.get(Profile, user.id)
    if profile is None:
        profile = Profile(user_id=user.id, profile_version=0)
        db.add(profile)
        db.flush()
    return profile


@router.get("", response_model=ProfileOut)
def get_profile(user: User = Depends(current_user), db: Session = Depends(get_db)):
    profile = db.get(Profile, user.id)
    # A resume committed mid-onboarding creates the row early; until the form
    # itself is saved there is no profile to show.
    if profile is None or profile.onboarded_at is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No profile yet. Complete onboarding first.")
    return profile_out(profile)


@router.put("", response_model=ProfileAccepted, status_code=status.HTTP_202_ACCEPTED)
def put_profile(
    body: ProfileIn,
    response: Response,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    profile = _get_or_create(db, user)
    profile.school = body.school.strip()
    profile.major = body.major.strip()
    profile.minor = body.minor
    profile.degree_level = body.degree_level.strip()
    profile.grad_year = body.grad_year
    profile.gpa = body.gpa
    profile.target_terms = body.target_terms
    profile.preferred_locations = body.preferred_locations
    profile.remote_ok = body.remote_ok
    if body.skills is not None:
        profile.resume_skills = resume_parse.canonicalize(body.skills)

    # Replace the ranking wholesale, deletes first. Updating rows in place
    # trips UNIQUE(user_id, rank) the moment two fields swap ranks.
    db.execute(delete(ProfileInterest).where(ProfileInterest.user_id == user.id))
    db.execute(
        insert(ProfileInterest),
        [{"user_id": user.id, "role": i.role, "rank": i.rank} for i in body.interests],
    )

    profile.profile_version += 1
    if profile.onboarded_at is None:
        profile.onboarded_at = datetime.now(UTC)
    db.commit()

    # The poll hint for the "building" screen. CORS must expose this header
    # (main.py) or the browser can't read it.
    response.headers["Retry-After"] = "1"
    return ProfileAccepted(profile_version=profile.profile_version)


# --------------------------------------------------------------------------- #
# Resume
# --------------------------------------------------------------------------- #


@router.post("/resume/presign", response_model=PresignOut)
def presign_resume(body: PresignIn, user: User = Depends(current_user)):
    content_type = body.content_type.split(";")[0].strip().lower()
    if content_type != PDF or not body.filename.lower().endswith(".pdf"):
        raise HTTPException(
            422,
            f"Resumes must be PDF files (up to {_limit_text()}).",
        )
    key = storage.resume_key(user.id, body.filename)
    url, headers = storage.presign_put(key, PDF)
    return PresignOut(upload_url=url, key=key, headers=headers)


@router.put("/resume/local/{key:path}")
async def upload_resume_local(key: str, request: Request, user: User = Depends(current_user)):
    """Local stand-in for the S3 presigned PUT. Same verb, same headers, so
    the frontend's upload code has one path."""
    if config.STORAGE_BACKEND != "local":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Local uploads are disabled.")
    # 404 rather than 403: whether another user's key exists is not ours to say.
    if not storage.owns(user.id, key):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown upload key.")
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != PDF:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Resumes must be uploaded as application/pdf."
        )

    too_large = HTTPException(413, f"Resumes can be at most {_limit_text()}.")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > config.RESUME_MAX_BYTES:
        raise too_large
    # Content-Length can lie or be absent (chunked), so count what arrives.
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > config.RESUME_MAX_BYTES:
            raise too_large
        chunks.append(chunk)
    if received == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The upload was empty.")

    storage.write_local(key, b"".join(chunks))
    return {"key": key, "size": received}


@router.post("/resume/commit", response_model=ResumeOut)
def commit_resume(
    body: CommitIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    if not storage.owns(user.id, body.key):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown upload key.")
    # Trust the storage, not the client: the object must really be there.
    size = storage.size(body.key)
    if size is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "No uploaded file found for that key. Upload it first."
        )
    if size > config.RESUME_MAX_BYTES:
        storage.delete(body.key)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Resumes can be at most {_limit_text()}.")
    try:
        text, skills, needs_ocr = resume_parse.parse_resume(storage.read(body.key))
    except resume_parse.ResumeParseError as exc:
        storage.delete(body.key)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None

    profile = _get_or_create(db, user)
    previous = profile.resume_s3_key
    profile.resume_s3_key = body.key
    # Display name only; the storage key carries its own sanitized copy.
    profile.resume_filename = body.filename.replace("\\", "/").rsplit("/", 1)[-1].strip()[:255]
    profile.resume_uploaded_at = datetime.now(UTC)
    profile.resume_text = text
    profile.resume_skills = skills
    profile.resume_needs_ocr = needs_ocr
    # Skills feed the scorer, so a new resume invalidates cached scores.
    profile.profile_version += 1
    db.commit()

    if previous and previous != body.key:
        storage.delete(previous)
    return resume_out(profile)
