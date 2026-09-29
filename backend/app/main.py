"""FastAPI app assembly for StEP1.

Run:  uvicorn app.main:app --reload --port 8000   ->  http://localhost:8000/docs
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, ProgrammingError

from app import config
from app.logging_config import AccessLogMiddleware
from app.logging_config import setup as setup_logging
from app.middleware import BodyLimitMiddleware

setup_logging()

from app.routes import (  # noqa: E402  (logging must be configured first)
    applications,
    auth,
    feed,
    health,
    ingest,
    postings,
    profile,
    saved,
)
from app.services import ingest_scheduler  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs the automatic refresh for as long as the API is up. Its first
    check is at startup, which is what lets a laptop that was off overnight
    catch up the moment the server starts."""
    task = ingest_scheduler.start()
    try:
        yield
    finally:
        await ingest_scheduler.stop(task)


app = FastAPI(
    title="StEP1 API",
    description="Internship discovery and application tracking.",
    version="0.1.0",
    lifespan=lifespan,
)

# Middleware wraps in reverse order of registration: the last one added is
# the first to see a request. So the body limit sits inside CORS (its refusals
# still carry CORS headers) and the access log sits outside everything.
app.add_middleware(BodyLimitMiddleware, exempt=("/profile/resume/local/",))
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
    # Retry-After is not CORS-safelisted. Without this the browser cannot read
    # the header on PUT /profile's 202 and the "building" poll loop silently
    # falls back to guessing (the Rackner bug, again).
    expose_headers=["Retry-After"],
)
# Outermost: every request gets an id + one JSON access line.
app.add_middleware(AccessLogMiddleware)

_log = logging.getLogger(__name__)


def _loc(loc: tuple) -> str:
    # ("body", "interests", 0, "rank") -> "interests[0].rank"
    out = ""
    for part in loc:
        if part in ("body", "query", "path", "header"):
            continue
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    """Flatten FastAPI's list-of-errors into one readable string, so every
    error body in the API is {"detail": str} and the frontend can show it."""
    parts = []
    for err in exc.errors():
        msg = str(err.get("msg", "invalid value"))
        # Pydantic prefixes custom ValueErrors with "Value error, ".
        msg = msg.removeprefix("Value error, ")
        if err.get("type") == "extra_forbidden":
            msg = "this field can't be set"
        where = _loc(tuple(err.get("loc", ())))
        parts.append(f"{where}: {msg}" if where else msg)
    return JSONResponse(status_code=422, content={"detail": "; ".join(parts) or "Invalid request."})


# A DB failure is a clean, NAMED 503 — never a bare 500. The two messages make
# the two deployment failure modes (unreachable vs migrations-never-ran)
# diagnosable from outside without CloudWatch access.
@app.exception_handler(OperationalError)
async def _db_unreachable(request: Request, exc: OperationalError):
    _log.error("database unreachable: %s", type(exc.orig).__name__)
    return JSONResponse(
        status_code=503,
        content={"detail": "The database is unreachable right now. Try again shortly."},
    )


@app.exception_handler(ProgrammingError)
async def _db_schema_broken(request: Request, exc: ProgrammingError):
    _log.error("database schema error: %s", exc.orig)
    return JSONResponse(
        status_code=503,
        content={"detail": "The database schema is not ready. Has `alembic upgrade head` run?"},
    )


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    """Even a bug answers in the contract's error shape. The traceback goes
    to the log (joined by X-Request-Id), never to the client."""
    _log.exception("unhandled error", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong on our side. Please try again."},
    )


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(feed.router)
app.include_router(postings.router)
app.include_router(saved.router)
app.include_router(applications.router)
app.include_router(ingest.router)
