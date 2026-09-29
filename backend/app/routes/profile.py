"""Profile, ranked interests, and the resume upload flow.

Upload is three calls, identical in local and S3 mode:

    POST /profile/resume/presign   -> an upload slot: where to PUT, and how
    PUT  <upload_url>              -> the browser sends the bytes
    POST /profile/resume/commit    -> we examine the object, then read it

In S3 mode the PUT goes straight to S3. In local mode it comes back to
PUT /profile/resume/local/{key} below, which enforces what S3's signature
would.

Nothing a client says about a file is believed. The slot records what was
promised (who, how many bytes, until when); the PUT is held to it; and commit
looks at what is actually in storage, its real size and its first bytes,
before any parser sees it.
"""

from __future__ import annotations

import logging
import unicodedata
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from app import config, limits
from app.deps import current_user, get_db
from app.models import Profile, ProfileInterest, ResumeUpload, User
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
from app.services import feed_state, pdf_worker, resume_parse, storage
from app.sources.roles import ROLE_LABELS

log = logging.getLogger(__name__)

router = APIRouter(prefix="/profile", tags=["profile"])

PDF = "application/pdf"
_MB = 1024 * 1024


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
    background: BackgroundTasks,
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

    # Mark the build as started before responding, so the first status poll
    # can't slip in ahead of the background task and read "ready" off the
    # previous version's scores.
    feed_state.begin(user.id)
    background.add_task(feed_state.run_build, user.id)

    # The poll hint for the "building" screen. CORS must expose this header
    # (main.py) or the browser can't read it.
    response.headers["Retry-After"] = "1"
    return ProfileAccepted(profile_version=profile.profile_version)


# --------------------------------------------------------------------------- #
# Resume
# --------------------------------------------------------------------------- #

_UNKNOWN_KEY = "Unknown upload key."
_START_AGAIN = "Start the upload again."
# Slots nobody came back for are swept up after this long. Generous next to
# the five minutes a slot is valid: the point is to not keep a stranger's
# half-finished upload for ever, not to race anyone.
_ABANDONED_AFTER = timedelta(hours=1)
# Bytes read from the socket at a time when receiving an upload.
_CHUNK = 64 * 1024


def _mb(n: int) -> str:
    return f"{n / _MB:g} MB"


def display_filename(name: str) -> str:
    """What the student's file was called, made safe to show. It is shown,
    and nothing else: it is never part of a key, a path or a header."""
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    # A tab or a newline was a space to whoever named the file. Any other
    # control or format character was nothing to anyone, and is dropped.
    name = "".join(
        " " if ch.isspace() else ch
        for ch in name
        if ch.isspace() or unicodedata.category(ch)[0] != "C"
    )
    return " ".join(name.split())[: limits.FILENAME_MAX] or "resume.pdf"


def _slot(db: Session, user: User, key: str) -> ResumeUpload:
    """The caller's upload slot for this key. Someone else's key, a key that
    was never issued and a string that is not a key at all get the same 404:
    which of the three it was is not the caller's to learn."""
    slot = None
    if isinstance(key, str) and len(key) <= limits.STORAGE_KEY_MAX and storage.owns(user.id, key):
        slot = db.scalar(
            select(ResumeUpload).where(ResumeUpload.key == key, ResumeUpload.user_id == user.id)
        )
    if slot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _UNKNOWN_KEY)
    return slot


def _discard(db: Session, slots: list[ResumeUpload]) -> None:
    """Delete slots and whatever was uploaded to them. The object goes first:
    if that fails, the row stays, so the object can still be found."""
    for slot in slots:
        if storage.delete(slot.key):
            db.delete(slot)
        else:
            log.error("could not delete an abandoned upload", extra={"user_id": slot.user_id})
    db.commit()


def _sweep(db: Session, user: User) -> None:
    """Before issuing a slot: drop this user's unfinished uploads, so they
    hold at most one at a time, and a few that anyone abandoned long ago."""
    unfinished = ResumeUpload.committed_at.is_(None)
    mine = db.scalars(select(ResumeUpload).where(ResumeUpload.user_id == user.id, unfinished)).all()
    abandoned = db.scalars(
        select(ResumeUpload)
        .where(unfinished, ResumeUpload.expires_at < datetime.now(UTC) - _ABANDONED_AFTER)
        .limit(20)
    ).all()
    _discard(db, list({s.key: s for s in [*mine, *abandoned]}.values()))


