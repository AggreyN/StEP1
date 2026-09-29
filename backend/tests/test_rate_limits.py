"""Rate limits on the routes that can be abused without an account, or
against one. Off for the rest of the suite; switched on here."""

import time

import pytest

from app import config, ratelimit
from app.ratelimit import limiter, wait_in_words
from tests.conftest import api_routes, register

ORIGIN = {"Origin": "http://localhost:3000"}


@pytest.fixture(autouse=True)
def limits_on(monkeypatch):
    limiter.reset()
    monkeypatch.setattr(limiter, "enabled", True)
    yield
    limiter.reset()


def login(client, password="wrong-password", email="ada@umd.edu", **headers):
    return client.post("/auth/login", json={"email": email, "password": password}, headers=headers)


def signup(client, n, **headers):
    return client.post(
        "/auth/register",
        json={"email": f"user{n}@example.com", "password": "correct-horse"},
        headers=headers,
    )


def test_the_suite_runs_with_limits_off():
    assert config.RATE_LIMIT_ENABLED is False
    assert (config.LOGIN_RATE_LIMIT, config.REGISTER_RATE_LIMIT) == ("10/minute", "5/hour")


def test_the_eleventh_sign_in_is_refused(client):
    register(client)
    limiter.reset()
    for attempt in range(10):
        assert login(client).status_code == 401, attempt

    r = login(client)
    assert r.status_code == 429
    assert r.json() == {"detail": "Too many sign-in attempts. Try again in a minute."}
    assert 1 <= int(r.headers["retry-after"]) <= 60
    # The right password is refused too: the limit is on attempts, and
    # letting a correct guess through would confirm it.
    assert login(client, password="correct-horse").status_code == 429


def test_a_refusal_is_readable_by_the_browser(client):
    register(client)
    limiter.reset()
    for _ in range(10):
        login(client, **ORIGIN)
    r = login(client, **ORIGIN)
    assert r.status_code == 429
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "retry-after" in r.headers["access-control-expose-headers"].lower()
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-request-id"]
    assert r.headers["content-type"] == "application/json"


def test_successful_sign_ins_count_too(client):
    register(client)
    limiter.reset()
    for _ in range(10):
        assert login(client, password="correct-horse").status_code == 200
    assert login(client, password="correct-horse").status_code == 429


def test_the_sixth_registration_is_refused(client):
    for n in range(5):
        assert signup(client, n).status_code == 200, n
    r = signup(client, 5)
    assert r.status_code == 429
    assert r.json() == {
        "detail": "Too many accounts created from here. Try again in about an hour."
    }
    assert 3000 <= int(r.headers["retry-after"]) <= 3600
    # Refused before anything was written.
    assert login(client, "correct-horse", "user5@example.com").status_code == 401


def test_a_malformed_request_is_refused_without_being_counted(client):
    """Validation runs before the limiter. A request that fails it never
    reaches a password check or a query, so it costs nothing worth limiting,
    and it does not use up the allowance of whoever shares the address."""
    register(client)
    limiter.reset()
    for _ in range(15):
        assert client.post("/auth/login", json={"email": "nope"}).status_code == 422
    assert [login(client).status_code for _ in range(11)] == [401] * 10 + [429]


def test_limits_are_separate_per_route(client):
    register(client)
    limiter.reset()
    for _ in range(11):
        login(client)
    assert login(client).status_code == 429
    assert signup(client, 1).status_code == 200  # register has its own counter
    assert client.get("/health").status_code == 200


def test_limits_are_separate_per_address(client, monkeypatch):
    """Behind a proxy, each client is limited on its own, and one client
    running out does nothing to the next."""
    monkeypatch.setattr(config, "TRUST_PROXY", True)
    client.post(
        "/auth/register",
        json={"email": "ada@umd.edu", "password": "correct-horse"},
        headers={"X-Forwarded-For": "198.51.100.1"},
    )
    noisy = {"X-Forwarded-For": "203.0.113.7"}
    quiet = {"X-Forwarded-For": "203.0.113.8"}
    for _ in range(10):
        assert login(client, **noisy).status_code == 401
    assert login(client, **noisy).status_code == 429
    assert login(client, **quiet).status_code == 401
    assert login(client, password="correct-horse", **quiet).status_code == 200


