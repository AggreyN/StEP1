"""The API behind a real server, over a real socket.

Every other test calls the application directly, which is fast and leaves out
the one component that sits between the network and the app. That component
has opinions of its own: uvicorn rewrites the client's address from
X-Forwarded-For when the connection comes from a host it trusts, and by
default it trusts this machine. A rate limit keyed on that address could be
reset by sending a header, and no in-process test could see it.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _post(base: str, path: str, body: dict, **headers) -> tuple[int, dict, dict]:
    request = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        response = urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as refused:
        response = refused
    return response.status, json.loads(response.read() or b"{}"), dict(response.headers)


@contextlib.contextmanager
def running(tmp_path, *flags: str, **settings: str):
    """uvicorn in a process of its own, on a free port."""
    port = _free_port()
    env = os.environ | {
        "RATE_LIMIT_ENABLED": "true",
        "TRUST_PROXY": "false",
        "AUTO_INGEST": "false",
        "UPLOAD_DIR": str(tmp_path / "uploads"),
        **settings,
    }
    env.pop("FORWARDED_ALLOW_IPS", None)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            *flags,
        ],  # fmt: skip
        cwd=BACKEND,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if urllib.request.urlopen(base + "/health", timeout=1).status == 200:
                    break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("the server did not start")
        yield base
    finally:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()


@pytest.fixture()
def server(tmp_path):
    """Started the way the README says to start it on a laptop, with no
    flags that would make it safer than the default."""
    with running(tmp_path) as base:
        yield base


@pytest.fixture()
def behind_load_balancer(tmp_path):
    """Started the way the container starts it, with the settings in
    .env.production.example for the path load balancer -> task. This test
    plays the load balancer: it is the only thing that connects, and it adds
    the client's address to the end of X-Forwarded-For, as an Application
    Load Balancer does."""
    with running(
        tmp_path, "--no-proxy-headers", TRUST_PROXY="true", TRUSTED_PROXY_HOPS="1"
    ) as base:
        yield base


def test_a_forwarded_header_does_not_reset_the_sign_in_limit(server):
    status, _, _ = _post(
        server, "/auth/register", {"email": "ada@umd.edu", "password": "correct-horse"}
    )
    assert status == 200

    wrong = {"email": "ada@umd.edu", "password": "a-wrong-guess"}
    claims = [
        {},
        {"X-Forwarded-For": "8.8.8.8"},
        {"X-Forwarded-For": "8.8.4.4"},
        {"X-Forwarded-For": "1.1.1.1:443"},
        {"X-Forwarded-For": "9.9.9.9, 8.8.8.8"},
        {"X-Forwarded-For": "[2001:db8::1]:443"},
        {"X-Forwarded-For": "203.0.113.1"},
        {"X-Forwarded-For": "203.0.113.2"},
        {"X-Forwarded-For": "203.0.113.3"},
        {"X-Forwarded-For": "203.0.113.4"},
    ]
    # Ten attempts are allowed from this machine as itself. Every attempt
    # that claims to be someone else shares one further allowance of ten,
    # however many someones it claims to be.
    seen = []
    for attempt in range(40):
        status, _, _ = _post(server, "/auth/login", wrong, **claims[attempt % len(claims)])
        seen.append(status)
    allowed = seen.count(401)
    assert set(seen) == {401, 429}, seen
    assert allowed <= 20, f"{allowed} attempts got through: {seen}"

    # And the refusals are real: the right password is refused too, under any
    # address not yet claimed.
    right = {"email": "ada@umd.edu", "password": "correct-horse"}
    for claim in ("198.51.100.77", "198.51.100.78:8080", "10.1.2.3"):
        status, body, headers = _post(server, "/auth/login", right, **{"X-Forwarded-For": claim})
        assert status == 429, (claim, status, body)
        assert body == {"detail": "Too many sign-in attempts. Try again in a minute."}
        assert 1 <= int(headers["retry-after"]) <= 60


def test_a_forwarded_proto_does_not_change_what_is_served(server):
    """The scheme can be rewritten the same way. Nothing that matters may
    depend on it: the most a client can do is ask to be sent HSTS."""
    request = urllib.request.Request(server + "/health", headers={"X-Forwarded-Proto": "https"})
    response = urllib.request.urlopen(request, timeout=10)
    assert response.status == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert json.loads(response.read()) == {"status": "ok", "db": "ok"}


# --------------------------------------------------------------------------- #
# Behind an Application Load Balancer
# --------------------------------------------------------------------------- #

WRONG = {"email": "ada@umd.edu", "password": "a-wrong-guess"}
RIGHT = {"email": "ada@umd.edu", "password": "correct-horse"}


def through_the_load_balancer(client_ip: str, sent_by_client: str | None = None) -> dict:
    """The headers a request arrives with after an Application Load Balancer
    has handled it. In its default mode it appends the address of whoever
    connected to it to whatever X-Forwarded-For the request already had, and
    sets X-Forwarded-Proto to the scheme the client used."""
    chain = f"{sent_by_client}, {client_ip}" if sent_by_client else client_ip
    return {"X-Forwarded-For": chain, "X-Forwarded-Proto": "https", "X-Forwarded-Port": "443"}


def attempts(base: str, body: dict, headers: list[dict]) -> list[int]:
    return [_post(base, "/auth/login", body, **h)[0] for h in headers]


def test_each_real_client_has_its_own_allowance(behind_load_balancer):
    base = behind_load_balancer
    assert (
        _post(base, "/auth/register", RIGHT, **through_the_load_balancer("198.51.100.1"))[0] == 200
    )

    one = [through_the_load_balancer("203.0.113.7")] * 12
    assert attempts(base, WRONG, one) == [401] * 10 + [429] * 2
    # Someone else, at another address, is not affected by that.
    other = [through_the_load_balancer("203.0.113.8")] * 3
    assert attempts(base, WRONG, other) == [401] * 3
    assert _post(base, "/auth/login", RIGHT, **through_the_load_balancer("203.0.113.8"))[0] == 200
    # And the first is still refused, with the right password too.
    status, body, headers = _post(
        base, "/auth/login", RIGHT, **through_the_load_balancer("203.0.113.7")
    )
    assert status == 429
    assert body == {"detail": "Too many sign-in attempts. Try again in a minute."}
    assert 1 <= int(headers["retry-after"]) <= 60


def test_a_forged_header_does_not_survive_the_load_balancer(behind_load_balancer):
    """The client sends X-Forwarded-For itself, a different one each time.
    The load balancer adds the truth to the end, and the end is what is read."""
    base = behind_load_balancer
    _post(base, "/auth/register", RIGHT, **through_the_load_balancer("198.51.100.1"))

    attacker = "198.51.100.66"
    forged = [
        "8.8.8.8",
        "1.1.1.1, 9.9.9.9",
        "203.0.113.200",
        "127.0.0.1",
        "10.0.0.1, 10.0.0.2, 10.0.0.3",
        "unknown",
        "[2001:db8::1]:443",
        "198.51.100.1",  # the address of a real user, to spend their allowance
        "0.0.0.0",
        "8.8.4.4:12345",
        "203.0.113.201",
        "203.0.113.202",
    ]
    headers = [through_the_load_balancer(attacker, sent_by_client=f) for f in forged]
    assert attempts(base, WRONG, headers) == [401] * 10 + [429] * 2

    # The user whose address was named in a forged header has lost nothing.
    victim = [through_the_load_balancer("198.51.100.1")] * 9
    assert attempts(base, WRONG, victim) == [401] * 9


def test_the_load_balancers_own_requests_are_not_mistaken_for_a_client(behind_load_balancer):
    """Health checks come from the load balancer itself, with no
    X-Forwarded-For. They are keyed on its address, and /health has no limit
    in any case."""
    for _ in range(40):
        assert urllib.request.urlopen(behind_load_balancer + "/health", timeout=5).status == 200


def test_hsts_is_sent_for_a_request_that_arrived_over_https(behind_load_balancer):
    """TLS ends at the load balancer; the hop to the task is plain HTTP.
    X-Forwarded-Proto says how the client really connected."""
    request = urllib.request.Request(
        behind_load_balancer + "/health", headers=through_the_load_balancer("203.0.113.7")
    )
    response = urllib.request.urlopen(request, timeout=5)
    assert response.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"

    plain = urllib.request.urlopen(behind_load_balancer + "/health", timeout=5)
    assert plain.headers["strict-transport-security"] is None  # dev build, no https
