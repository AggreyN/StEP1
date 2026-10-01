"""Rate limits, per client address.

Cognito throttles its own sign-in. In local mode nothing did: anyone could
try passwords against an account as fast as the server would answer. These
limits are what stands in the way, together with bcrypt making each attempt
cost a quarter of a second.

    sign in          10 a minute     guessing passwords
    register         5 an hour       filling the users table
    delete account   5 an hour       guessing the password there instead
    /stats           60 a minute     it is public

The counters are kept in this process's memory. That is right for one
instance, and it has two consequences worth knowing:

  * A restart forgets them. `--reload` in development resets every limit
    each time a file is saved.
  * With N instances behind a load balancer there are N sets of counters, so
    the effective limit is up to N times the configured one. Before running
    more than one instance, point the limiter at a shared store: install
    `limits[redis]` and pass storage_uri="redis://..." below. Nothing else
    changes.

The client's address comes from middleware.client_ip(), which believes
X-Forwarded-For only when TRUST_PROXY says there is a proxy to have set it.
Otherwise every request could name its own address and never be limited.
"""

from __future__ import annotations

import math
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from app import config
from app.middleware import client_ip


def _address(request: Request) -> str:
    return client_ip(request.scope)


limiter = Limiter(
    key_func=_address,
    enabled=config.RATE_LIMIT_ENABLED,
    storage_uri="memory://",
    # A window that slides. With fixed windows, ten attempts at 12:00:59 and
    # ten more at 12:01:00 are both allowed: twenty in two seconds.
    strategy="moving-window",
    # One counter per route, not per URL, so a path parameter cannot be
    # varied to get a fresh allowance.
    key_style="endpoint",
    # We write Retry-After ourselves, and only on a refusal.
    headers_enabled=False,
)


def login_limit() -> str:
    return config.LOGIN_RATE_LIMIT


def register_limit() -> str:
    return config.REGISTER_RATE_LIMIT


def delete_account_limit() -> str:
    return config.DELETE_ACCOUNT_RATE_LIMIT


def stats_limit() -> str:
    return config.STATS_RATE_LIMIT


def wait_in_words(seconds: int) -> str:
    """How long to wait, as a person would say it. The header has the number."""
    if seconds <= 90:
        return "in a minute"
    minutes = math.ceil(seconds / 60)
    if minutes <= 50:
        return f"in {minutes} minutes"
    if minutes <= 90:
        return "in about an hour"
    return f"in about {round(minutes / 60)} hours"


def _seconds_until_allowed(request: Request, exc: RateLimitExceeded) -> int:
    try:
        item, identifiers = request.state.view_rate_limit
        reset_at = limiter.limiter.get_window_stats(item, *identifiers).reset_time
        return max(1, math.ceil(reset_at - time.time()))
    except Exception:  # noqa: BLE001 — never fail to refuse because of a header
        return max(1, int(exc.limit.limit.get_expiry()))


async def too_many_requests(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """429, in the same shape as every other error, saying what happened and
    when to come back."""
    seconds = _seconds_until_allowed(request, exc)
    what = exc.detail if isinstance(exc.detail, str) and exc.detail else "Too many requests."
    return JSONResponse(
        status_code=429,
        content={"detail": f"{what} Try again {wait_in_words(seconds)}."},
        headers={"Retry-After": str(seconds)},
    )


def take(limit: str, *keys: tuple[str, ...]) -> int | None:
    """Count one use against `limit` for each key, if every key has room.
    Returns None when allowed (and counted), or the seconds until the
    tightest key has room again (and counts nothing). For limits that need
    to know who is asking, which the decorator above cannot."""
    if not limiter.enabled:
        return None
    from limits import parse

    item = parse(limit)
    strategy = limiter.limiter
    blocked = [key for key in keys if not strategy.test(item, *key)]
    if blocked:
        reset = max(strategy.get_window_stats(item, *key).reset_time for key in blocked)
        return max(1, math.ceil(reset - time.time()))
    for key in keys:
        strategy.hit(item, *key)
    return None
