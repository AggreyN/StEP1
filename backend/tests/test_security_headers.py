"""The same security headers on every response: successes, refusals, errors,
preflights, and routes that do not exist."""

import pytest
from fastapi.testclient import TestClient

from app import config, limits
from app.main import app, create_app
from app.middleware import client_ip, is_https
from tests.conftest import api_routes

STRICT = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "strict-origin-when-cross-origin",
    "x-frame-options": "DENY",
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
}
HSTS = "max-age=31536000; includeSubDomains"
ORIGIN = {"Origin": "http://localhost:3000"}


def check(r, *, hsts: bool = False) -> None:
    for name, value in STRICT.items():
        assert r.headers.get(name) == value, f"{name}: {r.headers.get(name)!r}"
    assert r.headers.get("strict-transport-security") == (HSTS if hsts else None)
    assert r.headers.get("x-request-id")
    for name in (*STRICT, "strict-transport-security", "cache-control"):
        assert len(r.headers.get_list(name)) <= 1, f"{name} sent twice"


def broken_app(prod: bool = False):
    """An application with a route that crashes, to see what a crash looks
    like from outside."""
    broken = create_app(prod=prod)

    @broken.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail")

    return broken


def test_on_every_kind_of_response(client, auth):
    too_big = "x" * (limits.JSON_BODY_MAX_BYTES + 1)
    responses = {
        "200": client.get("/health"),
        "200 with a token": client.get("/me", headers=auth),
        "401": client.get("/me"),
        "404 for a missing object": client.get("/postings/simplify:nope", headers=auth),
        "404 for a missing route": client.get("/no/such/route"),
        "405": client.delete("/health"),
        "409": client.get("/feed", headers=auth),
        "413 from the body limit": client.put("/profile", json={"school": too_big}, headers=auth),
        "422": client.post("/auth/register", json={"email": "nope"}),
        "preflight": client.options(
            "/feed", headers={**ORIGIN, "Access-Control-Request-Method": "GET"}
        ),
        "refused preflight": client.options(
            "/feed",
            headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
        ),
    }
    seen = {r.status_code for r in responses.values()}
    assert {200, 401, 404, 405, 409, 413, 422, 400} <= seen, seen
    for what, r in responses.items():
        try:
            check(r)
        except AssertionError as e:
            raise AssertionError(f"{what}: {e}") from None


def test_on_every_route_the_app_has(client, auth):
    routes = api_routes(app)
    assert len(routes) >= 20
    fill = {"application_id": 1, "posting_id": "simplify:x", "key": "resumes/1/x.pdf"}
    for method, template in sorted(routes):
        path = template.replace("{key:path}", "{key}").format(**fill)
        check(client.request(method, path, headers=auth, json={}))


def test_a_crash_is_a_response_like_any_other():
    """It has the security headers, the CORS headers a browser needs in order
    to read it, and a request id to find the traceback by. It says nothing
    about what went wrong."""
    with TestClient(broken_app(), raise_server_exceptions=False) as c:
        r = c.get("/boom", headers=ORIGIN)
    assert r.status_code == 500
    assert r.json() == {"detail": "Something went wrong on our side. Please try again."}
    assert "secret internal detail" not in r.text
    check(r)
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert r.headers["content-type"] == "application/json"


def test_refusals_are_readable_by_the_browser_too(client, auth):
    too_big = "x" * (limits.JSON_BODY_MAX_BYTES + 1)
    for r in (
        client.put("/profile", json={"school": too_big}, headers={**auth, **ORIGIN}),
        client.get("/me", headers=ORIGIN),
        client.post("/auth/register", json={"email": "nope"}, headers=ORIGIN),
    ):
        assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
        assert isinstance(r.json()["detail"], str)


def test_responses_are_not_cached(client, auth):
    for path in ("/me", "/health", "/ingest/status"):
        assert client.get(path, headers=auth).headers["cache-control"] == "no-store"


def test_a_route_that_sets_its_own_header_keeps_it():
    own = create_app(prod=False)

    @own.get("/cacheable")
    def cacheable():
        from fastapi.responses import JSONResponse

        return JSONResponse(
            {"ok": True},
            headers={"Cache-Control": "public, max-age=300", "X-Frame-Options": "SAMEORIGIN"},
        )

    with TestClient(own) as c:
        r = c.get("/cacheable")
    assert r.headers.get_list("cache-control") == ["public, max-age=300"]
    assert r.headers.get_list("x-frame-options") == ["SAMEORIGIN"]
    assert r.headers["x-content-type-options"] == "nosniff"


# --------------------------------------------------------------------------- #
# Strict-Transport-Security
# --------------------------------------------------------------------------- #


