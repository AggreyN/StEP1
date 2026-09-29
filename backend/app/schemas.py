"""Pydantic request/response shapes — the API contract the frontend is built
against. Field names here are load-bearing: a rename is a broken merge on the
`frontend` branch.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    PlainSerializer,
    field_validator,
    model_validator,
)

from app import config, limits
from app.limits import echo
from app.models import EVENT_KINDS, INTEREST_ROLES
from app.services.terms import canonical_term


def _utc_z(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


# Every timestamp leaves the API as UTC with a trailing Z, whatever zone it
# was stored or submitted in. The frontend compares and sorts these as strings.
UtcDateTime = Annotated[datetime, PlainSerializer(_utc_z, return_type=str, when_used="json")]


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    db: Literal["ok", "error"]


class RequestModel(BaseModel):
    """Base for everything a client sends. Unknown fields are refused, not
    dropped: a request carrying `status` or `user_id` gets a 422 naming the
    field, rather than a 200 that quietly did less than was asked.

    Refusing is the second line of defence. The first is that no route
    unpacks a body into a model: every column is assigned by name, so the
    only fields a client can set are the ones declared here.
    """

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #


def _check_email_length(value: object) -> object:
    # Before EmailStr parses it, so an oversized value is refused for its
    # size rather than examined.
    if isinstance(value, str) and len(value) > limits.EMAIL_MAX:
        raise ValueError(f"must be at most {limits.EMAIL_MAX} characters")
    return value


def _check_password_length(value: str) -> str:
    if len(value) > limits.PASSWORD_MAX:
        raise ValueError(f"must be at most {limits.PASSWORD_MAX} characters")
    return value


def _bounded_strings(values: list[str], *, most: int, chars: int, noun: str) -> list[str]:
    """Trim, drop blanks and repeats, and refuse a list that is too long or
    holds an entry that is. Counted before cleaning: the limit is on what was
    sent."""
    if len(values) > most:
        raise ValueError(f"at most {most} {noun}, not {len(values)}")
    kept: list[str] = []
    for position, raw in enumerate(values, 1):
        item = " ".join(raw.split())
        if len(item) > chars:
            raise ValueError(f"entry {position} is longer than {chars} characters")
        if item and item not in kept:
            kept.append(item)
    return kept


class RegisterIn(RequestModel):
    email: EmailStr
    password: str
    display_name: str | None = Field(default=None, max_length=limits.DISPLAY_NAME_MAX)

    _email_length = field_validator("email", mode="before")(_check_email_length)

    @field_validator("password")
    @classmethod
    def _length(cls, v: str) -> str:
        if len(v) < config.PASSWORD_MIN_LENGTH:
            raise ValueError(f"must be at least {config.PASSWORD_MIN_LENGTH} characters")
        return _check_password_length(v)

    @field_validator("display_name")
    @classmethod
    def _strip_name(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None


class LoginIn(RequestModel):
    email: EmailStr
    password: str

    _email_length = field_validator("email", mode="before")(_check_email_length)
    # No minimum here: a short password is simply a wrong one. The maximum
    # still applies, or a login attempt could make us hash a megabyte.
    _password_length = field_validator("password")(_check_password_length)


class DeleteAccountIn(RequestModel):
    # Asked for again, at the moment of deleting: a token left signed in on a
    # shared machine should not be enough to destroy an account.
    password: str | None = None

    @field_validator("password")
    @classmethod
    def _length(cls, v: str | None) -> str | None:
        return v if v is None else _check_password_length(v)


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


class InterestIn(RequestModel):
    role: str
    rank: int = Field(ge=1, le=limits.INTERESTS_MAX)

    @field_validator("role")
    @classmethod
    def _known_role(cls, v: str) -> str:
        if v not in INTEREST_ROLES:
            raise ValueError(
                f"unknown role '{echo(v)}'; expected one of {', '.join(INTEREST_ROLES)}"
            )
        return v


class InterestOut(BaseModel):
    role: str
    label: str
    rank: int


class ResumeOut(BaseModel):
    filename: str
    uploaded_at: UtcDateTime
    skills: list[str]
    needs_ocr: bool


class ProfileIn(RequestModel):
    school: str = Field(min_length=1, max_length=limits.SCHOOL_MAX)
    major: str = Field(min_length=1, max_length=limits.MAJOR_MAX)
    minor: str | None = Field(default=None, max_length=limits.MINOR_MAX)
    degree_level: str = Field(min_length=1, max_length=limits.DEGREE_LEVEL_MAX)
    grad_year: int = Field(ge=2000, le=2100)
    # Optional, and not used by matching. Kept for the student's own record.
    gpa: Decimal | None = Field(default=None, ge=0, le=limits.GPA_MAX, allow_inf_nan=False)
    target_terms: list[str]
    preferred_locations: list[str]
    remote_ok: bool
    interests: list[InterestIn]
    # Present -> replaces resume_skills (lets the user delete a wrongly
    # extracted skill). Absent -> the extracted list is left alone.
    skills: list[str] | None = None

    @field_validator("preferred_locations")
    @classmethod
    def _locations(cls, v: list[str]) -> list[str]:
        return _bounded_strings(
            v, most=limits.LOCATIONS_MAX, chars=limits.LOCATION_CHARS_MAX, noun="locations"
        )

    @field_validator("skills")
    @classmethod
    def _skills(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return _bounded_strings(
            v, most=limits.SKILLS_MAX, chars=limits.SKILL_CHARS_MAX, noun="skills"
        )

    @field_validator("target_terms")
    @classmethod
    def _terms(cls, v: list[str]) -> list[str]:
        if len(v) > limits.TERMS_MAX:
            raise ValueError(f"at most {limits.TERMS_MAX} terms, not {len(v)}")
        kept: list[str] = []
        for raw in v:
            if not raw.strip():
                continue
            term = canonical_term(raw)
            if term is None:
                raise ValueError(
                    f"'{echo(raw)}' is not a term; use a season and a year, like 'Summer 2027'"
                )
            if term not in kept:
                kept.append(term)
        return kept

    @field_validator("minor")
    @classmethod
    def _blank_minor(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None

    @model_validator(mode="after")
    def _interests_are_a_ranking(self):
        n = len(self.interests)
        if not limits.INTERESTS_MIN <= n <= limits.INTERESTS_MAX:
            raise ValueError(
                f"interests: pick between {limits.INTERESTS_MIN} and {limits.INTERESTS_MAX} fields"
            )
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


class PresignIn(RequestModel):
    filename: str = Field(min_length=1, max_length=limits.FILENAME_MAX)
    content_type: str = Field(max_length=100)
    # The file's length in bytes. The upload is then held to exactly this.
    size: int

    @field_validator("size")
    @classmethod
    def _size(cls, v: int) -> int:
        if not limits.RESUME_MIN_BYTES <= v <= config.RESUME_MAX_BYTES:
            raise ValueError(
                f"a resume must be between {limits.RESUME_MIN_BYTES // 1024} KB and "
                f"{config.RESUME_MAX_BYTES / (1024 * 1024):g} MB"
            )
        return v


class PresignOut(BaseModel):
    upload_url: str
    key: str
    method: Literal["PUT"] = "PUT"
    headers: dict[str, str]


class CommitIn(RequestModel):
    key: str = Field(min_length=1, max_length=limits.STORAGE_KEY_MAX)
    filename: str = Field(min_length=1, max_length=limits.FILENAME_MAX)


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
    date_posted: UtcDateTime | None
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
# Freshness
# --------------------------------------------------------------------------- #


class IngestSourceOut(BaseModel):
    source: str
    last_success_at: UtcDateTime | None
    last_attempt_at: UtcDateTime | None
    fetched: int
    upserted: int
    deactivated: int
    error: str | None


class IngestStatusOut(BaseModel):
    last_success_at: UtcDateTime | None
    next_due_at: UtcDateTime | None
    # int when it is a whole number of hours (the usual 24), so the JSON reads
    # 24 and not 24.0.
    interval_hours: int | float
    auto: bool
    running: bool
    active_postings: int
    sources: list[IngestSourceOut]


class StatsOut(BaseModel):
    """Public. Counts of the shared board, and nothing about anyone."""

    active_postings: int
    companies: int
    role_families: int
    updated_at: UtcDateTime | None


# --------------------------------------------------------------------------- #
# Applications
# --------------------------------------------------------------------------- #


class ApplicationCreateIn(RequestModel):
    posting_id: str = Field(min_length=1, max_length=limits.POSTING_ID_MAX)
    applied_at: datetime | None = None


class EventIn(RequestModel):
    kind: str
    occurred_at: datetime | None = None
    note: str | None = Field(default=None, max_length=limits.NOTE_MAX)

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, v: str) -> str:
        if v not in EVENT_KINDS:
            raise ValueError(f"unknown event kind '{echo(v)}'")
        return v


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    occurred_at: UtcDateTime
    note: str | None
    source: str


class ApplicationSummaryOut(BaseModel):
    id: int
    posting: PostingOut
    status: str
    applied_at: UtcDateTime | None
    last_event_at: UtcDateTime | None


class ApplicationDetailOut(ApplicationSummaryOut):
    events: list[EventOut]
    next_transitions: list[str]


class ApplicationListOut(BaseModel):
    items: list[ApplicationSummaryOut]
