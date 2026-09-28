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


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
