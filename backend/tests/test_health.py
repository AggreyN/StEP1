def test_health_reports_db_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "ok"}
    assert r.headers.get("x-request-id")


def test_cors_exposes_retry_after(client):
    r = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "retry-after" in r.headers["access-control-expose-headers"].lower()
