"""vanshb03 / Summer2027-Internships — secondary source (§2.2). MIT licensed.

Same file shape as Simplify minus `category` and `degrees`, with a bare
`season` ("Summer", "Winter", "Spring/Summer") instead of `terms`. The year is
inferred from the posting date: a season is the next occurrence of its start
month at least a month after the posting. So "Summer" posted August 2026 is
"Summer 2027", "Fall" posted July 2026 is "Fall 2026", and "Winter" posted
August 2025 is "Winter 2025" (the December). That matches how the Simplify
list labels the same postings, which is what the term filter compares against.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

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

# Month each season's internship actually starts.
_SEASON_START_MONTH = {"winter": 12, "spring": 1, "summer": 5, "fall": 8, "autumn": 8}
_SEASON_LABEL = {"autumn": "Fall"}


def season_to_terms(season: str | None, date_posted: datetime | None) -> list[str]:
    if not season or date_posted is None:
        return []
    terms: list[str] = []
    for part in str(season).replace("&", "/").split("/"):
        key = part.strip().lower()
        start = _SEASON_START_MONTH.get(key)
        if start is None:
            continue
        year = date_posted.year
        # "At least a month after": a Summer role posted in late April is for
        # this May; one posted in May is next year's.
        if start <= date_posted.month:
            year += 1
        label = _SEASON_LABEL.get(key, key.capitalize())
        term = f"{label} {year}"
        if term not in terms:
            terms.append(term)
    return terms


def normalize_row(row: dict) -> NormalizedPosting | None:
    source_id = str(row.get("id") or "").strip()
    title = " ".join(str(row.get("title") or "").split())
    url = str(row.get("url") or "").strip()
    if not (source_id and title and url):
        return None
    locations = clean_list(row.get("locations"))
    date_posted = epoch_to_dt(row.get("date_posted"))
    return NormalizedPosting(
        source="vanshb03",
        source_id=source_id,
        company_name=" ".join(str(row.get("company_name") or "Unknown").split()),
        company_url=(str(row.get("company_url") or "").strip() or None),
        title=title,
        category=None,
        roles=classify(title, None),
        locations=locations,
        is_remote=is_remote(locations),
        terms=season_to_terms(row.get("season"), date_posted),
        degrees=clean_list(row.get("degrees")),
        url=url,
        date_posted=date_posted,
        date_updated=epoch_to_dt(row.get("date_updated")),
        active=bool(row.get("active", True)),
        is_visible=bool(row.get("is_visible", True)),
        raw=row,
    )


class Vanshb03Source(Source):
    name = "vanshb03"

    def fetch(self) -> Iterable[NormalizedPosting]:
        for row in fetch_listings(config.VANSHB03_REPO):
            posting = normalize_row(row)
            if posting is not None:
                yield posting
