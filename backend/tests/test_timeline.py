"""The derived-status helper and the §6 state machine."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models import Application, Company, Posting, User
from app.services import timeline
from app.services.timeline import TransitionError


def _app(db) -> Application:
    user = User(email="t@example.com")
    company = Company(name="Acme", normalized_name="acme")
    posting = Posting(
        source="t", source_id="1", title="SWE Intern", url="u", raw={}, company=company
    )
    db.add_all([user, posting])
    db.flush()
    app = Application(user_id=user.id, posting_id=posting.id, status="applied")
    db.add(app)
    return app


T0 = datetime(2026, 9, 1, tzinfo=UTC)


def test_recompute_status_follows_newest_status_event(db):
    app = _app(db)
    timeline.start_application(db, app, applied_at=T0)
    assert app.status == "applied" and app.applied_at == T0
    timeline.record_user_event(db, app, kind="acknowledged", occurred_at=T0 + timedelta(days=2))
    timeline.record_user_event(
        db, app, kind="interview_scheduled", occurred_at=T0 + timedelta(days=5)
    )
    assert app.status == "interview_scheduled"
    assert timeline.next_transitions(app.status) == ["interviewed", "rejected", "withdrawn"]


def test_notes_do_not_change_status_but_move_last_event(db):
    app = _app(db)
    timeline.start_application(db, app, applied_at=T0)
    timeline.record_user_event(
        db, app, kind="note", note="Called recruiter", occurred_at=T0 + timedelta(days=1)
    )
    assert app.status == "applied"
    assert app.last_event_at == T0 + timedelta(days=1)


def test_recompute_ignores_insert_order(db):
    """Status is the newest by occurred_at, not the last inserted."""
    app = _app(db)
    timeline.start_application(db, app, applied_at=T0)
    timeline.record_user_event(db, app, kind="rejected", occurred_at=T0 + timedelta(days=9))
    # A system event dated earlier (e.g. a late-parsed email) must not win.
    timeline._append(
        db, app, kind="acknowledged", occurred_at=T0 + timedelta(days=3), note=None, source="gmail"
    )
    assert app.status == "rejected"


def test_illegal_transition_is_rejected(db):
    app = _app(db)
    timeline.start_application(db, app, applied_at=T0)
    with pytest.raises(TransitionError, match="Next steps allowed"):
        timeline.record_user_event(db, app, kind="offer")


def test_ghosted_is_not_user_settable(db):
    app = _app(db)
    timeline.start_application(db, app, applied_at=T0)
    with pytest.raises(TransitionError, match="automatically"):
        timeline.record_user_event(db, app, kind="ghosted")


def test_terminal_states_have_no_transitions(db):
    for status in ("accepted", "rejected", "withdrawn"):
        assert timeline.next_transitions(status) == []
    app = _app(db)
    timeline.start_application(db, app, applied_at=T0)
    timeline.record_user_event(db, app, kind="withdrawn", occurred_at=T0 + timedelta(days=1))
    with pytest.raises(TransitionError, match="no further status changes"):
        timeline.record_user_event(db, app, kind="acknowledged")
    # ...but a note is always allowed.
    timeline.record_user_event(db, app, kind="note", note="Took another offer")


def test_backdating_before_current_status_is_rejected(db):
    app = _app(db)
    timeline.start_application(db, app, applied_at=T0)
    with pytest.raises(TransitionError, match="can't be dated before"):
        timeline.record_user_event(db, app, kind="acknowledged", occurred_at=T0 - timedelta(days=1))


def test_every_nonterminal_status_can_withdraw():
    for status, nxt in timeline.TRANSITIONS.items():
        if status not in timeline.TERMINAL:
            assert "withdrawn" in nxt, status
        assert "ghosted" not in nxt


def test_ghost_job_marks_silent_applications(db):
    now = datetime(2026, 9, 28, tzinfo=UTC)
    stale = _app(db)
    timeline.start_application(db, stale, applied_at=now - timedelta(days=45))
    # A note inside the window is the student talking, not the company.
    timeline.record_user_event(
        db, stale, kind="note", note="still waiting", occurred_at=now - timedelta(days=2)
    )
    db.commit()

    assert timeline.ghost_stale_applications(db, now=now) == 1
    db.refresh(stale)
    assert stale.status == "ghosted"
    assert stale.events[-1].source == "system"
    # Idempotent: ghosted isn't ghostable.
    assert timeline.ghost_stale_applications(db, now=now) == 0
    # A late reply still moves it.
    assert "interview_scheduled" in timeline.next_transitions("ghosted")


def test_ghost_job_skips_recent_applications(db):
    now = datetime(2026, 9, 28, tzinfo=UTC)
    fresh = _app(db)
    timeline.start_application(db, fresh, applied_at=now - timedelta(days=10))
    db.commit()
    assert timeline.ghost_stale_applications(db, now=now) == 0
