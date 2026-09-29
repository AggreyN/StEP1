"""Terms: "Summer 2027". A season and a year, and nothing else.

The source lists, the profile's target terms and the feed's term filter all
use this one spelling, so they can be compared as strings.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app import limits

# In calendar order. "Winter 2026" is the December 2026 start, which is how
# the source lists label it, so it follows Fall of the same year.
SEASONS = ("Spring", "Summer", "Fall", "Winter")
_INDEX = {name.lower(): n for n, name in enumerate(SEASONS)} | {"autumn": 2}


def term_ordinal(term: str) -> int | None:
    """ "Summer 2027" -> a number where adjacent terms differ by 1."""
    parts = (term or "").strip().lower().split()
    if len(parts) != 2 or parts[0] not in _INDEX or not parts[1].isdigit():
        return None
    return int(parts[1]) * 4 + _INDEX[parts[0]]


def canonical_term(text: str, *, today: datetime | None = None) -> str | None:
    """The one accepted spelling of a term a student may target, or None.

    Case and spacing are forgiven ("summer  2027"); anything that is not one
    of the four seasons and a plausible year is not a term.
    """
    parts = (text or "").split()
    if len(parts) != 2 or not (parts[1].isdigit() and len(parts[1]) == 4):
        return None
    season = parts[0].lower()
    if season not in _INDEX or season == "autumn":
        return None
    this_year = (today or datetime.now(UTC)).year
    year = int(parts[1])
    if not this_year - limits.TERM_YEARS_BEHIND <= year <= this_year + limits.TERM_YEARS_AHEAD:
        return None
    return f"{SEASONS[_INDEX[season]]} {year}"
