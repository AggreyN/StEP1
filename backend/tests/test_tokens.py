"""What the API accepts as a token, and what it does not."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app import config
from tests.conftest import register

NOW = datetime.now(UTC)


def sign(claims=None, key=None, algorithm="HS256", **over) -> str:
    body = {"sub": "1", "email": "ada@umd.edu", "iat": NOW, "exp": NOW + timedelta(hours=1)}
    body |= claims or {}
    body |= over
    body = {k: v for k, v in body.items() if v is not None}
    return jwt.encode(body, config.JWT_SECRET if key is None else key, algorithm=algorithm)


def me(client, token: str):
    return client.get("/me", headers={"Authorization": f"Bearer {token}"})


def test_a_token_we_signed_is_accepted(client):
    register(client)
    assert me(client, sign()).json()["email"] == "ada@umd.edu"


def test_tokens_from_before_the_library_changed_still_work(client):
    """Same algorithm, same secret, same claims: the same bytes. Nobody was
    signed out."""
    headers = register(client)
    issued = headers["Authorization"].removeprefix("Bearer ")
    claims = jwt.decode(issued, config.JWT_SECRET, algorithms=["HS256"])
    assert set(claims) == {"sub", "email", "iat", "exp"} and claims["sub"] == "1"
    assert me(client, issued).status_code == 200


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(sign(exp=NOW - timedelta(seconds=5)), id="expired"),
        pytest.param(sign(key="someone-elses-secret-of-the-same-length"), id="someone-elses-key"),
        pytest.param(sign(key=config.DEFAULT_JWT_SECRET), id="signed-with-the-public-default"),
        pytest.param(sign(exp=None), id="never-expires"),
        pytest.param(sign(sub=None), id="names-nobody"),
        pytest.param(sign(sub="1 OR 1=1"), id="sub-is-not-a-number"),
        pytest.param(sign(sub="999999"), id="names-someone-who-does-not-exist"),
        pytest.param(sign()[:-4] + "AAAA", id="signature-altered"),
        pytest.param(sign().rsplit(".", 1)[0] + ".", id="signature-removed"),
        pytest.param("", id="empty"),
        pytest.param("not-a-token", id="not-a-token"),
        pytest.param("a.b.c", id="three-parts-of-nothing"),
        pytest.param(jwt.encode({"sub": "1", "exp": NOW + timedelta(hours=1)}, None,
                                algorithm="none"), id="algorithm-none"),
        pytest.param(sign(key=config.JWT_SECRET * 2, algorithm="HS512"), id="another-algorithm"),
    ],
)  # fmt: skip
def test_everything_else_is_refused(client, token):
    register(client)
    r = me(client, token)
    assert r.status_code == 401, r.text
    assert r.json()["detail"] in (
        "Invalid or expired token.",
        "User no longer exists.",
        "Not authenticated.",
    )


def test_the_payload_cannot_be_edited(client):
    """Change who the token is for, keep the signature."""
    import base64
    import json

    register(client)
    register(client, email="grace@umd.edu")
    header, payload, signature = sign().split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
    claims["sub"] = "2"
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    assert me(client, f"{header}.{forged}.{signature}").status_code == 401


def test_a_refusal_does_not_say_why(client):
    register(client)
    for token in (sign(exp=NOW - timedelta(days=1)), sign(key="x" * 40), "junk"):
        assert me(client, token).json() == {"detail": "Invalid or expired token."}


def test_other_schemes_are_not_tokens(client):
    register(client)
    for value in (sign(), f"Basic {sign()}", f"Token {sign()}", "Bearer"):
        assert client.get("/me", headers={"Authorization": value}).status_code == 401


def test_nothing_imports_the_library_that_was_removed():
    from pathlib import Path

    app_dir = Path(config.__file__).parent
    for path in app_dir.rglob("*.py"):
        assert "from jose" not in path.read_text() and "import jose" not in path.read_text(), path
    requirements = (app_dir.parent / "requirements.txt").read_text()
    assert "PyJWT" in requirements
    assert not any(
        line.strip().startswith(("python-jose", "ecdsa")) for line in requirements.splitlines()
    )
