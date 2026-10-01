"""One job, shown once, however many lists carry it.

The same internship is often in the Simplify list, a SpeedyApply table and a
jobright.ai table at once. Each copy is kept (each list may close it at a
different time, and each is credited), but only one is shown: in the feed,
in search, in saved postings and in every count.

Two postings are the same job when they share a dedupe_key (the apply URL
without tracking parameters), or come from different lists and share a
title_key (company, title and city). Both
are computed at ingest (sources/base.py). Groups are joined transitively: A
and B share a URL, B and C a title, so A, B and C are one job.

The copy shown is the one from the most structured list (backfill.SOURCES is
in order of preference), then the oldest. Every posting in a group gets
canonical_id = that posting's id; a posting alone is its own.

Only open postings take part: a closed copy must not be chosen over an open
one, and a closed posting is not shown anyway.
"""

from __future__ import annotations

import logging

from sqlalchemy import bindparam, or_, select, update
from sqlalchemy.orm import Session

from app.models import Posting

log = logging.getLogger(__name__)

# Postings that are shown: the copy chosen for their group, or not yet grouped.
SHOWN = or_(Posting.canonical_id.is_(None), Posting.canonical_id == Posting.id)


def _rank() -> dict[str, int]:
    from app.sources.backfill import SOURCES

    return {name: n for n, name in enumerate(SOURCES)}


def recompute(db: Session) -> dict[str, int]:
    """Regroup every open posting and write canonical_id where it changed.
    Commits. Returns {"open", "groups", "duplicates", "changed"}."""
    rank = _rank()
    rows = db.execute(
        select(
            Posting.id,
            Posting.source,
            Posting.kind,
            Posting.dedupe_key,
            Posting.title_key,
            Posting.canonical_id,
        ).where(Posting.active.is_(True), Posting.is_visible.is_(True))
    ).all()

    parent = {r.id: r.id for r in rows}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    # A shared apply URL is the same job wherever it appears. A shared
    # company, title and city is only taken to be the same job across two
    # lists: within one list, two rows like that are two openings (different
    # terms, different teams) that the list itself keeps apart.
    # Within one kind: a role in both an internship list and a new-grad list
    # stays in both, so that neither kind of student loses it.
    by_url: dict[tuple, int] = {}
    by_title: dict[tuple, dict[str, int]] = {}
    for r in rows:
        if r.dedupe_key:
            key = (r.kind, r.dedupe_key)
            if key in by_url:
                union(by_url[key], r.id)
            else:
                by_url[key] = r.id
        if r.title_key:
            seen = by_title.setdefault((r.kind, r.title_key), {})
            for source, other in seen.items():
                if source != r.source:
                    union(other, r.id)
            seen.setdefault(r.source, r.id)

    groups: dict[int, list] = {}
    for r in rows:
        groups.setdefault(find(r.id), []).append(r)

    changes = []
    for members in groups.values():
        best = min(members, key=lambda r: (rank.get(r.source, len(rank)), r.id))
        for r in members:
            if r.canonical_id != best.id:
                changes.append({"pid": r.id, "cid": best.id})

    stmt = (
        update(Posting)
        .where(Posting.id == bindparam("pid"))
        .values(canonical_id=bindparam("cid"))
        .execution_options(synchronize_session=False)
    )
    for i in range(0, len(changes), 2000):
        db.connection().execute(stmt, changes[i : i + 2000])
    db.commit()
    summary = {
        "open": len(rows),
        "groups": len(groups),
        "duplicates": len(rows) - len(groups),
        "changed": len(changes),
    }
    log.info("dedupe finished", extra=summary)
    return summary
