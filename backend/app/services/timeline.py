"""Application timeline: the §6 state machine, in one place.

`applications.status` is DERIVED — it is always the kind of the newest
status-bearing event in `application_events`. `recompute_status()` is the
only code that assigns it, and it runs on every event insert. The frontend
renders its buttons from `next_transitions()` and never hard-codes the graph.

Where §6's diagram is silent or ambiguous, these are the choices (also in the
README):

  * `applied` may skip ahead to `oa_sent` or `interview_scheduled`: plenty of
    companies never send an acknowledgement, and forcing a fake one would
    make the timeline lie.
  * `oa_completed` (an event kind the diagram doesn't draw) sits between
    `oa_sent` and `interview_scheduled`.
  * `additional_round` leads back to `interviewed` (the extra round happens),
    or to `offer` / `rejected`.
  * `ghosted` is never user-settable, but a late reply can still move it to
    acknowledged / interview_scheduled / rejected / withdrawn.
  * `accepted`, `rejected`, `withdrawn` are terminal.
  * `note` and `outreach_sent` never change status.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app import config
from app.models import Application, ApplicationEvent

NON_STATUS_KINDS = frozenset({"note", "outreach_sent"})
TERMINAL = frozenset({"accepted", "rejected", "withdrawn"})

# status -> the kinds a user may record next. Ordered for button rendering:
# the happy path first, the exits last.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "applied": ("acknowledged", "oa_sent", "interview_scheduled", "rejected", "withdrawn"),
    "acknowledged": ("oa_sent", "interview_scheduled", "rejected", "withdrawn"),
    "oa_sent": ("oa_completed", "interview_scheduled", "rejected", "withdrawn"),
    "oa_completed": ("interview_scheduled", "rejected", "withdrawn"),
    "interview_scheduled": ("interviewed", "rejected", "withdrawn"),
    "interviewed": ("additional_round", "offer", "rejected", "withdrawn"),
    "additional_round": ("interviewed", "offer", "rejected", "withdrawn"),
    "offer": ("accepted", "rejected", "withdrawn"),
    "ghosted": ("acknowledged", "interview_scheduled", "rejected", "withdrawn"),
    "accepted": (),
    "rejected": (),
    "withdrawn": (),
}

# The only statuses the nightly ghosting rule looks at (§6).
GHOSTABLE = ("applied", "acknowledged")

# A user-entered occurred_at this far in the future is a typo (wrong year),
# not a scheduled event. A day of slack covers timezone skew.
_FUTURE_SLACK = timedelta(days=1)


class TransitionError(ValueError):
    """A user tried to record an event the state machine doesn't allow.
    The message is shown to the user verbatim."""


def _human(kind: str) -> str:
    return kind.replace("_", " ")


def next_transitions(status: str) -> list[str]:
    return list(TRANSITIONS.get(status, ()))


def _order_key(ev: ApplicationEvent):
    # id breaks ties between events recorded for the same instant; unflushed
    # events (id None) are the newest by construction.
    return (ev.occurred_at, ev.id if ev.id is not None else float("inf"))


def recompute_status(application: Application) -> str:
    """Derive status / applied_at / last_event_at from the event log.

    Called on every event insert. Nothing else assigns `status`.
    """
    events = sorted(application.events, key=_order_key)
    status_events = [e for e in events if e.kind not in NON_STATUS_KINDS]
    if not status_events:
        raise ValueError("an application needs at least one status event")
    application.status = status_events[-1].kind
    applied = [e for e in status_events if e.kind == "applied"]
    application.applied_at = applied[0].occurred_at if applied else None
    application.last_event_at = events[-1].occurred_at
    return application.status


def _append(
    db: Session,
    application: Application,
    *,
    kind: str,
    occurred_at: datetime,
    note: str | None,
    source: str,
) -> ApplicationEvent:
    event = ApplicationEvent(kind=kind, occurred_at=occurred_at, note=note, source=source)
    application.events.append(event)
    db.flush()
    recompute_status(application)
    return event


def start_application(
    db: Session, application: Application, applied_at: datetime | None = None
) -> ApplicationEvent:
    """Seed a new application with its 'applied' event ("Confirm you applied")."""
    return _append(
        db,
        application,
        kind="applied",
        occurred_at=applied_at or datetime.now(UTC),
        note=None,
        source="manual",
    )


def record_user_event(
    db: Session,
    application: Application,
    *,
    kind: str,
    occurred_at: datetime | None = None,
    note: str | None = None,
) -> ApplicationEvent:
    """Validate a user-entered event against the state machine, then append it."""
    now = datetime.now(UTC)
    occurred_at = occurred_at or now
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)

    if kind == "ghosted":
        raise TransitionError(
            f"'ghosted' is set automatically after {config.GHOST_AFTER_DAYS} days "
            "with no response; it can't be recorded by hand."
        )
    if kind == "note":
        if not (note and note.strip()):
            raise TransitionError("A note event needs some note text.")
    else:
        allowed = next_transitions(application.status)
        if kind not in allowed:
            if not allowed:
                raise TransitionError(
                    f"This application is {_human(application.status)}; "
                    "no further status changes are possible. You can still add a note."
                )
            raise TransitionError(
                f"Can't record '{_human(kind)}' while the application is "
                f"{_human(application.status)}. Next steps allowed: "
                + ", ".join(_human(k) for k in allowed)
                + "."
            )
        latest = max(
            (e.occurred_at for e in application.events if e.kind not in NON_STATUS_KINDS),
            default=None,
        )
        # Status is "newest event wins", so a backdated event older than the
        # current status would be silently ignored. Refuse it instead.
        if latest is not None and occurred_at < latest:
            raise TransitionError(
                f"'{_human(kind)}' can't be dated before the current status "
                f"({_human(application.status)}, {latest.date().isoformat()})."
            )
    if occurred_at > now + _FUTURE_SLACK:
        raise TransitionError("occurred_at can't be in the future.")

    return _append(db, application, kind=kind, occurred_at=occurred_at, note=note, source="manual")


def ghost_stale_applications(db: Session, now: datetime | None = None) -> int:
    """§6's nightly rule: applied|acknowledged and silent for GHOST_AFTER_DAYS
    -> a source='system' 'ghosted' event. Returns how many were ghosted.

    "Silent" means no status event since; the student's own notes don't count
    as the company replying.
    """
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=config.GHOST_AFTER_DAYS)
    newer_status_event = (
        select(ApplicationEvent.id)
        .where(
            and_(
                ApplicationEvent.application_id == Application.id,
                ApplicationEvent.kind.not_in(NON_STATUS_KINDS),
                ApplicationEvent.occurred_at >= cutoff,
            )
        )
        .exists()
    )
    stale = db.scalars(
        select(Application).where(Application.status.in_(GHOSTABLE), ~newer_status_event)
    ).all()
    for application in stale:
        _append(db, application, kind="ghosted", occurred_at=now, note=None, source="system")
    db.commit()
    return len(stale)
