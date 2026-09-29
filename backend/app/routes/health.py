"""Liveness and database reachability: what the load balancer polls.

A health check is asked every few seconds, by a machine, for ever, and its
answer decides whether traffic is sent here and whether a deployment is kept.
So it is held to rules the other routes are not:

  * No token and no rate limit. The load balancer has neither an identity
    nor a single address, and a refused health check takes the service down.
  * One `SELECT 1` and nothing else. It never starts a refresh of the
    listings, touches a table, or does work that grows with the data.
  * It answers within HEALTH_DB_TIMEOUT_S whatever the database is doing. A
    database that has stopped answering must produce a prompt 503, not a
    request that hangs until the load balancer gives up on it.
"""

import asyncio
import logging

from fastapi import APIRouter, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import text

from app import config
from app.database import engine
from app.schemas import HealthOut

router = APIRouter(tags=["health"])
log = logging.getLogger(__name__)


def ping_database() -> None:
    """Raises if the database cannot be reached and queried."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


@router.get("/health", response_model=HealthOut, responses={503: {"model": HealthOut}})
async def health(response: Response):
    try:
        # In a thread, with a deadline on the wait. If the deadline passes
        # the thread is left to finish on its own, which it does within
        # DB_CONNECT_TIMEOUT; the answer does not wait for it.
        await asyncio.wait_for(run_in_threadpool(ping_database), timeout=config.HEALTH_DB_TIMEOUT_S)
    except Exception as exc:
        # The kind of failure, never its text: a connection error can carry
        # the host and user it was trying.
        log.error("health: database unreachable: %s", type(exc).__name__)
        # 503 so the load balancer stops routing here, with a body that
        # still says which half is broken.
        response.status_code = 503
        return HealthOut(status="degraded", db="error")
    return HealthOut(status="ok", db="ok")
