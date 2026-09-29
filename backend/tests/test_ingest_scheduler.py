"""Automatic refresh: what the scheduler decides, with fake sources and no
network."""

import time

import pytest
from sqlalchemy import func, select, text

from app import config
from app.models import IngestRun, Posting
from app.services import ingest_scheduler
from app.sources import backfill
from tests.conftest import INGEST_ROWS as ROWS
from tests.conftest import age_runs, make_row, onboard, register
from tests.conftest import fake_source as fake


def runs(db) -> list[IngestRun]:
    db.expire_all()
    return list(db.scalars(select(IngestRun).order_by(IngestRun.id)))


# --------------------------------------------------------------------------- #
# Deciding
# --------------------------------------------------------------------------- #


def test_never_ingested_is_due_and_runs(db):
    registry = {"simplify": fake("simplify"), "vanshb03": fake("vanshb03")}
    assert ingest_scheduler.due_sources(db, list(registry)) == ["simplify", "vanshb03"]

    results = ingest_scheduler.run_due(registry)
    assert [(r.source, r.fetched, r.upserted, r.error) for r in results] == [
        ("simplify", 3, 3, None),
        ("vanshb03", 3, 3, None),
    ]
    assert all(r.duration_ms >= 0 for r in results)
    assert db.scalar(select(func.count()).select_from(Posting)) == 6
    assert [(r.source, r.error, r.finished_at is not None) for r in runs(db)] == [
        ("simplify", None, True),
        ("vanshb03", None, True),
    ]


def test_fresh_is_skipped_without_fetching(db):
    registry = {"simplify": fake("simplify")}
    ingest_scheduler.run_due(registry)
    assert registry["simplify"].fetches == 1

    assert ingest_scheduler.run_due(registry) == []
    assert registry["simplify"].fetches == 1
    assert len(runs(db)) == 1


@pytest.mark.parametrize(("hours_ago", "due"), [(23, False), (24, True), (25, True), (72, True)])
def test_due_once_the_interval_has_passed(db, hours_ago, due):
    registry = {"simplify": fake("simplify")}
    ingest_scheduler.run_due(registry)
    age_runs(db, hours_ago)
    assert (ingest_scheduler.due_sources(db, ["simplify"]) == ["simplify"]) is due
    ran = ingest_scheduler.run_due(registry)
    assert len(ran) == (1 if due else 0)
    assert registry["simplify"].fetches == (2 if due else 1)


def test_only_the_stale_source_runs(db):
    registry = {"simplify": fake("simplify"), "vanshb03": fake("vanshb03")}
    ingest_scheduler.run_due(registry)
    db.execute(
        text(
            "UPDATE ingest_runs SET finished_at = finished_at - interval '30 hours' "
            "WHERE source = 'vanshb03'"
        )
    )
    db.commit()
    assert [r.source for r in ingest_scheduler.run_due(registry)] == ["vanshb03"]
    assert registry["simplify"].fetches == 1 and registry["vanshb03"].fetches == 2


def test_interval_is_configurable(db, monkeypatch):
    registry = {"simplify": fake("simplify")}
    ingest_scheduler.run_due(registry)
    age_runs(db, 2)
    assert ingest_scheduler.run_due(registry) == []
    monkeypatch.setattr(config, "INGEST_INTERVAL_HOURS", 1.0)
    assert len(ingest_scheduler.run_due(registry)) == 1


def test_a_failed_run_is_retried_at_the_next_check(db):
    good = {"simplify": fake("simplify")}
    ingest_scheduler.run_due(good)
    age_runs(db, 25)
    before = {p.source_id: (p.active, p.content_hash) for p in db.scalars(select(Posting))}

    broken = {"simplify": fake("simplify", fail=True)}
    (failed,) = ingest_scheduler.run_due(broken)
    assert failed.error == "ConnectionError: github is down"
    assert (failed.fetched, failed.upserted, failed.deactivated) == (0, 0, 0)

    # The error is on the ledger, and the postings are exactly as they were.
    last = runs(db)[-1]
    assert last.error == "ConnectionError: github is down" and last.finished_at is not None
    db.expire_all()
    after = {p.source_id: (p.active, p.content_hash) for p in db.scalars(select(Posting))}
    assert after == before

    # Still due: the very next check tries again, not the one 24 hours on.
    assert ingest_scheduler.due_sources(db, ["simplify"]) == ["simplify"]
    ingest_scheduler.run_due(broken)
    assert broken["simplify"].fetches == 2

    (recovered,) = ingest_scheduler.run_due(good)
    assert recovered.error is None
    assert ingest_scheduler.run_due(good) == []
    assert [r.error is None for r in runs(db)] == [True, False, False, True]


def test_a_truncated_feed_is_not_a_success(db, monkeypatch):
    """The guard refuses to close the board and records why. That run must not
    reset the clock: upstream looked broken, so look again soon."""
    monkeypatch.setattr(config, "DEACTIVATE_GUARD_RATIO", 0.5)
    ingest_scheduler.run_due({"simplify": fake("simplify")})
    age_runs(db, 25)
    (result,) = ingest_scheduler.run_due({"simplify": fake("simplify", rows=ROWS[:1])})
    assert "skipped deactivation" in result.error and result.deactivated == 0
    assert db.scalar(select(func.count()).where(Posting.active.is_(True))) == 3
    assert ingest_scheduler.due_sources(db, ["simplify"]) == ["simplify"]


