"""Shared fetch for the GitHub-hosted lists (SimplifyJobs, vanshb03).

Both publish one flat JSON array at `.github/scripts/listings.json` on the
`dev` branch. The repo slug is config because the name rolls forward every
recruiting cycle.
"""

from __future__ import annotations

import logging

import requests

from app import config

log = logging.getLogger(__name__)


def listings_url(repo: str) -> str:
    return (
        f"https://raw.githubusercontent.com/{repo}/{config.SOURCE_BRANCH}"
        "/.github/scripts/listings.json"
    )


def fetch_listings(repo: str) -> list[dict]:
    url = listings_url(repo)
    log.info("fetching listings", extra={"repo": repo})
    resp = requests.get(url, timeout=config.SOURCE_FETCH_TIMEOUT_S)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError(f"{url} did not return a JSON array")
    return [row for row in data if isinstance(row, dict)]
