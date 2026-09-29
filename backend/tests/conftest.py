"""Shared fixtures.

The suite runs against a real Postgres (postings use ARRAY, JSONB, tsvector
and a generated column — SQLite can't stand in).

    TEST_DATABASE_URL unset -> postgresql+psycopg://localhost:5432/step1_test
    TEST_DATABASE_URL set   -> that database (CI sets it to the service container)
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

# ---------------------------------------------------------------------------
# Environment is pinned HERE, at conftest import time — not in a fixture.
# app/config.py calls load_dotenv() at import and test modules import app.* at
# collection, before any fixture runs. load_dotenv() never overrides variables
# already in os.environ, so setting them now keeps a developer's .env (and its
# real database) out of the suite.
# ---------------------------------------------------------------------------
_TMP = Path(tempfile.mkdtemp(prefix="step1-tests-"))
DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://localhost:5432/step1_test")
os.environ["DATABASE_URL"] = DATABASE_URL
os.environ["APP_ENV"] = "dev"
os.environ["AUTH_MODE"] = "local"
os.environ["STORAGE_BACKEND"] = "local"
os.environ["UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ["PUBLIC_API_BASE"] = "http://testserver"
os.environ["JWT_SECRET"] = "test-only-secret-not-a-real-key"
# The cheapest bcrypt allows. The suite creates hundreds of accounts and none
# of them protects anything.
os.environ["BCRYPT_ROUNDS"] = "4"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:3000"
# The suite must never reach the network. The scheduler is off here; the
# tests that exercise it call it directly with a fake source.
os.environ["AUTO_INGEST"] = "false"
os.environ["INGEST_INTERVAL_HOURS"] = "24"
os.environ["INGEST_CHECK_MINUTES"] = "30"


_TABLES = (
    "application_events, applications, saved_postings, match_scores, profile_interests, "
    "profiles, outreach_messages, contacts, integrations, users, postings, companies, ingest_runs"
)


@pytest.fixture(scope="session", autouse=True)
def _migrated():
    """Build the schema with `alembic downgrade base && upgrade head` — the
    migration is what runs in production, so it's what the suite exercises."""
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def _clean_tables(_migrated):
    yield
    from sqlalchemy import text

    from app.database import engine

    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE"))


@pytest.fixture()
def db():
    from app.database import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


PROFILE = {
    "school": "University of Maryland, College Park",
    "major": "Information Science",
    "minor": "Data Science",
    "degree_level": "Bachelor's",
    "grad_year": 2028,
    "gpa": 3.7,
    "target_terms": ["Summer 2027"],
    "preferred_locations": ["Washington, DC", "New York, NY"],
    "remote_ok": True,
    "interests": [
        {"role": "software", "rank": 1},
        {"role": "ai_ml_data", "rank": 2},
        {"role": "data_analytics", "rank": 3},
    ],
}


@pytest.fixture()
def profile_body() -> dict:
    import copy

    return copy.deepcopy(PROFILE)


def register(client, email="ada@umd.edu", password="correct-horse", name="Ada") -> dict:
    """Register a user and return their Authorization header."""
    r = client.post(
        "/auth/register", json={"email": email, "password": password, "display_name": name}
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def auth(client) -> dict:
    return register(client)


RESUME_TEXT = """Ada Lovelace
ada@umd.edu | College Park, MD | github.com/ada

EDUCATION
University of Maryland, College Park - B.S. Information Science, minor in Data Science. GPA 3.7

SKILLS
Languages: Python, Java, SQL, JavaScript, C++
Frameworks: React, FastAPI, PyTorch, scikit-learn
Tools: Docker, AWS, Git, PostgreSQL, Tableau

EXPERIENCE
Software Engineering Intern, Example Corp, Summer 2026
Built a REST API in Python and deployed it on AWS with Docker and CI/CD.
Wrote machine learning models for ranking; improved precision by 12 percent.
"""


def make_pdf(text: str = RESUME_TEXT) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(50, 50, 560, 780), text, fontsize=10)
    data = doc.tobytes()
    doc.close()
    return data