def test_no_hsts_over_plain_http_in_development(client):
    check(client.get("/health"), hsts=False)


def test_hsts_over_https():
    with TestClient(app, base_url="https://testserver") as c:
        check(c.get("/health"), hsts=True)
        check(c.get("/me"), hsts=True)


def test_hsts_always_in_production():
    """App Runner terminates TLS, so the last hop to the container is plain
    HTTP. Every request still reached us over HTTPS."""
    with TestClient(create_app(prod=True), raise_server_exceptions=False) as c:
        check(c.get("/health"), hsts=True)
        check(c.get("/no/such/route"), hsts=True)
    with TestClient(broken_app(prod=True), raise_server_exceptions=False) as c:
        check(c.get("/boom"), hsts=True)


def test_forwarded_proto_is_believed_only_behind_a_proxy(client, monkeypatch):
    https = {"X-Forwarded-Proto": "https"}
    check(client.get("/health", headers=https), hsts=False)
    monkeypatch.setattr(config, "TRUST_PROXY", True)
    check(client.get("/health", headers=https), hsts=True)
    check(client.get("/health", headers={"X-Forwarded-Proto": "http"}), hsts=False)
    check(client.get("/health"), hsts=False)


# --------------------------------------------------------------------------- #
# The interactive docs
# --------------------------------------------------------------------------- #


def test_docs_work_in_development_under_their_own_policy(client):
    r = client.get("/docs")
    assert r.status_code == 200 and "swagger" in r.text.lower()
    policy = r.headers["content-security-policy"]
    assert "https://cdn.jsdelivr.net" in policy and "frame-ancestors 'none'" in policy
    assert "default-src 'none'" not in policy
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    # The schema is JSON and gets the strict policy.
    check(client.get("/openapi.json"))
    assert client.get("/redoc").status_code == 404


def test_docs_and_schema_do_not_exist_in_production():
    with TestClient(create_app(prod=True)) as c:
        for path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
            r = c.get(path)
            assert r.status_code == 404, path
            assert r.json() == {"detail": "Not Found"}
            check(r, hsts=True)
        assert c.get("/health").status_code == 200


def test_production_serves_the_same_routes():
    assert set(api_routes(create_app(prod=True))) == set(api_routes(app))


# --------------------------------------------------------------------------- #
# Who is asking
# --------------------------------------------------------------------------- #


def scope(peer="10.0.0.9", forwarded=None, scheme="http", proto=None):
    headers = []
    if forwarded is not None:
        headers.append((b"x-forwarded-for", forwarded.encode()))
    if proto is not None:
        headers.append((b"x-forwarded-proto", proto.encode()))
    return {"type": "http", "client": (peer, 5000), "headers": headers, "scheme": scheme}


def test_forwarded_for_is_ignored_without_a_proxy(monkeypatch):
    monkeypatch.setattr(config, "TRUST_PROXY", False)
    assert client_ip(scope(forwarded="1.2.3.4")) == "10.0.0.9"
    assert client_ip(scope(forwarded="1.2.3.4, 5.6.7.8")) == "10.0.0.9"
    assert client_ip(scope()) == "10.0.0.9"
    assert not is_https(scope(proto="https"))


@pytest.mark.parametrize(
    ("hops", "forwarded", "expected"),
    [
        (1, "203.0.113.7", "203.0.113.7"),
        # The client sent a header of its own; the proxy appended the truth.
        (1, "1.1.1.1, 203.0.113.7", "203.0.113.7"),
        (1, "spoofed, also-spoofed, 203.0.113.7", "203.0.113.7"),
        (2, "203.0.113.7, 130.176.0.1", "203.0.113.7"),
        (2, "1.1.1.1, 203.0.113.7, 130.176.0.1", "203.0.113.7"),
        (1, " 203.0.113.7 ", "203.0.113.7"),
        # Fewer entries than proxies: not how requests reach us. Use the socket.
        (2, "203.0.113.7", "10.0.0.9"),
        (1, "", "10.0.0.9"),
        (1, None, "10.0.0.9"),
        (1, " , ", "10.0.0.9"),
    ],
)
def test_behind_proxies_the_address_is_counted_from_the_right(
    monkeypatch, hops, forwarded, expected
):
    monkeypatch.setattr(config, "TRUST_PROXY", True)
    monkeypatch.setattr(config, "TRUSTED_PROXY_HOPS", hops)
    assert client_ip(scope(forwarded=forwarded)) == expected


def test_proxy_settings_default_to_not_trusting():
    import os

    assert "TRUST_PROXY" not in os.environ
    assert config.TRUST_PROXY is False and config.TRUSTED_PROXY_HOPS == 1
