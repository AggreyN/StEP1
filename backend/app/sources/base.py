"""The one shape every source normalizes into (§2.5), and the Source interface.

Sources only fetch and normalize. Classification (roles.py) and persistence
(backfill.py) happen once, here and downstream, so adding Adzuna or USAJobs
later is one new normalizer and nothing else.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

_REMOTE = re.compile(r"\bremote\b", re.I)
_WS = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")
# Suffixes that make "Palantir Technologies Inc." and "Palantir Technologies"
# two companies. Stripped only for the dedupe key, never from the display name.
_COMPANY_SUFFIX = re.compile(
    r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|company|plc|gmbh|sa|ag)\b\.?$"
)


class Cancelled(Exception):
    """The process has been told to stop, and the ingest is stopping with it."""


# Set when the process is asked to stop. An ingest looks at it between the
# steps where stopping is clean: between chunks of a download, before it
# writes, between batches. It is a module-level flag because the code that
# has to look (a source's fetch, several calls deep) and the code that sets it
# (a signal handler, the server's shutdown) share nothing else.
cancel = threading.Event()


def check_cancelled() -> None:
    if cancel.is_set():
        raise Cancelled("the process is stopping")


@dataclass
class NormalizedPosting:
    source: str  # "simplify" | "vanshb03" | "adzuna" | "usajobs"
    source_id: str  # stable id from that source
    company_name: str
    company_url: str | None
    title: str
    category: str | None  # the source's own category, raw; None for sources without one
    roles: list[str]  # roles.classify(title, category)
    locations: list[str]
    is_remote: bool
    terms: list[str]  # "Summer 2027"; [] when the posting declares none
    degrees: list[str]
    url: str
    date_posted: datetime | None
    date_updated: datetime | None
    active: bool
    is_visible: bool
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    salary_unit: str | None = None  # "hour" | "year"
    kind: str = "internship"  # "internship" | "new_grad"
    raw: dict = field(default_factory=dict)

    @property
    def dedupe_key(self) -> str:
        """The same job, as any list would link to it: the apply URL without
        tracking parameters; failing that, company, title and place."""
        return url_key(self.url) or self.title_key

    @property
    def title_key(self) -> str:
        place = self.locations[0] if self.locations else ""
        return "t:" + "|".join(
            _WS.sub(" ", _NON_ALNUM.sub(" ", part.lower())).strip()
            for part in (normalize_company(self.company_name), self.title, place.split(",")[0])
        )

    @property
    def content_hash(self) -> str:
        """SHA-256 of the fields that matter. Ingest skips the UPDATE when it
        matches, which turns a 16,000-row nightly pull into a few dozen writes.
        `raw` is deliberately excluded: upstream reorders keys and touches
        fields we don't use, and none of that should cost a write."""
        material = {
            "title": self.title,
            "company": self.company_name,
            "company_url": self.company_url,
            "category": self.category,
            "roles": self.roles,
            "locations": self.locations,
            "is_remote": self.is_remote,
            "terms": self.terms,
            "degrees": self.degrees,
            "url": self.url,
            "date_posted": self.date_posted.isoformat() if self.date_posted else None,
            "date_updated": self.date_updated.isoformat() if self.date_updated else None,
            "active": self.active,
            "is_visible": self.is_visible,
            "salary": [str(self.salary_min), str(self.salary_max), self.salary_unit],
            "kind": self.kind,
        }
        return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


class Source(ABC):
    name: str

    @abstractmethod
    def fetch(self) -> Iterable[NormalizedPosting]:
        """Pull the source and yield normalized rows. Raise on a failed fetch:
        backfill records the error and, crucially, does NOT deactivate anything
        on the strength of an empty result.

        A fetch that can take more than a moment calls check_cancelled() as it
        goes, so that a process told to stop is not kept waiting for it."""


# --------------------------------------------------------------------------- #
# Helpers shared by normalizers
# --------------------------------------------------------------------------- #


def epoch_to_dt(value) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def clean_list(values) -> list[str]:
    """Strings only, stripped, de-duplicated, order preserved."""
    out: list[str] = []
    for v in values or []:
        if isinstance(v, str):
            v = _WS.sub(" ", v).strip()
            if v and v not in out:
                out.append(v)
    return out


def is_remote(locations: list[str]) -> bool:
    return any(_REMOTE.search(loc) for loc in locations)


def normalize_company(name: str) -> str:
    """The dedupe key for `companies.normalized_name`."""
    key = _NON_ALNUM.sub(" ", name.lower().replace("&", " and "))
    key = _WS.sub(" ", key).strip()
    key = _COMPANY_SUFFIX.sub("", key).strip()
    return key or name.lower().strip()


# Query parameters that say where a click came from, not which job it is.
_TRACKING = {
    "ref", "refs", "src", "source", "s", "gh_src", "lever-source", "lever-origin",
    "trk", "campaign", "utm", "fbclid", "gclid", "mc_cid", "mc_eid", "iis", "iisn",
}  # fmt: skip


def url_key(url: str) -> str | None:
    """A URL reduced to what identifies the page: scheme dropped, host
    lowercased without www., fragment and tracking parameters gone, the rest
    sorted, no trailing slash. None for something that is not a web URL."""
    from urllib.parse import parse_qsl, urlencode, urlsplit

    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    host = parts.netloc.lower().removeprefix("www.")
    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING
    )
    path = parts.path.rstrip("/")
    return f"u:{host}{path}" + (f"?{urlencode(query)}" if query else "")


_TERM = re.compile(r"\b(summer|fall|autumn|spring|winter)\s*[,'-]?\s*(20\d\d)\b", re.I)


def terms_in(title: str) -> list[str]:
    """Terms a title names, "Summer 2027" style. For lists with no term column."""
    found: list[str] = []
    for season, year in _TERM.findall(title):
        season = "Fall" if season.lower() == "autumn" else season.capitalize()
        term = f"{season} {year}"
        if term not in found:
            found.append(term)
    return found
