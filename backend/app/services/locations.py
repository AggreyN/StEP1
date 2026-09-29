"""Location parsing for the matcher's location component (§4).

The source lists write places freehand — "NYC", "SF", "San Jose, CA",
"Toronto, ON, Canada", "Remote in USA" — and a student types "Washington, DC".
This module turns both into (city, region) and answers two questions:
same metro? same state?

"Metro" is a small hand-kept table of the metros that dominate intern
postings. A student who asks for Washington, DC means Arlington and Bethesda
too; without the table those score as merely "same state" or, across the
river, nothing. Cities not in the table are their own metro.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota",
    "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}  # fmt: skip
_STATE_BY_NAME = {name.lower(): abbr for abbr, name in US_STATES.items()}

# Shorthand the lists use in place of "City, ST".
_ALIASES = {
    "nyc": ("new york", "NY"),
    "new york city": ("new york", "NY"),
    "new york": ("new york", "NY"),
    "manhattan": ("new york", "NY"),
    "sf": ("san francisco", "CA"),
    "san francisco": ("san francisco", "CA"),
    "bay area": ("san francisco", "CA"),
    "sf bay area": ("san francisco", "CA"),
    "san francisco bay area": ("san francisco", "CA"),
    "silicon valley": ("san jose", "CA"),
    "la": ("los angeles", "CA"),
    "los angeles": ("los angeles", "CA"),
    "dc": ("washington", "DC"),
    "washington dc": ("washington", "DC"),
    "washington d.c.": ("washington", "DC"),
    "washington d.c": ("washington", "DC"),
    # Bare "Washington" is read as the city, not the state: at a Maryland
    # school that is what it means nine times in ten.
    "washington": ("washington", "DC"),
    "seattle": ("seattle", "WA"),
    "boston": ("boston", "MA"),
    "chicago": ("chicago", "IL"),
    "austin": ("austin", "TX"),
    "atlanta": ("atlanta", "GA"),
}

_METROS: dict[str, dict[str, tuple[str, ...]]] = {
    "Washington, DC area": {
        "DC": ("washington",),
        "VA": (
            "arlington", "alexandria", "mclean", "tysons", "tysons corner", "reston", "herndon",
            "vienna", "fairfax", "falls church", "chantilly", "sterling", "ashburn",
            "springfield", "dulles",
        ),
        "MD": (
            "bethesda", "rockville", "silver spring", "college park", "greenbelt", "laurel",
            "gaithersburg", "germantown", "hyattsville", "fort meade", "annapolis junction",
            "bowie", "landover", "riverdale", "chevy chase",
        ),
    },
    "New York City area": {
        "NY": ("new york", "brooklyn", "queens", "bronx", "long island city"),
        "NJ": ("jersey city", "hoboken", "newark"),
    },
    "San Francisco Bay Area": {
        "CA": (
            "san francisco", "south san francisco", "oakland", "berkeley", "emeryville",
            "san jose", "palo alto", "mountain view", "sunnyvale", "santa clara", "menlo park",
            "cupertino", "redwood city", "san mateo", "fremont", "milpitas", "san bruno",
            "foster city", "los gatos", "burlingame", "pleasanton", "san carlos", "los altos",
        ),
    },
    "Seattle area": {"WA": ("seattle", "bellevue", "redmond", "kirkland")},
    "Boston area": {
        "MA": ("boston", "cambridge", "somerville", "waltham", "burlington", "lexington"),
    },
    "Los Angeles area": {
        "CA": (
            "los angeles", "santa monica", "culver city", "el segundo", "burbank", "pasadena",
            "glendale", "playa vista",
        ),
    },
}  # fmt: skip
_METRO_BY_PLACE = {
    (city, state): metro
    for metro, states in _METROS.items()
    for state, cities in states.items()
    for city in cities
}

_REMOTE = re.compile(r"\bremote\b", re.I)
_COUNTRY_ONLY = {"united states", "usa", "us", "u.s.", "u.s.a.", "canada", "uk", "united kingdom"}


@dataclass(frozen=True)
class Place:
    city: str | None  # lowercased
    region: str | None  # US state abbreviation, or whatever follows the city elsewhere
    remote: bool = False

    @property
    def metro(self) -> str | None:
        if self.city is None:
            return None
        return _METRO_BY_PLACE.get((self.city, self.region)) or f"{self.city}|{self.region}"


def _region(token: str) -> str:
    token = token.strip()
    upper = token.upper().replace(".", "")
    if upper in US_STATES:
        return upper
    return _STATE_BY_NAME.get(token.lower(), upper)


@lru_cache(maxsize=20_000)
def parse(text: str) -> Place:
    """Location strings repeat heavily across postings, hence the cache."""
    raw = " ".join((text or "").split())
    if not raw:
        return Place(None, None)
    if _REMOTE.search(raw):
        return Place(None, None, remote=True)
    lowered = raw.lower()
    if lowered in _COUNTRY_ONLY:
        return Place(None, None)
    if lowered in _ALIASES:
        city, region = _ALIASES[lowered]
        return Place(city, region)
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) == 1:
        # A bare state ("Maryland", "MD") is a region with no city.
        region = _region(parts[0])
        if region in US_STATES:
            return Place(None, region)
        return Place(lowered, None)
    city = parts[0].lower()
    region = _region(parts[1])
    # "New York City, NY" and "Washington D.C., DC" are the alias cities.
    if city in _ALIASES and _ALIASES[city][1] == region:
        city = _ALIASES[city][0]
    return Place(city, region)


def state_name(region: str | None) -> str | None:
    return US_STATES.get(region or "", region)


def match(posting_locations: list[str], preferred: list[Place]) -> tuple[str, str] | None:
    """Best relationship between a posting and the student's preferred places.

    Returns ("metro" | "state", the posting's location string), or None.
    "metro" also covers a student who asked for a whole state and a posting
    inside it: that is exactly what they asked for, not a near miss.
    """
    same_state: str | None = None
    for text in posting_locations:
        place = parse(text)
        if place.remote or (place.city is None and place.region is None):
            continue
        for want in preferred:
            if want.city is None:
                if want.region and want.region == place.region:
                    return ("metro", text)
                continue
            if place.city is not None and place.metro == want.metro:
                return ("metro", text)
            # "London" against "London, UK": one side gave no region at all.
            if place.city == want.city and None in (place.region, want.region):
                return ("metro", text)
            if same_state is None and want.region and want.region == place.region:
                same_state = text
    return ("state", same_state) if same_state else None
