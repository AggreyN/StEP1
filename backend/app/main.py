"""FastAPI app assembly for StEP1.

Run:  uvicorn app.main:app --reload --port 8000   ->  http://localhost:8000/docs
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import OperationalError, ProgrammingError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import config
from app.auth import NOT_FOUND
from app.logging_config import AccessLogMiddleware
from app.logging_config import setup as setup_logging
from app.middleware import (
    BodyLimitMiddleware,
    ErrorBoundaryMiddleware,
    SecurityHeadersMiddleware,
)

setup_logging()

from app.ratelimit import limiter, too_many_requests  # noqa: E402
from app.routes import (  # noqa: E402  (logging must be configured first)
    admin,
    applications,
    auth,
    feed,
    health,
    ingest,
    postings,
    profile,
    resumes,
    reviews,
    saved,
    stats,
)
from app.services import ingest_scheduler  # noqa: E402

_log = logging.getLogger(__name__)


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


def _loc(loc: tuple) -> str:
    # ("body", "interests", 0, "rank") -> "interests[0].rank"
    out = ""
    for n, part in enumerate(loc):
        # Only the first part says where; after that, "body" is a field name.
        if n == 0 and part in ("body", "query", "path", "header"):
            continue
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


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


async def _http_error(request: Request, exc: StarletteHTTPException):
    """Every HTTP error as {"detail": str}, as FastAPI does, with two changes.

    A path that is not there says "Not found." rather than Starlette's "Not
    Found", so that it reads exactly like an admin route does to someone who
    is not an admin (auth.current_admin). And an admin path asked for with
    the wrong method is a 404 too, not a 405: "method not allowed" would say
    the path exists.
    """
    if exc.status_code == 404 and exc.detail == "Not Found":
        return JSONResponse(status_code=404, content={"detail": NOT_FOUND})
    if exc.status_code == 405 and request.url.path.startswith("/admin"):
        return JSONResponse(status_code=404, content={"detail": NOT_FOUND})
    return await http_exception_handler(request, exc)


# A DB failure is a clean, NAMED 503 — never a bare 500. The two messages make
# the two deployment failure modes (unreachable vs migrations-never-ran)
# diagnosable from outside without CloudWatch access.
async def _db_unreachable(request: Request, exc: OperationalError):
    _log.error("database unreachable: %s", type(exc.orig).__name__)
    return JSONResponse(
        status_code=503,
        content={"detail": "The database is unreachable right now. Try again shortly."},
    )


async def _db_schema_broken(request: Request, exc: ProgrammingError):
    _log.error("database schema error: %s", type(exc.orig).__name__)
    return JSONResponse(
        status_code=503,
        content={"detail": "The database schema is not ready. Has `alembic upgrade head` run?"},
    )


def create_app(*, prod: bool = config.APP_ENV == "prod") -> FastAPI:
    """Build the application. `prod` is a parameter so that what production
    serves can be tested from anywhere, without pretending to be there."""
    app = FastAPI(
        title="StEP1 API",
        description="Internship discovery and application tracking.",
        version="0.1.0",
        lifespan=lifespan,
        # The interactive docs and the schema describe every route and every
        # field. Useful on a laptop; in production, a map for whoever is
        # looking for a way in. ReDoc is off everywhere: one is enough.
        docs_url=None if prod else "/docs",
        openapi_url=None if prod else "/openapi.json",
        redoc_url=None,
    )

    # Middleware wraps in reverse order of registration: the last one added
    # is the first to see a request and the last to see its response.
    #
    #   access log         outermost, so it times and records everything
    #   security headers   on every response, including refusals and errors
    #   CORS               so that refusals and errors below are readable
    #   body limit         before a byte of the body is read
    #   error boundary     innermost: a crash becomes a response down here,
    #                      and so passes back up through all of the above
    app.add_middleware(ErrorBoundaryMiddleware)
    app.add_middleware(BodyLimitMiddleware, exempt=("/profile/resume/local/",))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
        # Retry-After is not CORS-safelisted. Without this the browser cannot
        # read the header on PUT /profile's 202 and the "building" poll loop
        # silently falls back to guessing (the Rackner bug, again).
        # Content-Disposition carries a download's file name; without this a
        # page on another origin cannot read it.
        expose_headers=["Retry-After", "Content-Disposition"],
    )
    app.add_middleware(SecurityHeadersMiddleware, prod=prod)
    app.add_middleware(AccessLogMiddleware)

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, too_many_requests)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(OperationalError, _db_unreachable)
    app.add_exception_handler(ProgrammingError, _db_schema_broken)

    for module in (
        health,
        auth,
        profile,
        feed,
        postings,
        saved,
        applications,
        ingest,
        stats,
        reviews,
        admin,
        resumes,
    ):
        app.include_router(module.router)
    return app


app = create_app()