def test_a_client_cannot_pick_its_own_address(client, monkeypatch):
    """Without a proxy, X-Forwarded-For is just a header. A different value
    on every request must not buy a fresh allowance."""
    register(client)
    limiter.reset()
    assert config.TRUST_PROXY is False
    codes = [login(client, **{"X-Forwarded-For": f"10.9.8.{n}"}).status_code for n in range(12)]
    assert codes == [401] * 10 + [429] * 2

    # Behind one proxy, what the client put in front of the proxy's entry
    # is ignored as well.
    limiter.reset()
    monkeypatch.setattr(config, "TRUST_PROXY", True)
    codes = [
        login(client, **{"X-Forwarded-For": f"10.9.8.{n}, 203.0.113.7"}).status_code
        for n in range(12)
    ]
    assert codes == [401] * 10 + [429] * 2


def test_limits_are_configurable(client, monkeypatch):
    monkeypatch.setattr(config, "LOGIN_RATE_LIMIT", "2/minute")
    register(client)
    limiter.reset()
    assert [login(client).status_code for _ in range(3)] == [401, 401, 429]


def test_limits_can_be_switched_off(client, monkeypatch):
    monkeypatch.setattr(limiter, "enabled", False)
    register(client)
    assert {login(client).status_code for _ in range(15)} == {401}


def test_the_window_slides(client, monkeypatch):
    """Two attempts a second are used up at once and return one at a time,
    a second after each was made. Nothing resets all at once."""
    monkeypatch.setattr(config, "LOGIN_RATE_LIMIT", "2/second")
    register(client)
    limiter.reset()
    assert [login(client).status_code for _ in range(3)] == [401, 401, 429]
    time.sleep(1.1)
    assert login(client).status_code == 401


def test_a_bad_limit_stops_the_app_from_starting(monkeypatch):
    monkeypatch.setattr(config, "LOGIN_RATE_LIMIT", "ten per minute")
    with pytest.raises(RuntimeError, match="LOGIN_RATE_LIMIT='ten per minute' is not a rate"):
        config._check_rate_limits()


@pytest.mark.parametrize(
    ("seconds", "words"),
    [(1, "in a minute"), (59, "in a minute"), (90, "in a minute"), (91, "in 2 minutes"),
     (600, "in 10 minutes"), (3000, "in 50 minutes"), (3001, "in about an hour"),
     (3600, "in about an hour"), (5400, "in about an hour"), (7200, "in about 2 hours")],
)  # fmt: skip
def test_waits_are_said_the_way_a_person_would(seconds, words):
    assert wait_in_words(seconds) == words


def test_every_unauthenticated_write_is_limited():
    """A route that needs no token and changes something is a route anyone
    can hammer. Each must carry a limit."""
    from app.main import app

    limited = {
        f"{r.endpoint.__module__}.{r.endpoint.__name__}"
        for r in api_routes(app).values()
        if f"{r.endpoint.__module__}.{r.endpoint.__name__}" in limiter._route_limits
        or f"{r.endpoint.__module__}.{r.endpoint.__name__}" in limiter._dynamic_route_limits
    }
    assert {"app.routes.auth.login", "app.routes.auth.register"} <= limited
    for (method, path), route in api_routes(app).items():
        needs_token = any(
            d.call.__name__ in ("current_user", "onboarded_profile")
            for d in route.dependant.dependencies
        )
        if not needs_token and method != "GET":
            name = f"{route.endpoint.__module__}.{route.endpoint.__name__}"
            assert name in limited, f"{method} {path} takes no token and has no rate limit"


def test_sign_in_takes_as_long_for_no_account_as_for_a_wrong_password(client, monkeypatch):
    """If a missing account answered faster, the time would say which emails
    are registered. Both paths check one password against one hash."""
    monkeypatch.setattr(limiter, "enabled", False)
    register(client)
    import app.routes.auth as auth_routes

    checked = []
    real = auth_routes.verify_password
    monkeypatch.setattr(
        auth_routes, "verify_password", lambda p, h: checked.append(h) or real(p, h)
    )
    login(client, email="ada@umd.edu")
    login(client, email="nobody@umd.edu")
    assert len(checked) == 2 and all(h.startswith("$2b$") for h in checked)
    assert checked[0] != checked[1]
    assert ratelimit.limiter is limiter