@router.post("/resume/presign", response_model=PresignOut)
def presign_resume(
    body: PresignIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    content_type = body.content_type.split(";")[0].strip().lower()
    if content_type != PDF or not body.filename.lower().endswith(".pdf"):
        raise HTTPException(
            422, f"Resumes must be PDF files (up to {_mb(config.RESUME_MAX_BYTES)})."
        )

    _sweep(db, user)
    key = storage.new_key(user.id)
    db.add(
        ResumeUpload(
            key=key,
            user_id=user.id,
            filename=display_filename(body.filename),
            content_type=PDF,
            size=body.size,
            expires_at=datetime.now(UTC) + timedelta(seconds=config.PRESIGN_EXPIRY_SECONDS),
        )
    )
    db.commit()
    url, headers = storage.presign_put(key, PDF, body.size)
    return PresignOut(upload_url=url, key=key, headers=headers)


def _claim(db: Session, key: str) -> bool:
    """Mark the slot used, if it has not been. One statement, so that of two
    uploads racing for the same slot exactly one wins."""
    won = db.execute(
        update(ResumeUpload)
        .where(ResumeUpload.key == key, ResumeUpload.uploaded_at.is_(None))
        .values(uploaded_at=datetime.now(UTC))
    ).rowcount
    db.commit()
    return won == 1


def _release(db: Session, key: str) -> None:
    db.execute(update(ResumeUpload).where(ResumeUpload.key == key).values(uploaded_at=None))
    db.commit()


@router.put(
    "/resume/local/{key:path}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
async def upload_resume_local(
    key: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Local stand-in for the S3 presigned PUT: same verb, same headers, and
    the same refusals S3 would make from the signature."""
    if config.STORAGE_BACKEND != "local":
        raise HTTPException(status.HTTP_404_NOT_FOUND, _UNKNOWN_KEY)
    slot = await run_in_threadpool(_slot, db, user, key)

    if slot.uploaded_at is not None:
        raise HTTPException(409, f"That upload link has already been used. {_START_AGAIN}")
    if slot.expires_at < datetime.now(UTC):
        raise HTTPException(410, f"That upload link has expired. {_START_AGAIN}")
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != slot.content_type:
        raise HTTPException(415, "Resumes must be uploaded as application/pdf.")

    wrong_size = HTTPException(
        400, f"That upload link is for a file of exactly {slot.size:,} bytes. {_START_AGAIN}"
    )
    too_large = HTTPException(413, f"Resumes can be at most {_mb(config.RESUME_MAX_BYTES)}.")
    declared = request.headers.get("content-length")
    if declared is not None:
        if not declared.isdigit():
            raise wrong_size
        if int(declared) > config.RESUME_MAX_BYTES:
            raise too_large
        if int(declared) != slot.size:
            raise wrong_size

    # Content-Length can be absent or untrue, so the bytes are counted as
    # they arrive, and reading stops the moment there are too many.
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > config.RESUME_MAX_BYTES:
            raise too_large
        if received > slot.size:
            raise wrong_size
        chunks.append(chunk)
    if received != slot.size:
        raise wrong_size

    if not await run_in_threadpool(_claim, db, key):
        raise HTTPException(409, f"That upload link has already been used. {_START_AGAIN}")
    try:
        await run_in_threadpool(storage.write_local, key, b"".join(chunks))
    except Exception:
        await run_in_threadpool(_release, db, key)
        raise
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/resume/commit", response_model=ResumeOut)
def commit_resume(
    body: CommitIn,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    slot = _slot(db, user, body.key)
    profile = _get_or_create(db, user)
    if slot.committed_at is not None and profile.resume_s3_key == slot.key:
        # A retry of a commit that already worked (the response was lost).
        return resume_out(profile)

    def refuse(message: str) -> HTTPException:
        """The file is not acceptable: it does not stay, and neither does
        the slot."""
        _discard(db, [slot])
        return HTTPException(status.HTTP_400_BAD_REQUEST, message)

    # What is in storage, not what anyone said would be.
    stored = storage.size(slot.key)
    if stored is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "No uploaded file found for that key. Upload it first."
        )
    if stored > config.RESUME_MAX_BYTES:
        raise refuse(f"Resumes can be at most {_mb(config.RESUME_MAX_BYTES)}.")
    if stored != slot.size or stored < limits.RESUME_MIN_BYTES:
        raise refuse(f"That upload is not the file that was described. {_START_AGAIN}")
    # The first bytes, before anything else is read and before any parser
    # is involved. The name and the declared type were the client's to choose.
    if storage.head(slot.key, len(pdf_worker.MAGIC)) != pdf_worker.MAGIC:
        raise refuse(pdf_worker.NOT_A_PDF)

    try:
        data = storage.read(slot.key, most=config.RESUME_MAX_BYTES)
        text, skills, needs_ocr = resume_parse.parse_resume(data)
    except resume_parse.ResumeParseError as exc:
        raise refuse(str(exc)) from None
    except storage.StorageError:
        raise refuse(f"Resumes can be at most {_mb(config.RESUME_MAX_BYTES)}.") from None

    previous = profile.resume_s3_key
    now = datetime.now(UTC)
    profile.resume_s3_key = slot.key
    profile.resume_filename = display_filename(body.filename)
    profile.resume_uploaded_at = now
    profile.resume_text = text
    profile.resume_skills = skills
    profile.resume_needs_ocr = needs_ocr
    # Skills feed the scorer, so a new resume invalidates cached scores.
    profile.profile_version += 1
    slot.committed_at = now
    db.commit()

    if previous and previous != slot.key:
        # The resume this one replaces. Gone from storage, and its slot too.
        if not storage.delete(previous):
            log.error("could not delete a replaced resume", extra={"user_id": user.id})
        db.execute(delete(ResumeUpload).where(ResumeUpload.key == previous))
        db.commit()
    if profile.onboarded_at is not None:
        feed_state.begin(user.id)
        background.add_task(feed_state.run_build, user.id)
    return resume_out(profile)
