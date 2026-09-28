"""Deterministic matching — §4 of docs/ARCHITECTURE.md.

Hard filters remove postings; six weighted components score what is left.
Every point on screen traces to a rule here, and every component that earns
points says why in `reasons`.

    Field match      30   best-ranked interest among the posting's roles
    Skills overlap   20   share of the skills the posting names that you have
    Location         15   same metro 15, same state 10, remote (if you're open to it) 15
    Term precision   15   exact target term 15, adjacent term 8
    Freshness        10   10 * exp(-days_since_posted / 30)
    Company signal   10   you saved or applied to another role at this company

**The score is out of what the posting could have earned.** A component is
left out of the denominator when it could not be earned at all:

    skills      the posting's title names no skill, or you have none on file
    location    the posting lists no location, or you gave no preference
    term        the posting declares no term, or you gave no target terms
    freshness   the posting has no date

    score = round(100 * earned / earnable)

Without this, a source that omits terms or locations would lose up to 30
points for what it didn't say, and be buried under better-labelled listings.

Scoring every open posting for one student is one SQL query and one Python
pass — no query per posting.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from sqlalchemy import delete, insert, text
from sqlalchemy.orm import Session

from app import config
from app.models import MatchScore, Profile
from app.services import locations, resume_parse
from app.sources.roles import ROLE_LABELS

W_ROLE, W_SKILLS, W_LOCATION, W_TERM, W_FRESH, W_COMPANY = 30, 20, 15, 15, 10, 10

# §4 gives three points on this curve — rank 1 -> 30, rank 2 -> 24, rank 5 ->
# 12 — which a constant step cannot satisfy (steps of 6 put rank 5 at 6).
# These values hit all three and fall evenly between. Flattening the tail
# further makes a student's 5th choice outrank a 1st-choice posting that is a
# week older; steepening it makes ranks 4 and 5 pointless to fill in.
ROLE_POINTS = {1: 30, 2: 24, 3: 20, 4: 16, 5: 12}

LOCATION_METRO, LOCATION_STATE, LOCATION_REMOTE = 15, 10, 15
TERM_EXACT, TERM_ADJACENT = 15, 8
# Freshness halves roughly every 21 days (30 * ln 2).
FRESH_DECAY_DAYS = 30
# Past this a "Posted N days ago" chip stops being a reason to apply. The
# points are still counted; only the chip is dropped.
FRESH_REASON_MAX_DAYS = 30

# Seasons in calendar order. "Winter 2026" is the December 2026 start, which
# is how the source lists label it, so it follows Fall of the same year.
_SEASONS = {"spring": 0, "summer": 1, "fall": 2, "autumn": 2, "winter": 3}

_DEGREE_SYNONYMS = {
    "bachelors": {"bachelors", "bachelor", "undergraduate", "undergrad", "bs", "ba", "bsc", "be"},
    "masters": {"masters", "master", "graduate", "ms", "ma", "msc", "meng"},
    "phd": {"phd", "doctorate", "doctoral"},
    "mba": {"mba"},
    "associates": {"associates", "associate", "aa", "as"},
}
_DEGREE_CANON = {alias: canon for canon, aliases in _DEGREE_SYNONYMS.items() for alias in aliases}


@dataclass
class Scored:
    posting_id: int
    score: int
    reasons: list[dict] = field(default_factory=list)
    # Points per component, as {code: (earned, earnable)}. Not persisted; it
    # is here so a score can be explained, and tested, to the point.
    breakdown: dict[str, tuple[float, int]] = field(default_factory=dict)


@dataclass
class StudentView:
    """The profile, pre-digested once so the per-posting loop does no parsing."""

    rank_by_role: dict[str, int]
    skills: set[str]
    places: list[locations.Place]
    remote_ok: bool
    term_index: dict[int, str]  # ordinal -> the student's own spelling
    degree: str | None

    @classmethod
    def from_profile(cls, profile: Profile) -> StudentView:
        return cls(
            rank_by_role={i.role: i.rank for i in profile.interests},
            skills=set(profile.resume_skills or []),
            places=[
                p
                for p in (locations.parse(loc) for loc in profile.preferred_locations or [])
                if p.city or p.region
            ],
            remote_ok=bool(profile.remote_ok),
            term_index={
                o: t for t in profile.target_terms or [] if (o := term_ordinal(t)) is not None
            },
            degree=normalize_degree(profile.degree_level),
        )


# --------------------------------------------------------------------------- #
# Small pure helpers
# --------------------------------------------------------------------------- #


def term_ordinal(term: str) -> int | None:
    """ "Summer 2027" -> a number where adjacent terms differ by 1."""
    parts = (term or "").strip().lower().split()
    if len(parts) != 2 or parts[0] not in _SEASONS or not parts[1].isdigit():
        return None
    return int(parts[1]) * 4 + _SEASONS[parts[0]]


def normalize_degree(value: str | None) -> str | None:
    key = "".join(ch for ch in (value or "").lower() if ch.isalnum())
    return _DEGREE_CANON.get(key)


@lru_cache(maxsize=50_000)
def title_skills(title: str) -> tuple[str, ...]:
    """Skills a posting's title names, in the order it names them. Titles
    repeat across postings and across rescoring runs, so this is cached per
    process."""
    return tuple(resume_parse.find_skills(title))


def _days_label(days: int) -> str:
    if days <= 0:
        return "Posted today"
    return "Posted 1 day ago" if days == 1 else f"Posted {days} days ago"


# --------------------------------------------------------------------------- #
# Hard filters
# --------------------------------------------------------------------------- #


def passes_filters(row, student: StudentView) -> bool:
    """Degree and term filters. Active/visible/age are applied in SQL.

    §4 says `terms` must overlap the target terms, but also awards 8 points
    for an *adjacent* term — which an exact-overlap filter would have already
    removed. So the filter admits exact and adjacent terms and drops the rest.
    """
    if row.degrees and student.degree:
        declared = {normalize_degree(d) for d in row.degrees}
        # Only filter on degrees we recognise; an unfamiliar label ("Bootcamp")
        # is not evidence the student is ineligible.
        known = declared - {None}
        if known and student.degree not in known:
            return False
    if row.terms and student.term_index:
        ordinals = [o for o in (term_ordinal(t) for t in row.terms) if o is not None]
        if ordinals and not any(
            abs(o - want) <= 1 for o in ordinals for want in student.term_index
        ):
            return False
    return True


# --------------------------------------------------------------------------- #
# The scorer
# --------------------------------------------------------------------------- #


def score_posting(row, student: StudentView, now: datetime) -> Scored:
    breakdown: dict[str, tuple[float, int]] = {}
    reasons: list[dict] = []

    def reason(code: str, label: str, detail: str | None) -> None:
        reasons.append({"code": code, "label": label, "detail": detail})

    # --- Field match (always earnable: every posting has a role) ---
    points = 0.0
    ranked = [(student.rank_by_role[r], r) for r in row.roles if r in student.rank_by_role]
    if ranked:
        rank, role = min(ranked)
        points = ROLE_POINTS.get(rank, 0)
        reason("role_rank", f"Matches your #{rank} field", ROLE_LABELS[role])
    breakdown["role_rank"] = (points, W_ROLE)

    # --- Skills ---
    asked = title_skills(row.title)
    if asked and student.skills:
        have = [s for s in asked if s in student.skills]
        if have:
            reason("skills", f"{len(have)} of your skills", ", ".join(have))
        breakdown["skills"] = (W_SKILLS * len(have) / len(asked), W_SKILLS)

    # --- Location ---
    if row.locations and (student.places or student.remote_ok):
        points = 0.0
        hit = locations.match(row.locations, student.places) if student.places else None
        if hit and hit[0] == "metro":
            points = LOCATION_METRO
            reason("location", "In one of your locations", hit[1])
        elif row.is_remote and student.remote_ok:
            points = LOCATION_REMOTE
            remote = next((loc for loc in row.locations if locations.parse(loc).remote), None)
            reason("location", "Remote friendly", remote)
        elif hit:
            points = LOCATION_STATE
            reason("location", "Same state as one of your locations", hit[1])
        breakdown["location"] = (points, W_LOCATION)

    # --- Term ---
    ordinals = {o: t for t in row.terms if (o := term_ordinal(t)) is not None}
    if ordinals and student.term_index:
        points = 0.0
        exact = sorted(o for o in ordinals if o in student.term_index)
        near = sorted(o for o in ordinals if any(abs(o - want) == 1 for want in student.term_index))
        if exact:
            points = TERM_EXACT
            reason("term", "Matches your target term", ordinals[exact[0]])
        elif near:
            points = TERM_ADJACENT
            reason("term", "Close to your target term", ordinals[near[0]])
        breakdown["term"] = (points, W_TERM)

    # --- Freshness ---
    if row.date_posted is not None:
        days = max(0.0, (now - row.date_posted).total_seconds() / 86_400)
        if days <= FRESH_REASON_MAX_DAYS:
            reason("fresh", _days_label(int(days)), None)
        breakdown["fresh"] = (W_FRESH * math.exp(-days / FRESH_DECAY_DAYS), W_FRESH)

    # --- Company signal (always earnable: any company can be one you know) ---
    points = 0.0
    if row.applied_here or row.saved_here:
        points = W_COMPANY
        label = "You applied here before" if row.applied_here else "You saved another role here"
        reason("company", label, row.company_name)
    breakdown["company"] = (points, W_COMPANY)

    earned = sum(e for e, _ in breakdown.values())
    earnable = sum(m for _, m in breakdown.values())
    return Scored(row.id, round(100 * earned / earnable), reasons, breakdown)


# One query: every open posting, plus whether the student already has history
# with its company. "History" excludes the posting itself — saving a role
# should not raise that role's own score.
_CANDIDATES = text(
    """
    WITH mine AS (
        SELECT p.company_id, p.id AS posting_id, TRUE AS applied
          FROM applications a JOIN postings p ON p.id = a.posting_id
         WHERE a.user_id = :user_id AND p.company_id IS NOT NULL
        UNION ALL
        SELECT p.company_id, p.id, FALSE
          FROM saved_postings s JOIN postings p ON p.id = s.posting_id
         WHERE s.user_id = :user_id AND p.company_id IS NOT NULL
    )
    SELECT p.id, p.title, p.company_name, p.roles, p.locations, p.is_remote,
           p.terms, p.degrees, p.date_posted,
           EXISTS (SELECT 1 FROM mine m WHERE m.company_id = p.company_id
                      AND m.posting_id <> p.id AND m.applied) AS applied_here,
           EXISTS (SELECT 1 FROM mine m WHERE m.company_id = p.company_id
                      AND m.posting_id <> p.id AND NOT m.applied) AS saved_here
      FROM postings p
     WHERE p.active AND p.is_visible
       AND (p.date_posted IS NULL OR p.date_posted >= :cutoff)
       AND (CAST(:company_id AS INTEGER) IS NULL OR p.company_id = :company_id)
    """
)


def score_all(
    db: Session,
    profile: Profile,
    *,
    now: datetime | None = None,
    company_id: int | None = None,
) -> list[Scored]:
    """Score every posting that survives the hard filters, for one student."""
    now = now or datetime.now(UTC)
    student = StudentView.from_profile(profile)
    rows = db.execute(
        _CANDIDATES,
        {
            "user_id": profile.user_id,
            "cutoff": now - timedelta(days=config.POSTING_MAX_AGE_DAYS),
            "company_id": company_id,
        },
    ).all()
    return [score_posting(r, student, now) for r in rows if passes_filters(r, student)]


# Namespaces pg_advisory_xact_lock so it can't collide with another feature's
# use of advisory locks on the same integers.
_LOCK_NAMESPACE = 5171


def rescore(
    db: Session,
    user_id: int,
    *,
    company_id: int | None = None,
    unless: Callable[[Profile], bool] | None = None,
) -> int:
    """Recompute and replace the cached match_scores for one student. Commits.

    With `company_id`, only that company's postings are rescored — what a
    save or an application needs, since the company signal is the only thing
    they change.

    An advisory lock serialises concurrent rescoring of the same student (the
    background task racing a status poll): the loser waits, then recomputes
    against the same data rather than interleaving its DELETE with the
    winner's INSERT. `unless` is asked once the lock is held, so a caller that
    only wants current scores can let the loser return without redoing the
    work the winner just committed.
    """
    db.execute(
        text("SELECT pg_advisory_xact_lock(:ns, :uid)"), {"ns": _LOCK_NAMESPACE, "uid": user_id}
    )
    profile = db.get(Profile, user_id, populate_existing=True)
    if profile is None or profile.onboarded_at is None or (unless and unless(profile)):
        db.rollback()
        return 0
    version = profile.profile_version
    now = datetime.now(UTC)
    scored = score_all(db, profile, now=now, company_id=company_id)

    stale = delete(MatchScore).where(MatchScore.user_id == user_id)
    if company_id is not None:
        stale = stale.where(
            MatchScore.posting_id.in_(
                text("SELECT id FROM postings WHERE company_id = :cid").bindparams(cid=company_id)
            )
        )
    db.execute(stale)
    if scored:
        db.execute(
            insert(MatchScore),
            [
                {
                    "user_id": user_id,
                    "posting_id": s.posting_id,
                    "score": s.score,
                    "reasons": s.reasons,
                    "profile_version": version,
                    "computed_at": now,
                }
                for s in scored
            ],
        )
    if company_id is None:
        profile.scores_version = version
        profile.scores_computed_at = now
    db.commit()
    return len(scored)
