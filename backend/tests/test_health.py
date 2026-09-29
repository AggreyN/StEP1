def test_health_reports_db_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "ok"}
    assert r.headers.get("x-request-id")


def test_cors_exposes_retry_after(client):
    r = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "retry-after" in r.headers["access-control-expose-headers"].lower()


def test_health_reports_a_database_it_cannot_reach(client):
    from app.deps import get_db
    from app.main import app

    class Unreachable:
        def execute(self, *args, **kwargs):
            raise ConnectionError("no route to host")

    app.dependency_overrides[get_db] = lambda: Unreachable()
    try:
        r = client.get("/health")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 503
    assert r.json() == {"status": "degraded", "db": "error"}
