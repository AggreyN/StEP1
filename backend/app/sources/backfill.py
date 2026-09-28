"""Pull every source into `postings`, idempotently.

    python -m app.sources.backfill [--source=all|simplify|vanshb03]

Per source, in one transaction:

  1. fetch + normalize (a failed fetch records an ingest_runs error and
     touches nothing — an empty result must never look like "everything closed")
  2. upsert companies by normalized_name
  3. compare each row's content_hash with what's stored: new and changed rows
     go through one bulk INSERT ... ON CONFLICT (source, source_id) DO UPDATE;
     unchanged rows are skipped (they only get their last_seen_at bumped, in
     one statement)
  4. rows that are stored as active but absent from the feed -> active=false,
     guarded so a truncated upstream file can't close the whole board
  5. one ingest_runs row: fetched / upserted / deactivated / error

Nothing is filtered at ingest. Inactive and invisible rows are stored as-is
and excluded on read.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app import config
from app.models import Company, IngestRun, Posting
from app.sources.base import NormalizedPosting, Source, normalize_company
from app.sources.simplify import SimplifySource
from app.sources.vanshb03 import Vanshb03Source

log = logging.getLogger(__name__)

SOURCES: dict[str, type[Source]] = {
    SimplifySource.name: SimplifySource,
    Vanshb03Source.name: Vanshb03Source,
}

# Rows per INSERT statement. psycopg's parameter limit is 65,535; postings
# have ~22 columns, so 1,000 rows is a comfortable ~22k parameters.
_BATCH = 1000


@dataclass
class RunResult:
    source: str
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    deactivated: int = 0
    error: str | None = None

    @property
    def upserted(self) -> int:
        return self.inserted + self.updated


def _upsert_companies(db: Session, postings: list[NormalizedPosting]) -> dict[str, int]:
    """Ensure a companies row per distinct normalized name; return name -> id."""
    by_key: dict[str, tuple[str, str | None]] = {}
    for p in postings:
        key = normalize_company(p.company_name)
        # First spelling wins for display; a URL from any row beats none.
        name, url = by_key.get(key, (p.company_name, None))
        by_key[key] = (name, url or p.company_url)
    if not by_key:
        return {}
    rows = [{"name": n, "normalized_name": k, "url": u} for k, (n, u) in by_key.items()]
    for i in range(0, len(rows), _BATCH):
        stmt = pg_insert(Company).values(rows[i : i + _BATCH])
        stmt = stmt.on_conflict_do_update(
            index_elements=[Company.normalized_name],
            set_={"url": func.coalesce(Company.url, stmt.excluded.url)},
        )
        db.execute(stmt)
    keys = list(by_key)
    mapping: dict[str, int] = {}
    for i in range(0, len(keys), 5000):
        for cid, key in db.execute(
            select(Company.id, Company.normalized_name).where(
                Company.normalized_name.in_(keys[i : i + 5000])
            )
        ):
            mapping[key] = cid
    return mapping


def _row(p: NormalizedPosting, company_ids: dict[str, int], now: datetime) -> dict:
    return {
        "source": p.source,
        "source_id": p.source_id,
        "company_id": company_ids.get(normalize_company(p.company_name)),
        "company_name": p.company_name,
        "title": p.title,
        "category": p.category,
        "roles": p.roles,
        "locations": p.locations,
        "is_remote": p.is_remote,
        "terms": p.terms,
        "degrees": p.degrees,
        "url": p.url,
        "date_posted": p.date_posted,
        "date_updated": p.date_updated,
        "active": p.active,
        "is_visible": p.is_visible,
        "salary_min": p.salary_min,
        "salary_max": p.salary_max,
        "salary_unit": p.salary_unit,
        "raw": p.raw,
        "content_hash": p.content_hash,
        "first_seen_at": now,
        "last_seen_at": now,
    }


def ingest(
    db: Session, source: Source, postings: list[NormalizedPosting] | None = None
) -> RunResult:
    """Run one source end to end and commit. `postings` lets tests (and a
    future Lambda) hand in already-fetched rows."""
    result = RunResult(source=source.name)
    run = IngestRun(source=source.name)
    db.add(run)
    db.commit()

    try:
        if postings is None:
            postings = list(source.fetch())
        # Upstream occasionally repeats an id; the last occurrence wins, and
        # the bulk INSERT can't tolerate the same key twice in one statement.
        postings = list({p.source_id: p for p in postings}.values())
        result.fetched = len(postings)

        now = datetime.now(UTC)
        existing: dict[str, str | None] = dict(
            db.execute(
                select(Posting.source_id, Posting.content_hash).where(Posting.source == source.name)
            ).all()
        )
        active_before = db.scalar(
            select(func.count()).where(Posting.source == source.name, Posting.active.is_(True))
        )

        company_ids = _upsert_companies(db, postings)

        to_write: list[dict] = []
        unchanged_ids: list[str] = []
        for p in postings:
            stored = existing.get(p.source_id, _MISSING)
            if stored is _MISSING:
                result.inserted += 1
                to_write.append(_row(p, company_ids, now))
            elif stored != p.content_hash:
                result.updated += 1
                to_write.append(_row(p, company_ids, now))
            else:
                unchanged_ids.append(p.source_id)
        result.unchanged = len(unchanged_ids)

        for i in range(0, len(to_write), _BATCH):
            stmt = pg_insert(Posting).values(to_write[i : i + _BATCH])
            excluded = stmt.excluded
            stmt = stmt.on_conflict_do_update(
                constraint="uq_postings_source_source_id",
                set_={
                    c: getattr(excluded, c)
                    for c in _row(postings[0], company_ids, now)
                    if c not in ("source", "source_id", "first_seen_at")
                },
            )
            db.execute(stmt)

        for i in range(0, len(unchanged_ids), 5000):
            db.execute(
                update(Posting)
                .where(
                    Posting.source == source.name,
                    Posting.source_id.in_(unchanged_ids[i : i + 5000]),
                )
                .values(last_seen_at=now)
            )

        # Deactivate what fell out of the feed. If the fetch came back much
        # smaller than what we believe is live, assume upstream is broken —
        # not that thousands of roles closed overnight — and leave them alone.
        fetched_ids = {p.source_id for p in postings}
        guard = config.DEACTIVATE_GUARD_RATIO
        if active_before and guard and len(postings) < guard * active_before:
            result.error = (
                f"fetched {len(postings)} rows against {active_before} active; "
                "skipped deactivation (DEACTIVATE_GUARD_RATIO)"
            )
            log.warning(result.error, extra={"source": source.name})
        else:
            stale = [
                sid
                for sid in db.scalars(
                    select(Posting.source_id).where(
                        Posting.source == source.name, Posting.active.is_(True)
                    )
                )
                if sid not in fetched_ids
            ]
            for i in range(0, len(stale), 5000):
                res = db.execute(
                    update(Posting)
                    .where(
                        Posting.source == source.name, Posting.source_id.in_(stale[i : i + 5000])
                    )
                    # content_hash NULL so a row that comes back unchanged is
                    # still rewritten (and reactivated) rather than skipped.
                    .values(active=False, content_hash=None, date_updated=now)
                )
                result.deactivated += res.rowcount
    except Exception as exc:  # noqa: BLE001 — recorded in the ledger, re-raised below
        db.rollback()
        result.error = f"{type(exc).__name__}: {exc}"[:2000]
        log.error("ingest failed", extra={"source": source.name, "error": result.error})

    run.finished_at = datetime.now(UTC)
    run.fetched = result.fetched
    run.upserted = result.upserted
    run.deactivated = result.deactivated
    run.error = result.error
    db.add(run)
    db.commit()
    log.info("ingest finished", extra=asdict(result) | {"upserted": result.upserted})
    return result


_MISSING = object()


def run_all(db: Session, only: str = "all") -> list[RunResult]:
    names = list(SOURCES) if only == "all" else [only]
    return [ingest(db, SOURCES[name]()) for name in names]


def main(argv: list[str] | None = None) -> int:
    from app.database import SessionLocal
    from app.logging_config import setup as setup_logging

    setup_logging()
    parser = argparse.ArgumentParser(description="Backfill postings from every source.")
    parser.add_argument("--source", default="all", choices=["all", *SOURCES])
    args = parser.parse_args(argv)
    with SessionLocal() as db:
        results = run_all(db, args.source)
    for r in results:
        print(json.dumps(asdict(r) | {"upserted": r.upserted}))
    return 1 if any(r.error and not r.fetched for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
