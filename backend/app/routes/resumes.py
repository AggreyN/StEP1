"""The person's resume as data, tailoring it to a job, and saved resumes.

    POST   /resume/base/extract     a draft base resume from their upload (not saved)
    GET    /resume/base             their base resume
    PUT    /resume/base             save it: the only source tailoring draws from
    POST   /tailor                  a tailored draft for a posting or pasted job (not saved)
    POST   /resumes                 save a resume under a name
    GET    /resumes                 their saved resumes, newest first
    GET    /resumes/{id}            one, in full
    PUT    /resumes/{id}            rename it, or replace its content
    DELETE /resumes/{id}
    GET    /resumes/{id}/download?format=pdf|docx

Everything is the caller's own: another person's resume is a 404, the same
404 as one that does not exist.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app import config, limits
from app.deps import current_user, get_db
from app.models import BaseResumeDoc, Posting, Profile, TailoredResume, User
from app.ratelimit import take, wait_in_words
from app.schemas import (
    BaseResume,
    ResumeFullOut,
    ResumeListOut,
    SavedResumeIn,
    SavedResumeUpdate,
    TailorIn,
    TailorOut,
    TailorReport,
    document,
)
from app.services import llm, postings, resume_render, resumes, tailor

router = APIRouter(tags=["resumes"])
log = logging.getLogger(__name__)

BUSY = "Resume tailoring is busy right now. Try again in a minute."
NO_UPLOAD = "Upload your resume first."
NO_BASE = "Set up your base resume first."
NOT_THERE = "That resume doesn't exist."


def _too_many(what: str, seconds: int) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": f"You've used {what} a lot today. Try again {wait_in_words(seconds)}."},
        headers={"Retry-After": str(seconds)},
    )


def _busy() -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, BUSY, headers={"Retry-After": "60"})


# --------------------------------------------------------------------------- #
# The base resume
# --------------------------------------------------------------------------- #


@router.post("/resume/base/extract", response_model=BaseResume)
def extract_base(user: User = Depends(current_user), db: Session = Depends(get_db)):
    text = db.scalar(select(Profile.resume_text).where(Profile.user_id == user.id))
    if not text or not text.strip():
        raise HTTPException(status.HTTP_409_CONFLICT, NO_UPLOAD)
    wait = take(config.EXTRACT_RATE_LIMIT, ("resume-extract", str(user.id)))
    if wait is not None:
        return _too_many("resume drafting", wait)
    try:
        return tailor.extract_base(text)
    except (llm.LLMUnavailable, llm.LLMBadOutput) as exc:
        log.error("extract failed", extra={"user_id": user.id, "error": str(exc)[:200]})
        raise _busy() from None


@router.get("/resume/base", response_model=BaseResume)
def get_base(user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.get(BaseResumeDoc, user.id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No base resume yet.")
    return BaseResume.model_validate(row.doc)


@router.put("/resume/base", response_model=BaseResume)
def put_base(body: BaseResume, user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = document(body)
    row = db.get(BaseResumeDoc, user.id)
    if row is None:
        db.add(BaseResumeDoc(user_id=user.id, doc=doc))
    else:
        row.doc = doc
        row.updated_at = datetime.now(UTC)
    db.commit()
    return body


# --------------------------------------------------------------------------- #
# Tailoring
# --------------------------------------------------------------------------- #


def _posting_text(p: Posting) -> str:
    """What the board knows about a posting. The lists carry no description,
    so this is the title and its particulars: enough to tailor towards, and
    the report says when more would help."""
    lines = [f"Role: {p.title}", f"Company: {p.company_name or 'Unknown'}"]
    if p.locations:
        lines.append(f"Location: {'; '.join(p.locations)}")
    if p.terms:
        lines.append(f"Term: {', '.join(p.terms)}")
    if p.degrees:
        lines.append(f"Degrees: {', '.join(p.degrees)}")
    if p.category:
        lines.append(f"Category: {p.category}")
    lines.append(
        "Only this summary of the posting is available; the full description is at the "
        "employer's site."
    )
    return "\n".join(lines)


@router.post("/tailor", response_model=TailorOut)
def tailor_resume(
    body: TailorIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    row = db.get(BaseResumeDoc, user.id)
    if row is None:
        raise HTTPException(status.HTTP_409_CONFLICT, NO_BASE)
    posting_meta = None
    if body.posting_id is not None:
        posting = postings.get_by_public_id(db, body.posting_id)
        job_text = _posting_text(posting)
        posting_meta = {
            "title": posting.title,
            "company": posting.company_name or "Unknown",
            "locations": list(posting.locations),
        }
    else:
        job_text = body.job_text.strip()
    wait = take(config.TAILOR_RATE_LIMIT, ("tailor", str(user.id)))
    if wait is not None:
        return _too_many("tailoring", wait)
    try:
        result = tailor.tailor(BaseResume.model_validate(row.doc), job_text, posting_meta)
    except (llm.LLMUnavailable, llm.LLMBadOutput) as exc:
        log.error("tailor failed", extra={"user_id": user.id, "error": str(exc)[:200]})
        raise _busy() from None
    log.info(
        "tailored",
        extra={
            "user_id": user.id,
            "attempts": result.attempts,
            "removed": result.violations_removed,
        },
    )
    return TailorOut(
        draft=result.draft,
        report=TailorReport(
            fit=result.report["fit"],
            changes=result.report["changes"],
            gaps=result.report["gaps"],
            question=result.report["question"],
        ),
        suggested_name=result.suggested_name,
    )


# --------------------------------------------------------------------------- #
# Saved resumes
# --------------------------------------------------------------------------- #


def _owned(db: Session, resume_id: int, user_id: int) -> TailoredResume:
    resume = db.scalar(
        select(TailoredResume)
        .options(joinedload(TailoredResume.posting))
        .where(TailoredResume.id == resume_id, TailoredResume.user_id == user_id)
    )
    if resume is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_THERE)
    return resume


def full(resume: TailoredResume) -> ResumeFullOut:
    summary = resumes.summary(resume)
    return ResumeFullOut(
        id=summary.id,
        name=summary.name,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        posting=summary.posting,
        doc=resume.doc,
    )


@router.post("/resumes", response_model=ResumeFullOut, status_code=status.HTTP_201_CREATED)
def save_resume(
    body: SavedResumeIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    held = db.scalar(select(func.count()).where(TailoredResume.user_id == user.id))
    if held >= limits.SAVED_RESUMES_MAX:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"You have {limits.SAVED_RESUMES_MAX} saved resumes. Delete one to save another.",
        )
    posting_id = None
    if body.posting_id is not None:
        posting_id = postings.get_by_public_id(db, body.posting_id).id
    resume = TailoredResume(
        user_id=user.id, name=body.name, doc=document(body.doc), posting_id=posting_id
    )
    db.add(resume)
    db.commit()
    return full(_owned(db, resume.id, user.id))


@router.get("/resumes", response_model=ResumeListOut)
def list_resumes(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return ResumeListOut(items=resumes.summaries(db, user.id))


@router.get("/resumes/{resume_id}", response_model=ResumeFullOut)
def get_resume(resume_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return full(_owned(db, resume_id, user.id))


@router.put("/resumes/{resume_id}", response_model=ResumeFullOut)
def update_resume(
    resume_id: int,
    body: SavedResumeUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    resume = _owned(db, resume_id, user.id)
    if body.name is not None:
        resume.name = body.name
    if body.doc is not None:
        resume.doc = document(body.doc)
    if body.name is not None or body.doc is not None:
        resume.updated_at = datetime.now(UTC)
    db.commit()
    return full(_owned(db, resume_id, user.id))


@router.delete(
    "/resumes/{resume_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
def delete_resume(
    resume_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    db.delete(_owned(db, resume_id, user.id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


_MEDIA = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def file_name(name: str, extension: str) -> str:
    """ "JPMorgan resume" -> "JPMorgan resume.pdf": the name as typed, minus
    anything a file system or a header would choke on."""
    cleaned = unicodedata.normalize("NFC", name)
    cleaned = "".join(c for c in cleaned if unicodedata.category(c)[0] != "C")
    cleaned = re.sub(r'[\\/:*?"<>|]+', " ", cleaned)
    cleaned = " ".join(cleaned.split()).strip(" .")[: limits.SAVED_RESUME_NAME_MAX]
    return f"{cleaned or 'resume'}.{extension}"


@router.get(
    "/resumes/{resume_id}/download",
    response_class=Response,
    responses={200: {"content": {m: {} for m in _MEDIA.values()}}},
)
def download_resume(
    resume_id: int,
    format: Literal["pdf", "docx"] = Query("pdf"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return download(_owned(db, resume_id, user.id), format)


def download(resume: TailoredResume, format: str) -> Response:
    """The resume as a file attachment, named after it."""
    from app.services.storage import attachment

    rendered = resume_render.pdf(resume.doc) if format == "pdf" else resume_render.docx(resume.doc)
    headers = {"Content-Disposition": attachment(file_name(resume.name, format))}
    if format == "pdf":
        headers["X-Resume-Pages"] = str(rendered.pages)
    return Response(content=rendered.data, media_type=_MEDIA[format], headers=headers)
