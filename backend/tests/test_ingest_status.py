"""GET /ingest/status: how fresh the listings are."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app import config
from app.models import IngestRun
from app.services import ingest_scheduler
from app.sources import backfill
from tests.conftest import age_runs
from tests.conftest import fake_source as fake

STATUS_KEYS = {
    "last_success_at", "next_due_at", "interval_hours", "auto", "running",
    "active_postings", "sources",
}  # fmt: skip
SOURCE_KEYS = {
    "source", "last_success_at", "last_attempt_at", "fetched", "upserted", "deactivated", "error",
}  # fmt: skip


def parse(stamp: str) -> datetime:
    assert stamp.endswith("Z"), stamp
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def test_status_requires_auth(client):
    r = client.get("/ingest/status")
    assert r.status_code == 401 and r.json() == {"detail": "Not authenticated."}


def test_status_before_any_ingest(client, auth):
    body = client.get("/ingest/status", headers=auth).json()
    assert set(body) == STATUS_KEYS
    assert body == {
        "last_success_at": None,
        "next_due_at": None,
        "interval_hours": 24,
        "auto": False,
        "running": False,
        "active_postings": 0,
        "sources": [
            {"source": s, "last_success_at": None, "last_attempt_at": None, "fetched": 0,
             "upserted": 0, "deactivated": 0, "error": None}
            for s in backfill.SOURCES
        ],
    }  # fmt: skip
    assert isinstance(body["interval_hours"], int)


def test_status_after_ingests(client, auth, db):
    ingest_scheduler.run_due({"simplify": fake("simplify"), "vanshb03": fake("vanshb03")})
    db.execute(
        text(
            "UPDATE ingest_runs SET finished_at = finished_at - interval '5 hours' "
            "WHERE source = 'simplify'"
        )
    )
    db.commit()

    body = client.get("/ingest/status", headers=auth).json()
    assert set(body) == STATUS_KEYS and all(set(s) == SOURCE_KEYS for s in body["sources"])
    by_source = {s["source"]: s for s in body["sources"]}
    assert [s["source"] for s in body["sources"]] == list(backfill.SOURCES)

    # The board is as fresh as its least recently refreshed source.
    assert body["last_success_at"] == by_source["simplify"]["last_success_at"]
    assert parse(by_source["simplify"]["last_success_at"]) < parse(
        by_source["vanshb03"]["last_success_at"]
    )
    assert parse(body["next_due_at"]) - parse(body["last_success_at"]) == timedelta(hours=24)
    assert datetime.now(UTC) - parse(body["last_success_at"]) < timedelta(hours=5, minutes=1)

    # Both fakes carry the same three jobs: shown once each.
    assert body["active_postings"] == 3 and body["running"] is False
    for s in (by_source["simplify"], by_source["vanshb03"]):
        assert (s["fetched"], s["upserted"], s["deactivated"], s["error"]) == (3, 3, 0, None)
        assert s["last_attempt_at"] == s["last_success_at"]


def test_status_shows_the_last_attempts_error_and_keeps_the_last_success(client, auth, db):
    ingest_scheduler.run_due({"simplify": fake("simplify")})
    age_runs(db, 25)
    ingest_scheduler.run_due({"simplify": fake("simplify", fail=True)})

    body = client.get("/ingest/status", headers=auth).json()
    s = body["sources"][0]
    assert s["error"] == "ConnectionError: github is down"
    assert (s["fetched"], s["upserted"], s["deactivated"]) == (0, 0, 0)
    assert parse(s["last_attempt_at"]) - parse(s["last_success_at"]) > timedelta(hours=24)
    assert body["last_success_at"] == s["last_success_at"]
    assert parse(body["next_due_at"]) < datetime.now(UTC)  # overdue, and it says so
    assert body["active_postings"] == 3  # the failed run closed nothing

    ingest_scheduler.run_due({"simplify": fake("simplify")})
    assert client.get("/ingest/status", headers=auth).json()["sources"][0]["error"] is None


def test_status_running_and_interrupted(client, auth, db):
    db.add(IngestRun(source="simplify"))
    db.commit()
    with backfill.ingest_lock(wait=False):
        body = client.get("/ingest/status", headers=auth).json()
        assert body["running"] is True
        assert body["sources"][0]["error"] is None  # in progress, not failed
        assert body["sources"][0]["last_attempt_at"] is not None
    body = client.get("/ingest/status", headers=auth).json()
    assert body["running"] is False
    assert body["sources"][0]["error"] == backfill.INTERRUPTED


def test_status_reports_a_fractional_interval(client, auth, monkeypatch):
    monkeypatch.setattr(config, "INGEST_INTERVAL_HOURS", 0.5)
    monkeypatch.setattr(config, "AUTO_INGEST", True)
    body = client.get("/ingest/status", headers=auth).json()
    assert body["interval_hours"] == 0.5 and body["auto"] is True
