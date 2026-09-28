"""ORM models — §3 of docs/ARCHITECTURE.md, SQLAlchemy 2.0 `Mapped[]` style.

Deviations from the §3 listing, each forced by something the doc asks for
elsewhere (see the final report / README for the full list):

  * postings.company_name — denormalized copy of companies.name. The
    `search_tsv` generated column must read it, and a generated column cannot
    reference another table.
  * postings.roles TEXT[] — the classifier output (app/sources/roles.py),
    which is what matching and the feed filter actually use. `category` stays
    as the raw source category for provenance and as the classifier fallback.
  * postings.is_visible — §4 hard-filters on it; §3 omits it.
  * profile_interests.role instead of `category`, constrained to the roles.py
    vocabulary.
  * profiles.resume_filename / resume_uploaded_at / resume_needs_ocr — the
    GET /profile contract returns them; resume_needs_ocr is named in the brief.
  * profiles.scores_version / scores_computed_at — the profile_version the
    cached match_scores were computed under. "Ready" is a comparison against
    this, which stays correct even when zero postings survive the filters (in
    which case there are no match_scores rows to inspect).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.sources.roles import OTHER as ROLE_OTHER
from app.sources.roles import ROLE_LABELS

# Roles a student may rank as an interest. `other` is a classifier bucket for
# unclassifiable titles, not a field anyone wants to be matched to.
INTEREST_ROLES: tuple[str, ...] = tuple(r for r in ROLE_LABELS if r != ROLE_OTHER)

EVENT_KINDS: tuple[str, ...] = (
    "applied",
    "acknowledged",
    "oa_sent",
    "oa_completed",
    "interview_scheduled",
    "interviewed",
    "additional_round",
    "offer",
    "accepted",
    "rejected",
    "withdrawn",
    "ghosted",
    "note",
    "outreach_sent",
)
EVENT_SOURCES: tuple[str, ...] = ("manual", "gmail", "system")


def _in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join("'" + v.replace("'", "''") + "'" for v in values)
    return f"{column} IN ({quoted})"


TS = DateTime(timezone=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    cognito_sub: Mapped[str | None] = mapped_column(String(64), unique=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    # Local mode only. Cognito owns passwords in prod; this stays NULL there.
    password_hash: Mapped[str | None] = mapped_column(String(128))
    display_name: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())

    profile: Mapped[Profile | None] = relationship(back_populates="user")


class Profile(Base):
    __tablename__ = "profiles"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Nullable because a resume can be committed during onboarding, before the
    # form itself is saved; onboarded_at marks the profile as complete.
    school: Mapped[str | None] = mapped_column(String(200))
    major: Mapped[str | None] = mapped_column(String(200))
    minor: Mapped[str | None] = mapped_column(String(200))
    degree_level: Mapped[str | None] = mapped_column(String(40))
    grad_year: Mapped[int | None] = mapped_column(SmallInteger)
    gpa: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    target_terms: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'"), default=list
    )
    preferred_locations: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'"), default=list
    )
    remote_ok: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    work_auth: Mapped[str | None] = mapped_column(String(80))
    resume_s3_key: Mapped[str | None] = mapped_column(String(512))
    resume_filename: Mapped[str | None] = mapped_column(String(255))
    resume_uploaded_at: Mapped[datetime | None] = mapped_column(TS)
    resume_text: Mapped[str | None] = mapped_column(Text)
    resume_skills: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'"), default=list
    )
    resume_needs_ocr: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
    onboarded_at: Mapped[datetime | None] = mapped_column(TS)
    profile_version: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    scores_version: Mapped[int | None] = mapped_column(Integer)
    scores_computed_at: Mapped[datetime | None] = mapped_column(TS)

    user: Mapped[User] = relationship(back_populates="profile")
    interests: Mapped[list[ProfileInterest]] = relationship(
        order_by="ProfileInterest.rank", cascade="all, delete-orphan"
    )


class ProfileInterest(Base):
    """The "3–5 fields" a student ranks. Rank 1 is the strongest interest."""

    __tablename__ = "profile_interests"
    __table_args__ = (
        UniqueConstraint("user_id", "rank", name="uq_profile_interests_user_rank"),
        CheckConstraint("rank BETWEEN 1 AND 5", name="ck_profile_interests_rank"),
        CheckConstraint(_in("role", INTEREST_ROLES), name="ck_profile_interests_role"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("profiles.user_id", ondelete="CASCADE"), primary_key=True
    )
    # The PK doubles as UNIQUE(user_id, role).
    role: Mapped[str] = mapped_column(String(40), primary_key=True)
    rank: Mapped[int] = mapped_column(SmallInteger)


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        # Trigram index for the fuzzy cross-source dedupe §3 reserves pg_trgm for.
        Index(
            "ix_companies_normalized_name_trgm",
            "normalized_name",
            postgresql_using="gin",
            postgresql_ops={"normalized_name": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    normalized_name: Mapped[str] = mapped_column(String(300), unique=True)
    url: Mapped[str | None] = mapped_column(Text)


class Posting(Base):
    __tablename__ = "postings"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_postings_source_source_id"),
        Index("ix_postings_search_tsv", "search_tsv", postgresql_using="gin"),
        Index("ix_postings_locations", "locations", postgresql_using="gin"),
        Index("ix_postings_roles", "roles", postgresql_using="gin"),
        Index("ix_postings_active_date_posted", "active", text("date_posted DESC")),
        Index("ix_postings_category_active", "category", "active"),
        Index("ix_postings_company_id", "company_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(String(128))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    company_name: Mapped[str | None] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(80))
    roles: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    locations: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    is_remote: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    terms: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    degrees: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    url: Mapped[str] = mapped_column(Text)
    date_posted: Mapped[datetime | None] = mapped_column(TS)
    date_updated: Mapped[datetime | None] = mapped_column(TS)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    is_visible: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    salary_max: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    salary_unit: Mapped[str | None] = mapped_column(String(8))
    raw: Mapped[dict] = mapped_column(JSONB)
    # NULL after an absence-deactivation, so a posting that reappears unchanged
    # is still rewritten (and reactivated) instead of skipped as "unchanged".
    content_hash: Mapped[str | None] = mapped_column(String(64))
    search_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('english'::regconfig, title || ' ' || coalesce(company_name, ''))",
            persisted=True,
        ),
    )
    first_seen_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())

    company: Mapped[Company | None] = relationship()

    @property
    def public_id(self) -> str:
        """The API's id for a posting: "{source}:{source_id}"."""
        return f"{self.source}:{self.source_id}"


