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
os.environ["ALLOWED_ORIGINS"] = "http://localhost:3000"


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
