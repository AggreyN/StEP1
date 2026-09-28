"""Pydantic request/response shapes — the API contract the frontend is built
against. Field names here are load-bearing: a rename is a broken merge on the
`frontend` branch.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app import config
from app.models import EVENT_KINDS, INTEREST_ROLES

# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #


class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    display_name: str | None = Field(default=None, max_length=120)

    @field_validator("password")
    @classmethod
    def _min_length(cls, v: str) -> str:
        if len(v) < config.PASSWORD_MIN_LENGTH:
            raise ValueError(f"must be at least {config.PASSWORD_MIN_LENGTH} characters")
        return v

    @field_validator("display_name")
    @classmethod
    def _strip_name(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str | None


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserOut


class MeOut(UserOut):
    onboarded: bool


# --------------------------------------------------------------------------- #
# Profile
# --------------------------------------------------------------------------- #


class InterestIn(BaseModel):
    role: str
    rank: int = Field(ge=1, le=5)

    @field_validator("role")
    @classmethod
    def _known_role(cls, v: str) -> str:
        if v not in INTEREST_ROLES:
            raise ValueError(f"unknown role '{v}'; expected one of {', '.join(INTEREST_ROLES)}")
        return v


class InterestOut(BaseModel):
    role: str
    label: str
    rank: int


class ResumeOut(BaseModel):
    filename: str
    uploaded_at: datetime
    skills: list[str]
    needs_ocr: bool


class ProfileIn(BaseModel):
    school: str = Field(min_length=1, max_length=200)
    major: str = Field(min_length=1, max_length=200)
    minor: str | None = Field(default=None, max_length=200)
    degree_level: str = Field(min_length=1, max_length=40)
    grad_year: int = Field(ge=2000, le=2100)
    gpa: Decimal | None = Field(default=None, ge=0, le=4)
    target_terms: list[str]
    preferred_locations: list[str]
    remote_ok: bool
    interests: list[InterestIn]
    # Present -> replaces resume_skills (lets the user delete a wrongly
    # extracted skill). Absent -> the extracted list is left alone.
    skills: list[str] | None = None

    @field_validator("target_terms", "preferred_locations", "skills")
    @classmethod
    def _clean_strings(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        seen: list[str] = []
        for item in v:
            item = item.strip()
            if item and item not in seen:
                seen.append(item)
        return seen

    @field_validator("minor")
    @classmethod
    def _blank_minor(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None

    @model_validator(mode="after")
    def _interests_are_a_ranking(self):
        n = len(self.interests)
        if not 3 <= n <= 5:
            raise ValueError("interests: pick between 3 and 5 fields")
        ranks = sorted(i.rank for i in self.interests)
        if ranks != list(range(1, n + 1)):
            raise ValueError(f"interests: ranks must be 1..{n} with no gaps or repeats")
        roles = [i.role for i in self.interests]
        if len(set(roles)) != n:
            raise ValueError("interests: each field may appear only once")
        return self


class ProfileOut(BaseModel):
    school: str | None
    major: str | None
    minor: str | None
    degree_level: str | None
    grad_year: int | None
    gpa: float | None
    target_terms: list[str]
    preferred_locations: list[str]
    remote_ok: bool
    interests: list[InterestOut]
    resume: ResumeOut | None
    profile_version: int


class ProfileAccepted(BaseModel):
    profile_version: int
    state: Literal["building"] = "building"


class PresignIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str


class PresignOut(BaseModel):
    upload_url: str
    key: str
    method: Literal["PUT"] = "PUT"
    headers: dict[str, str]


class CommitIn(BaseModel):
    key: str = Field(min_length=1, max_length=512)
    filename: str = Field(min_length=1, max_length=255)


# --------------------------------------------------------------------------- #
# Postings / feed
# --------------------------------------------------------------------------- #


class CompanyOut(BaseModel):
    name: str
    url: str | None


class SalaryOut(BaseModel):
    min: float | None
    max: float | None
    unit: str | None


class ReasonOut(BaseModel):
    code: Literal["role_rank", "skills", "location", "term", "fresh", "company"]
    label: str
    detail: str | None


class ApplicationRef(BaseModel):
    id: int
    status: str


class PostingOut(BaseModel):
    id: str
    title: str
    company: CompanyOut
    roles: list[str]
    role_labels: list[str]
    locations: list[str]
    is_remote: bool
    terms: list[str]
    degrees: list[str]
    url: str
    date_posted: datetime | None
    salary: SalaryOut | None
    source: str
    score: int | None
    reasons: list[ReasonOut]
    saved: bool
    application: ApplicationRef | None


class FeedOut(BaseModel):
    items: list[PostingOut]
    page: int
    total: int
    has_more: bool


class FeedStatusOut(BaseModel):
    state: Literal["building", "ready"]
    pct: int
    step: str


# --------------------------------------------------------------------------- #
# Applications
# --------------------------------------------------------------------------- #


class ApplicationCreateIn(BaseModel):
    posting_id: str
    applied_at: datetime | None = None


class EventIn(BaseModel):
    kind: str
    occurred_at: datetime | None = None
    note: str | None = Field(default=None, max_length=4000)

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, v: str) -> str:
        if v not in EVENT_KINDS:
            raise ValueError(f"unknown event kind '{v}'")
        return v


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    occurred_at: datetime
    note: str | None
    source: str


class ApplicationSummaryOut(BaseModel):
    id: int
    posting: PostingOut
    status: str
    applied_at: datetime | None
    last_event_at: datetime | None


class ApplicationDetailOut(ApplicationSummaryOut):
    events: list[EventOut]
    next_transitions: list[str]


class ApplicationListOut(BaseModel):
    items: list[ApplicationSummaryOut]
