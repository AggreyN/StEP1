"""Shared fetch for the GitHub-hosted lists (SimplifyJobs, vanshb03).

Both publish one flat JSON array at `.github/scripts/listings.json` on the
`dev` branch. The repo slug is config because the name rolls forward every
recruiting cycle.
"""

from __future__ import annotations

import json
import logging
import time

import requests

from app import config
from app.sources.base import check_cancelled

log = logging.getLogger(__name__)

# Seconds to wait for the connection, and for each read from it. Short, and
# separate from the deadline for the whole download: a stalled connection is
# noticed in seconds, and a process told to stop is never waiting on a single
# read for longer than this.
_CONNECT_TIMEOUT_S = 10
_READ_TIMEOUT_S = 10
_CHUNK = 256 * 1024
# The Simplify list is about 13 MB. Something five times that is not the list.
_MAX_BYTES = 64 * 1024 * 1024


def listings_url(repo: str, branch: str | None = None) -> str:
    return raw_url(repo, ".github/scripts/listings.json", branch)


def raw_url(repo: str, path: str, branch: str | None = None) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{branch or config.SOURCE_BRANCH}/{path}"


def fetch_bytes(url: str) -> bytes:
    """Download one file.

    Read in pieces rather than all at once, for two reasons. Between pieces
    it can notice that the process has been asked to stop, and stop. And it
    can give up on a response that is too large or too slow while it is still
    arriving, rather than after holding all of it.
    """
    deadline = time.monotonic() + config.SOURCE_FETCH_TIMEOUT_S
    pieces: list[bytes] = []
    size = 0
    with requests.get(url, stream=True, timeout=(_CONNECT_TIMEOUT_S, _READ_TIMEOUT_S)) as resp:
        resp.raise_for_status()
        for piece in resp.iter_content(chunk_size=_CHUNK):
            check_cancelled()
            size += len(piece)
            if size > _MAX_BYTES:
                raise ValueError(f"{url} is larger than {_MAX_BYTES // (1024 * 1024)} MB")
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"{url} did not finish in {config.SOURCE_FETCH_TIMEOUT_S:g} seconds"
                )
            pieces.append(piece)
    check_cancelled()
    return b"".join(pieces)


def fetch_text(repo: str, path: str, branch: str | None = None) -> str:
    """A text file from a repo, e.g. a README holding the list as a table."""
    log.info("fetching listings", extra={"repo": repo, "path": path})
    return fetch_bytes(raw_url(repo, path, branch)).decode("utf-8", errors="replace")


def fetch_listings(repo: str, branch: str | None = None) -> list[dict]:
    """Download and parse one list's JSON (Simplify's format)."""
    url = listings_url(repo, branch)
    log.info("fetching listings", extra={"repo": repo})
    data = json.loads(fetch_bytes(url))
    if not isinstance(data, list):
        raise ValueError(f"{url} did not return a JSON array")
    return [row for row in data if isinstance(row, dict)]
