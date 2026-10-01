"""SimplifyJobs / Pitt CSC — the primary source (§2.1).

Traps handled here:
  * `terms` uses "N/A" as a value. That is "declares no term", so it is
    dropped and the posting is exempt from the term hard-filter rather than
    matched against a literal "N/A".
  * `category` has two spellings per value. It is kept raw (provenance); the
    classifier's fallback table knows both spellings.
  * The feed includes inactive and invisible rows. They are stored as-is and
    filtered on read, so "closed 3 days ago" is possible later.
"""

from __future__ import annotations

from collections.abc import Iterable

from app import config
from app.sources.base import (
    NormalizedPosting,
    Source,
    clean_list,
    epoch_to_dt,
    is_remote,
)
from app.sources.github_list import fetch_listings
from app.sources.roles import classify

_NO_TERM = {"n/a", "na", "tbd", "unknown", ""}


def normalize_terms(values) -> list[str]:
    return [t for t in clean_list(values) if t.lower() not in _NO_TERM]


def normalize_row(
    row: dict, source: str = "simplify", kind: str = "internship"
) -> NormalizedPosting | None:
    """One Simplify JSON object -> NormalizedPosting. None if it lacks the
    fields nothing downstream can work without. The New-Grad list uses the
    same format, so it comes through here too, as a different source."""
    source_id = str(row.get("id") or "").strip()
    title = " ".join(str(row.get("title") or "").split())
    url = str(row.get("url") or "").strip()
    if not (source_id and title and url):
        return None
    category = (row.get("category") or None) and str(row["category"]).strip()
    locations = clean_list(row.get("locations"))
    return NormalizedPosting(
        source=source,
        source_id=source_id,
        company_name=" ".join(str(row.get("company_name") or "Unknown").split()),
        company_url=(str(row.get("company_url") or "").strip() or None),
        title=title,
        category=category or None,
        roles=classify(title, category),
        locations=locations,
        is_remote=is_remote(locations),
        terms=normalize_terms(row.get("terms")),
        degrees=clean_list(row.get("degrees")),
        url=url,
        date_posted=epoch_to_dt(row.get("date_posted")),
        date_updated=epoch_to_dt(row.get("date_updated")),
        active=bool(row.get("active", True)),
        is_visible=bool(row.get("is_visible", True)),
        kind=kind,
        raw=row,
    )


class SimplifySource(Source):
    name = "simplify"

    def fetch(self) -> Iterable[NormalizedPosting]:
        for row in fetch_listings(config.SIMPLIFY_REPO):
            posting = normalize_row(row)
            if posting is not None:
                yield posting


class SimplifyNewGradSource(Source):
    """SimplifyJobs/New-Grad-Positions: the same JSON, for full-time roles."""

    name = "simplify_newgrad"

    def fetch(self) -> Iterable[NormalizedPosting]:
        for row in fetch_listings(config.SIMPLIFY_NEWGRAD_REPO, config.SIMPLIFY_NEWGRAD_BRANCH):
            posting = normalize_row(row, source=self.name, kind="new_grad")
            if posting is not None:
                yield posting