def test_stands_down_when_another_process_holds_the_lock(db):
    registry = {"simplify": fake("simplify")}
    with backfill.ingest_lock(wait=False) as held:
        assert held is True
        assert backfill.is_running(db) is True
        assert ingest_scheduler.run_due(registry) is None
        # A second taker on its own connection is refused as well.
        with backfill.ingest_lock(wait=False) as second:
            assert second is False
    assert registry["simplify"].fetches == 0 and runs(db) == []

    # Released with the block, so the next check goes ahead.
    assert backfill.is_running(db) is False
    assert len(ingest_scheduler.run_due(registry)) == 1


def test_lock_is_released_when_the_ingest_raises(db):
    with pytest.raises(RuntimeError), backfill.ingest_lock(wait=False):
        raise RuntimeError("boom")
    assert backfill.is_running(db) is False


def test_runs_left_unfinished_by_a_dead_process_are_closed(db):
    db.add(IngestRun(source="simplify"))  # started, never finished
    db.commit()
    ingest_scheduler.run_due({"simplify": fake("simplify")})
    first, second = runs(db)
    assert first.error == backfill.INTERRUPTED and first.finished_at is not None
    assert second.error is None


def test_manual_backfill_takes_the_same_lock(db, monkeypatch):
    monkeypatch.setattr(backfill, "SOURCES", {"simplify": fake("simplify")})
    seen = []
    real = backfill.ingest

    def spy(session, source, postings=None):
        seen.append(backfill.is_running(session))
        return real(session, source, postings)

    monkeypatch.setattr(backfill, "ingest", spy)
    backfill.run_all(db, "all")
    assert seen == [True]
    assert backfill.is_running(db) is False


# --------------------------------------------------------------------------- #
# The background task
# --------------------------------------------------------------------------- #


def test_scheduler_is_off_under_pytest():
    assert config.AUTO_INGEST is False


def _wait_for(condition, seconds=3.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_lifespan_checks_at_startup_and_keeps_checking(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    calls = []
    monkeypatch.setattr(config, "AUTO_INGEST", True)
    monkeypatch.setattr(ingest_scheduler, "_MIN_CHECK_SECONDS", 0.05)
    monkeypatch.setattr(config, "INGEST_CHECK_MINUTES", 0.0)
    monkeypatch.setattr(ingest_scheduler, "run_due", lambda: calls.append(time.monotonic()))

    with TestClient(app) as client:
        assert _wait_for(lambda: len(calls) >= 1), "no check at startup"
        assert _wait_for(lambda: len(calls) >= 3), "did not keep checking"
        # Requests are served while it runs.
        assert client.get("/health").status_code == 200
    stopped = len(calls)
    time.sleep(0.3)
    assert len(calls) == stopped, "kept running after shutdown"


def test_lifespan_does_not_start_it_when_off(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    calls = []
    monkeypatch.setattr(ingest_scheduler, "run_due", lambda: calls.append(1))
    with TestClient(app):
        time.sleep(0.2)
    assert calls == []


def test_a_failing_check_does_not_end_the_loop(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database went away")

    monkeypatch.setattr(config, "AUTO_INGEST", True)
    monkeypatch.setattr(ingest_scheduler, "_MIN_CHECK_SECONDS", 0.05)
    monkeypatch.setattr(config, "INGEST_CHECK_MINUTES", 0.0)
    monkeypatch.setattr(ingest_scheduler, "run_due", flaky)
    with TestClient(app):
        assert _wait_for(lambda: len(calls) >= 2)


# --------------------------------------------------------------------------- #
# Feeds see what the scheduler brought in
# --------------------------------------------------------------------------- #


def test_feed_picks_up_postings_from_a_scheduled_run(client, db):
    registry = {"simplify": fake("simplify")}
    ingest_scheduler.run_due(registry)
    headers = register(client)
    onboard(client, headers)
    assert client.get("/feed", headers=headers).json()["total"] == 3

    age_runs(db, 25)
    db.execute(text("UPDATE profiles SET scores_computed_at = now() - interval '1 hour'"))
    db.commit()
    newer = [r for r in ROWS if r["id"] != "c"] + [
        make_row("d", "Machine Learning Intern", "Hooli", days_ago=0, category="AI/ML/Data")
    ]
    (result,) = ingest_scheduler.run_due({"simplify": fake("simplify", rows=newer)})
    assert (result.inserted, result.deactivated) == (1, 1)

    body = client.get("/feed", headers=headers).json()
    items = {i["id"]: i for i in body["items"]}
    assert body["total"] == 3 and set(items) == {"simplify:a", "simplify:b", "simplify:d"}
    # The new posting arrives scored, not merely listed.
    assert isinstance(items["simplify:d"]["score"], int) and items["simplify:d"]["reasons"]
