"""Backfill idempotency against a fake source: run twice, nothing changes; then
a changed row is updated, a dropped row is deactivated, a reappearing row is
reactivated, and a broken fetch touches nothing."""

import json
from pathlib import Path

from sqlalchemy import select

from app import config
from app.models import Company, IngestRun, Posting
from app.sources import simplify
from app.sources.backfill import ingest
from app.sources.base import Source

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "simplify_sample.json").read_text())


class FakeSimplify(Source):
    name = "simplify"

    def __init__(self, rows, fail=False):
        self.rows, self.fail = rows, fail

    def fetch(self):
        if self.fail:
            raise ConnectionError("github is down")
        return [simplify.normalize_row(r) for r in self.rows]


def _snapshot(db):
    return {
        p.source_id: (p.title, p.content_hash, p.active, p.roles, p.company_id, p.first_seen_at)
        for p in db.scalars(select(Posting))
    }


def test_backfill_twice_is_idempotent(db):
    first = ingest(db, FakeSimplify(FIXTURE))
    assert first.error is None
    assert first.fetched == len(FIXTURE) and first.inserted == len(FIXTURE)
    assert first.updated == 0 and first.deactivated == 0
    before = _snapshot(db)
    db.expire_all()

    second = ingest(db, FakeSimplify(FIXTURE))
    assert second.error is None
    assert second.upserted == 0 and second.deactivated == 0
    assert second.unchanged == len(FIXTURE)
    assert _snapshot(db) == before

    runs = db.scalars(select(IngestRun).order_by(IngestRun.id)).all()
    assert len(runs) == 2
    assert (runs[0].fetched, runs[0].upserted) == (len(FIXTURE), len(FIXTURE))
    assert (runs[1].fetched, runs[1].upserted, runs[1].deactivated) == (len(FIXTURE), 0, 0)
    assert all(r.finished_at is not None and r.error is None for r in runs)


def test_backfill_updates_changed_and_deactivates_missing(db):
    ingest(db, FakeSimplify(FIXTURE))
    db.expire_all()
    changed = dict(FIXTURE[0], title=FIXTURE[0]["title"] + " - Machine Learning")
    dropped = FIXTURE[1]
    result = ingest(db, FakeSimplify([changed, *FIXTURE[2:]]))
    assert result.error is None
    assert result.updated == 1 and result.inserted == 0
    assert result.deactivated == (1 if dropped["active"] else 0)
    db.expire_all()

    row = db.scalar(select(Posting).where(Posting.source_id == changed["id"]))
    assert row.title == changed["title"]
    assert "ai_ml_data" in row.roles  # re-classified on update
    gone = db.scalar(select(Posting).where(Posting.source_id == dropped["id"]))
    assert gone is not None and gone.active is False and gone.content_hash is None

    # It comes back unchanged -> rewritten and reactivated, not skipped.
    back = ingest(db, FakeSimplify(FIXTURE))
    db.expire_all()
    gone = db.scalar(select(Posting).where(Posting.source_id == dropped["id"]))
    assert gone.active == dropped["active"]
    assert back.updated >= 1


def test_failed_fetch_records_error_and_deactivates_nothing(db):
    ingest(db, FakeSimplify(FIXTURE))
    active_before = db.scalar(select(Posting).where(Posting.active.is_(True))) is not None
    result = ingest(db, FakeSimplify(FIXTURE, fail=True))
    assert result.error and "github is down" in result.error
    assert result.fetched == 0 and result.deactivated == 0
    db.expire_all()
    assert (db.scalar(select(Posting).where(Posting.active.is_(True))) is not None) == active_before
    run = db.scalars(select(IngestRun).order_by(IngestRun.id.desc())).first()
    assert run.error and run.finished_at is not None


def test_truncated_feed_does_not_close_the_board(db, monkeypatch):
    ingest(db, FakeSimplify(FIXTURE))
    monkeypatch.setattr(config, "DEACTIVATE_GUARD_RATIO", 0.5)
    result = ingest(db, FakeSimplify(FIXTURE[:1]))
    assert result.deactivated == 0
    assert result.error and "skipped deactivation" in result.error
    db.expire_all()
    active = db.scalars(select(Posting.source_id).where(Posting.active.is_(True))).all()
    assert len(active) == sum(1 for r in FIXTURE if r["active"])


def test_companies_are_deduped_by_normalized_name(db):
    rows = [
        dict(FIXTURE[0], id="a", company_name="Acme Corp"),
        dict(FIXTURE[0], id="b", company_name="ACME Corporation"),
    ]
    ingest(db, FakeSimplify(rows))
    companies = db.scalars(select(Company)).all()
    assert len(companies) == 1 and companies[0].name == "Acme Corp"
    ids = {p.company_id for p in db.scalars(select(Posting))}
    assert ids == {companies[0].id}
