"""The API behind a real server, over a real socket.

Every other test calls the application directly, which is fast and leaves out
the one component that sits between the network and the app. That component
has opinions of its own: uvicorn rewrites the client's address from
X-Forwarded-For when the connection comes from a host it trusts, and by
default it trusts this machine. A rate limit keyed on that address could be
reset by sending a header, and no in-process test could see it.
"""

from __future__ import annotations

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


@pytest.fixture()
def server(tmp_path):
    """uvicorn, started the way the README says to start it, with no flags
    that would make it safer than the default."""
    port = _free_port()
    env = os.environ | {
        "RATE_LIMIT_ENABLED": "true",
        "TRUST_PROXY": "false",
        "AUTO_INGEST": "false",
        "UPLOAD_DIR": str(tmp_path / "uploads"),
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
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


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
