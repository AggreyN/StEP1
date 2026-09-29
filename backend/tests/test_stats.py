"""GET /stats: public, cacheable, and about nobody."""

from datetime import datetime

import pytest

from app import config
from app.ratelimit import limiter
from app.services import ingest_scheduler
from app.sources.roles import ROLE_LABELS
from tests.conftest import age_runs, fake_source, make_row, onboard, register, seed

BOARD = [
    make_row("a1", company="Acme"),
    make_row("a2", company="Acme"),
    make_row("a3", company="ACME Corp"),  # the same company, spelled differently
    make_row("g1", company="Globex"),
    make_row("closed", company="Closedco", active=False),
    make_row("hidden", company="Hiddenco", is_visible=False),
    make_row("old", company="Oldco", days_ago=400),  # open, though too old for a feed
]


def test_shape_and_counts(client):
    seed(BOARD)
    r = client.get("/stats")
    assert r.status_code == 200
    body = r.json()
    assert list(body) == ["active_postings", "companies", "role_families", "updated_at"]
    assert body["active_postings"] == 5  # a1 a2 a3 g1 old
    assert body["companies"] == 3  # Acme, Globex, Oldco: not Closedco, not Hiddenco
    assert body["role_families"] == len(ROLE_LABELS) == 15
    assert "other" in ROLE_LABELS
    assert body["updated_at"].endswith("Z")
    datetime.fromisoformat(body["updated_at"].replace("Z", "+00:00"))


def test_an_empty_board(client):
    assert client.get("/stats").json() == {
        "active_postings": 0,
        "companies": 0,
        "role_families": 15,
        "updated_at": None,
    }


def test_needs_no_token_and_ignores_one(client):
    seed(BOARD)
    headers = register(client)
    onboard(client, headers)
    client.post("/saved/simplify:a1", headers=headers)
    anonymous = client.get("/stats")
    signed_in = client.get("/stats", headers=headers)
    garbage = client.get("/stats", headers={"Authorization": "Bearer not-a-token"})
    assert anonymous.status_code == signed_in.status_code == garbage.status_code == 200
    assert anonymous.json() == signed_in.json() == garbage.json()
    for forbidden in ("ada@umd.edu", "Ada", "user", "email", "saved", "score"):
        assert forbidden not in anonymous.text


def test_is_cacheable_and_says_so(client):
    r = client.get("/stats")
    assert r.headers.get_list("cache-control") == ["public, max-age=300"]
    # Everything else is one person's data, and says the opposite.
    assert client.get("/health").headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"


def test_is_readable_from_the_frontend(client):
    r = client.get("/stats", headers={"Origin": "http://localhost:3000"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
    r = client.get("/stats", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_updated_at_is_the_freshness_the_status_route_reports(client, db, auth):
    registry = {"simplify": fake_source("simplify"), "vanshb03": fake_source("vanshb03")}
    ingest_scheduler.run_due(registry)
    age_runs(db, 3)
    ingest_scheduler.run_due({"vanshb03": fake_source("vanshb03", fail=True)})

    status = client.get("/ingest/status", headers=auth).json()
    stats = client.get("/stats").json()
    assert stats["updated_at"] == status["last_success_at"] is not None
    assert stats["active_postings"] == status["active_postings"] == 6


def test_takes_no_input(client):
    seed(BOARD)
    plain = client.get("/stats").json()
    for query in ("?user_id=1", "?active=false", "?q='; DROP TABLE postings; --", "?page=2"):
        assert client.get(f"/stats{query}").json() == plain
    assert client.post("/stats", json={}).status_code == 405
    assert client.delete("/stats").status_code == 405


@pytest.fixture()
def limits_on(monkeypatch):
    limiter.reset()
    monkeypatch.setattr(limiter, "enabled", True)
    yield
    limiter.reset()


def test_is_rate_limited(client, limits_on):
    assert config.STATS_RATE_LIMIT == "60/minute"
    codes = [client.get("/stats").status_code for _ in range(61)]
    assert codes == [200] * 60 + [429]
    r = client.get("/stats")
    assert r.json() == {"detail": "Too many requests. Try again in a minute."}
    assert 1 <= int(r.headers["retry-after"]) <= 60
    # A refusal must not be cached as if it were the answer.
    assert r.headers["cache-control"] == "no-store"
    # And it has its own counter: signing in is unaffected.
    assert (
        client.post(
            "/auth/login", json={"email": "a@example.com", "password": "whatever-it-is"}
        ).status_code
        == 401
    )