class MatchScore(Base):
    __tablename__ = "match_scores"
    __table_args__ = (Index("ix_match_scores_user_score", "user_id", text("score DESC")),)

    # The composite PK is UNIQUE(user_id, posting_id).
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    posting_id: Mapped[int] = mapped_column(
        ForeignKey("postings.id", ondelete="CASCADE"), primary_key=True
    )
    score: Mapped[int] = mapped_column(SmallInteger)
    reasons: Mapped[list] = mapped_column(JSONB)
    profile_version: Mapped[int] = mapped_column(Integer)
    computed_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class SavedPosting(Base):
    __tablename__ = "saved_postings"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    posting_id: Mapped[int] = mapped_column(
        ForeignKey("postings.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("user_id", "posting_id", name="uq_applications_user_posting"),
        Index("ix_applications_user_last_event", "user_id", text("last_event_at DESC")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    posting_id: Mapped[int] = mapped_column(ForeignKey("postings.id", ondelete="CASCADE"))
    # Derived from application_events by services/timeline.recompute_status().
    # Never assigned anywhere else.
    status: Mapped[str] = mapped_column(String(32))
    applied_at: Mapped[datetime | None] = mapped_column(TS)
    last_event_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())

    posting: Mapped[Posting] = relationship()
    events: Mapped[list[ApplicationEvent]] = relationship(
        order_by="(ApplicationEvent.occurred_at, ApplicationEvent.id)",
        cascade="all, delete-orphan",
        back_populates="application",
    )


class ApplicationEvent(Base):
    """Append-only. The history is the timeline UI; status is derived from it."""

    __tablename__ = "application_events"
    __table_args__ = (
        CheckConstraint(_in("kind", EVENT_KINDS), name="ck_application_events_kind"),
        CheckConstraint(_in("source", EVENT_SOURCES), name="ck_application_events_source"),
        Index("ix_application_events_app_occurred", "application_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))
    occurred_at: Mapped[datetime] = mapped_column(TS)
    note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), server_default=text("'manual'"))
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())

    application: Mapped[Application] = relationship(back_populates="events")


# --- Tables §3 defines for later steps (outreach, integrations). Created now
# so the schema matches the spec in one revision; no routes use them yet. ---


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    linkedin_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class OutreachMessage(Base):
    __tablename__ = "outreach_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    channel: Mapped[str] = mapped_column(String(32))
    subject: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))
    follow_up_due_at: Mapped[datetime | None] = mapped_column(TS)
    sent_at: Mapped[datetime | None] = mapped_column(TS)


class Integration(Base):
    __tablename__ = "integrations"
    __table_args__ = (
        CheckConstraint(
            _in("provider", ("gmail", "github", "linkedin")), name="ck_integrations_provider"
        ),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(String(16), primary_key=True)
    external_id: Mapped[str | None] = mapped_column(String(200))
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    # An ARN into Secrets Manager / SSM. Tokens themselves never live in a column.
    token_secret_arn: Mapped[str | None] = mapped_column(Text)
    connected_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(TS)


class IngestRun(Base):
    """Freshness ledger: when the feed looks stale, this says whether last
    night's pull ran, instead of guessing."""

    __tablename__ = "ingest_runs"
    __table_args__ = (Index("ix_ingest_runs_source_started", "source", text("started_at DESC")),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(TS)
    fetched: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    upserted: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    deactivated: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(Text)