def make_row(
    source_id: str,
    title: str = "Software Engineer Intern",
    company: str = "Acme",
    *,
    locations=("Washington, DC",),
    terms=("Summer 2027",),
    degrees=("Bachelor's",),
    days_ago: float | None = 3,
    category: str = "Software",
    active: bool = True,
    is_visible: bool = True,
    posted: int | None = None,
) -> dict:
    """One posting in the Simplify list's own JSON shape. `days_ago=None`
    makes an undated posting; `posted` pins the exact epoch second, for tests
    that need several postings with an identical date."""
    import time

    if posted is None and days_ago is not None:
        posted = int(time.time() - days_ago * 86_400)
    return {
        "source": "Simplify",
        "id": source_id,
        "title": title,
        "company_name": company,
        "company_url": f"https://simplify.jobs/c/{company.replace(' ', '-')}",
        "category": category,
        "locations": list(locations),
        "terms": list(terms),
        "degrees": list(degrees),
        "sponsorship": "Other",
        "url": f"https://jobs.example.com/{source_id}",
        "date_posted": posted,
        "date_updated": posted,
        "active": active,
        "is_visible": is_visible,
    }


def seed(rows: list[dict]):
    """Ingest rows through the real backfill path, as source 'simplify'."""
    from app.database import SessionLocal
    from app.sources import simplify
    from app.sources.backfill import ingest
    from app.sources.base import Source

    class Fixed(Source):
        name = "simplify"

        def fetch(self):
            return [simplify.normalize_row(r) for r in rows]

    with SessionLocal() as session:
        result = ingest(session, Fixed())
    assert result.error is None, result.error
    return result


def onboard(client, headers: dict, **overrides) -> dict:
    """PUT /profile with the standard body; returns the body that was sent."""
    import copy

    body = copy.deepcopy(PROFILE) | overrides
    r = client.put("/profile", json=body, headers=headers)
    assert r.status_code == 202, r.text
    return body


INGEST_ROWS = [
    make_row("a", "Software Engineer Intern", "Acme"),
    make_row("b", "Data Analyst Intern", "Globex", category="AI/ML/Data"),
    make_row("c", "Hardware Engineering Intern", "Initech", category="Hardware"),
]


def fake_source(name: str, rows=None, fail: bool = False):
    """A source class the scheduler can instantiate in place of a real one.
    It never touches the network, and counts how often it was asked to fetch."""
    from dataclasses import replace

    from app.sources import simplify
    from app.sources.base import Source

    rows = INGEST_ROWS if rows is None else rows

    class Fake(Source):
        fetches = 0

        def fetch(self):
            type(self).fetches += 1
            if fail:
                raise ConnectionError("github is down")
            return [replace(simplify.normalize_row(r), source=name) for r in rows]

    Fake.name = name
    return Fake


def age_runs(db, hours: float) -> None:
    """Pretend every recorded ingest run happened `hours` ago."""
    from sqlalchemy import text

    db.execute(
        text(
            "UPDATE ingest_runs SET started_at = started_at - make_interval(secs => :s), "
            "finished_at = finished_at - make_interval(secs => :s)"
        ),
        {"s": hours * 3600},
    )
    db.commit()


def api_routes(app) -> dict[tuple[str, str], object]:
    """Every API route in the app, as {(METHOD, path template): route}.

    Recent FastAPI keeps included routers nested rather than copying their
    routes onto the app, so `for r in app.routes` finds none of them. A test
    that walked only the top level would check nothing and pass. This walks
    all the way down, and works on the older flat layout too.
    """
    from fastapi.routing import APIRoute

    found: dict[tuple[str, str], object] = {}

    def walk(routes, prefix: str) -> None:
        for route in routes:
            if isinstance(route, APIRoute):
                for method in route.methods - {"HEAD", "OPTIONS"}:
                    found[(method, prefix + route.path)] = route
            elif hasattr(route, "original_router"):
                inner = getattr(route.include_context, "prefix", "") or ""
                walk(route.original_router.routes, prefix + inner)
            elif hasattr(route, "routes"):
                walk(route.routes, prefix + getattr(route, "path", ""))

    walk(app.routes, "")
    return found


def upload_resume(client, headers: dict, data: bytes | None = None, filename: str = "resume.pdf"):
    """The whole resume flow as a browser does it: presign, PUT, commit.
    Returns the commit response."""
    from app import config

    data = make_pdf() if data is None else data
    presigned = client.post(
        "/profile/resume/presign",
        json={"filename": filename, "content_type": "application/pdf"},
        headers=headers,
    )
    assert presigned.status_code == 200, presigned.text
    target = presigned.json()
    path = target["upload_url"].removeprefix(config.PUBLIC_API_BASE)
    put = client.put(path, content=data, headers={**headers, **target["headers"]})
    assert put.status_code < 300, put.text
    return client.post(
        "/profile/resume/commit",
        json={"key": target["key"], "filename": filename},
        headers=headers,
    )
