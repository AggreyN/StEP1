"""GET /health, as a load balancer would use it."""

import time

import pytest
from sqlalchemy import event

from app import config
from app.database import engine
from app.ratelimit import limiter
from app.routes import health as health_route
from tests.conftest import api_routes


def test_health_reports_db_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "ok"}
    assert r.headers.get("x-request-id")


def test_cors_exposes_retry_after(client):
    r = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "retry-after" in r.headers["access-control-expose-headers"].lower()


def test_health_reports_a_database_it_cannot_reach(client, monkeypatch):
    def unreachable():
        raise ConnectionError("could not connect to server at db.internal as step1")

    monkeypatch.setattr(health_route, "ping_database", unreachable)
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json() == {"status": "degraded", "db": "error"}
    # The reason stays in the log, by kind only.
    assert "db.internal" not in r.text and "step1" not in r.text


def test_health_does_not_wait_for_a_database_that_has_stopped_answering(client, monkeypatch):
    """A security group that drops packets makes a connection attempt hang.
    The load balancer allows a health check a few seconds in all."""
    monkeypatch.setattr(config, "HEALTH_DB_TIMEOUT_S", 0.3)
    monkeypatch.setattr(health_route, "ping_database", lambda: time.sleep(3))
    started = time.perf_counter()
    r = client.get("/health")
    assert time.perf_counter() - started < 1.5
    assert r.status_code == 503
    assert r.json() == {"status": "degraded", "db": "error"}


def test_health_recovers_when_the_database_does(client, monkeypatch):
    real = health_route.ping_database
    monkeypatch.setattr(health_route, "ping_database", lambda: 1 / 0)
    assert client.get("/health").status_code == 503
    monkeypatch.setattr(health_route, "ping_database", real)
    assert client.get("/health").status_code == 200


def test_health_needs_no_token_and_ignores_a_bad_one(client):
    for headers in ({}, {"Authorization": "Bearer not-a-token"}, {"Authorization": "junk"}):
        assert client.get("/health", headers=headers).status_code == 200


def test_health_is_never_rate_limited(client, monkeypatch):
    """Polled every few seconds from a handful of addresses, for ever. One
    refusal is a failed health check."""
    limiter.reset()
    monkeypatch.setattr(limiter, "enabled", True)
    try:
        codes = {client.get("/health").status_code for _ in range(300)}
    finally:
        limiter.reset()
    assert codes == {200}
    route = api_routes(client.app)[("GET", "/health")]
    name = f"{route.endpoint.__module__}.{route.endpoint.__name__}"
    assert name not in limiter._route_limits and name not in limiter._dynamic_route_limits


def test_health_runs_one_trivial_query_and_nothing_else(client, monkeypatch):
    from app.services import ingest_scheduler
    from app.sources import backfill

    started = []
    monkeypatch.setattr(ingest_scheduler, "run_due", lambda *a, **k: started.append("run_due"))
    monkeypatch.setattr(backfill, "ingest", lambda *a, **k: started.append("ingest"))
    statements = []

    def record(conn, cursor, statement, *_):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        for _ in range(5):
            assert client.get("/health").status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert started == [], "a health check started a refresh of the listings"
    assert set(statements) <= {"SELECT 1", "select pg_catalog.version()"}, set(statements)
    assert statements.count("SELECT 1") == 5


def test_health_is_fast(client):
    client.get("/health")  # the first call opens the connection
    started = time.perf_counter()
    for _ in range(50):
        assert client.get("/health").status_code == 200
    each = (time.perf_counter() - started) / 50
    assert each < 0.05, f"{each * 1000:.1f} ms per check"


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
def test_health_is_read_only(client, method):
    assert client.request(method, "/health").status_code == 405
