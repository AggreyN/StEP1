"""AUTH_MODE=cognito, tested without AWS.

A key pair stands in for the pool's, a local server stands in for its
well-known keys URL, and tokens are made here exactly as the pool makes them.
Then every way a token can be wrong is tried, and every way the keys can be
missing.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import http.server
import json
import threading
import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import func, select

from app import config
from app.models import User
from app.services import cognito
from tests.conftest import make_row, onboard, register, seed, upload_resume

REGION = "us-east-1"
POOL = "us-east-1_TestPool1"
CLIENT = "7testclientid1234567890ab"
ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{POOL}"
NEWER_ISSUER = f"https://issuer-cognito-idp.{REGION}.amazonaws.com/{POOL}"
REFUSED = {"detail": "Invalid or expired token."}
UNAVAILABLE = {"detail": "Sign-in can't be checked right now. Try again in a minute."}


class Key:
    """A signing key pair, and the public half as the pool publishes it."""

    def __init__(self, kid: str):
        self.kid = kid
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.pem = self.private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        self.public_pem = self.private.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        self.jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.private.public_key())) | {
            "kid": kid,
            "alg": "RS256",
            "use": "sig",
        }


# Made once: generating a 2048-bit key takes a noticeable fraction of a second.
ID_KEY = Key("id-token-key")
ACCESS_KEY = Key("access-token-key")
ROTATED = Key("key-after-rotation")
STRANGER = Key("id-token-key")  # another pool's key that happens to share the kid


class Pool:
    """The pool's keys endpoint, with a switch for each way it can fail."""

    def __init__(self):
        self.keys = [ID_KEY.jwk, ACCESS_KEY.jwk]
        self.mode = "ok"
        self.requests = 0
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                owner.requests += 1
                if owner.mode == "error":
                    self.send_response(500)
                    self.end_headers()
                    return
                if owner.mode == "slow":
                    time.sleep(3)
                body = {
                    "ok": json.dumps({"keys": owner.keys}),
                    "slow": json.dumps({"keys": owner.keys}),
                    "garbage": "<html>not json</html>",
                    "empty": json.dumps({"keys": []}),
                    "wrong-shape": json.dumps({"kees": owner.keys}),
                }[owner.mode].encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/.well-known/jwks.json"
        threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        ).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def expire_cache(self):
        """As if an hour had passed since the keys were fetched."""
        with cognito._lock:
            cognito._state["next_refresh"] = 0.0

    def allow_another_lookup_of_an_unknown_kid(self):
        with cognito._lock:
            cognito._state["next_unknown_kid_fetch"] = 0.0


@pytest.fixture()
def pool(monkeypatch):
    stub = Pool()
    monkeypatch.setattr(config, "AUTH_MODE", "cognito")
    monkeypatch.setattr(config, "AWS_REGION", REGION)
    monkeypatch.setattr(config, "COGNITO_USER_POOL_ID", POOL)
    monkeypatch.setattr(config, "COGNITO_APP_CLIENT_ID", CLIENT)
    monkeypatch.setattr(config, "COGNITO_ISSUER", ISSUER)
    monkeypatch.setattr(config, "COGNITO_JWKS_URL", stub.url)
    monkeypatch.setattr(config, "COGNITO_JWKS_PATH", "")
    monkeypatch.setattr(config, "COGNITO_JWKS_TIMEOUT_S", 1.0)
    cognito.forget_keys()
    yield stub
    stub.stop()
    cognito.forget_keys()


def claims(sub: str = "sub-ada", email: str = "ada@umd.edu", **over) -> dict:
    """An ID token's claims, as a user pool issues them."""
    now = int(time.time())
    body = {
        "sub": sub,
        "iss": ISSUER,
        "aud": CLIENT,
        "token_use": "id",
        "auth_time": now,
        "iat": now,
        "exp": now + 3600,
        "email": email,
        "email_verified": True,
        "name": "Ada Lovelace",
        "cognito:username": sub,
        "event_id": str(uuid.uuid4()),
        "jti": str(uuid.uuid4()),
        "origin_jti": str(uuid.uuid4()),
    }
    body |= over
    return {k: v for k, v in body.items() if v is not None}


def token(key: Key = ID_KEY, kid: str | None = None, **over) -> str:
    return jwt.encode(claims(**over), key.pem, algorithm="RS256", headers={"kid": kid or key.kid})


def b64(data: bytes | dict) -> str:
    if isinstance(data, dict):
        data = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def bearer(value: str) -> dict:
    return {"Authorization": f"Bearer {value}"}


def me(client, value: str):
    return client.get("/me", headers=bearer(value))


def users(db) -> list[User]:
    db.expire_all()
    return list(db.scalars(select(User).order_by(User.id)))


# --------------------------------------------------------------------------- #
# A good token
# --------------------------------------------------------------------------- #


def test_a_valid_token_signs_in_and_creates_the_user(client, pool, db):
    r = me(client, token())
    assert r.status_code == 200, r.text
    assert r.json() == {
        "id": 1,
        "email": "ada@umd.edu",
        "display_name": "Ada Lovelace",
        "onboarded": False,
    }
    (user,) = users(db)
    assert user.cognito_sub == "sub-ada" and user.password_hash is None
    assert pool.requests == 1


def test_the_same_person_is_the_same_user_every_time(client, pool, db):
    first = me(client, token()).json()["id"]
    for _ in range(5):
        assert me(client, token()).json()["id"] == first
    assert len(users(db)) == 1
    assert pool.requests == 1, "the keys are fetched once and kept"


def test_a_whole_session_works_on_a_cognito_token(client, pool):
    """Every kind of route, with the pool's token in place of our own."""
    seed([make_row("a"), make_row("b", company="Globex")])
    headers = bearer(token())
    assert upload_resume(client, headers).status_code == 200
    onboard(client, headers)
    assert client.get("/feed", headers=headers).json()["total"] == 2
    assert client.post("/saved/simplify:a", headers=headers).status_code == 204
    created = client.post("/applications", json={"posting_id": "simplify:b"}, headers=headers)
    assert created.status_code == 201
    assert client.get("/profile", headers=headers).json()["resume"]["filename"] == "resume.pdf"


def test_both_forms_of_the_issuer_are_this_pool(client, pool):
    assert me(client, token(iss=ISSUER)).status_code == 200
    assert me(client, token(iss=NEWER_ISSUER)).status_code == 200


def test_a_token_a_few_seconds_early_is_clock_skew_not_forgery(client, pool):
    soon = int(time.time()) + 3
    assert me(client, token(iat=soon, auth_time=soon)).status_code == 200


# --------------------------------------------------------------------------- #
# Who a token belongs to
# --------------------------------------------------------------------------- #


def test_users_are_matched_by_sub_never_by_email(client, pool, db):
    """Same address, different identity. It is a different person as far as
    the pool is concerned, and it does not get the first one's account."""
    seed([make_row("a")])
    ada = bearer(token(sub="sub-ada", email="ada@umd.edu"))
    assert upload_resume(client, ada).status_code == 200
    onboard(client, ada)
    client.post("/saved/simplify:a", headers=ada)

    impostor = bearer(token(sub="sub-someone-else", email="ada@umd.edu"))
    r = client.get("/me", headers=impostor)
    assert r.status_code == 409
    assert "not linked to this sign-in" in r.json()["detail"]
    for path in ("/profile", "/saved", "/applications", "/feed"):
        assert client.get(path, headers=impostor).status_code == 409, path
    assert client.request("DELETE", "/me", headers=impostor).status_code == 409

    (only,) = users(db)
    assert only.cognito_sub == "sub-ada"
    assert client.get("/saved", headers=ada).json()["total"] == 1
    assert client.get("/profile", headers=ada).json()["resume"] is not None


def test_a_local_account_is_not_handed_to_a_matching_email(client, pool, db, monkeypatch):
    """Someone registered with a password while the app ran in local mode.
    A cognito sign-in that names the same address is not that person until
    someone links the two on purpose."""
    monkeypatch.setattr(config, "AUTH_MODE", "local")
    local = register(client, email="ada@umd.edu", password="her-own-password")
    onboard(client, local)
    monkeypatch.setattr(config, "AUTH_MODE", "cognito")

    r = me(client, token(sub="sub-ada", email="ada@umd.edu"))
    assert r.status_code == 409
    (only,) = users(db)
    assert only.cognito_sub is None and only.password_hash.startswith("$2b$")

    # Linked deliberately, in the database, it is then found by sub.
    only.cognito_sub = "sub-ada"
    db.commit()
    assert me(client, token(sub="sub-ada", email="ada@umd.edu")).json()["onboarded"] is True


def test_a_changed_email_follows_the_user(client, pool, db):
    first = me(client, token(sub="sub-ada", email="ada@umd.edu")).json()
    changed = me(client, token(sub="sub-ada", email="Ada.Lovelace@UMD.edu", name="Ada L.")).json()
    assert changed == first | {"email": "ada.lovelace@umd.edu", "display_name": "Ada L."}
    assert len(users(db)) == 1


def test_a_changed_email_cannot_take_an_address_in_use(client, pool, db):
    me(client, token(sub="sub-ada", email="ada@umd.edu"))
    me(client, token(sub="sub-grace", email="grace@umd.edu"))
    r = me(client, token(sub="sub-grace", email="ada@umd.edu"))
    assert r.status_code == 200 and r.json()["email"] == "grace@umd.edu"
    assert [(u.cognito_sub, u.email) for u in users(db)] == [
        ("sub-ada", "ada@umd.edu"),
        ("sub-grace", "grace@umd.edu"),
    ]


def test_a_token_with_no_email_still_has_an_account(client, pool, db):
    r = me(client, token(sub="sub-anon", email=None))
    assert r.status_code == 200
    assert r.json()["email"] == "sub-anon@users.cognito.invalid"


def test_several_first_requests_at_once_make_one_user(client, pool, db):
    value = token(sub="sub-burst", email="burst@umd.edu")
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(me(client, value).status_code))
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == [200] * 8
    assert db.scalar(select(func.count()).where(User.cognito_sub == "sub-burst")) == 1


# --------------------------------------------------------------------------- #
# A token that is wrong
# --------------------------------------------------------------------------- #

NOW = int(time.time())

WRONG = {
    "another pool's issuer": dict(
        iss=f"https://cognito-idp.{REGION}.amazonaws.com/us-east-1_Other"
    ),
    "the right pool in another region": dict(
        iss=f"https://cognito-idp.us-west-2.amazonaws.com/{POOL}"
    ),
    "an issuer that only starts the same": dict(iss=ISSUER + ".evil.example"),
    "an issuer over http": dict(iss=ISSUER.replace("https://", "http://")),
    "no issuer": dict(iss=None),
    "another app client": dict(aud="another-client-in-the-pool"),
    "no audience": dict(aud=None),
    "an audience that contains ours": dict(aud=CLIENT + "-and-more"),
    "an access token": dict(token_use="access", aud=None, client_id=CLIENT, scope="openid"),
    "an access token dressed as ours": dict(token_use="access"),
    "no token_use": dict(token_use=None),
    "a made-up token_use": dict(token_use="refresh"),
    "expired an hour ago": dict(exp=NOW - 3600),
    "expired a minute ago": dict(exp=NOW - 60),
    "no expiry": dict(exp=None),
    "not valid for another hour": dict(nbf=NOW + 3600),
    "issued an hour from now": dict(iat=NOW + 3600, auth_time=NOW + 3600),
    "no sub": dict(sub=None),
    "an empty sub": dict(sub=""),
    "no iat": dict(iat=None),
}


@pytest.mark.parametrize("what", sorted(WRONG))
def test_a_wrong_token_is_refused(client, pool, db, what):
    assert me(client, token()).status_code == 200  # the keys are good

    over = dict(WRONG[what])
    if over.get("sub") == "":
        # The library will not write an empty subject; the pool would not
        # either. Built by hand, as a forger would.
        body = claims() | {"sub": ""}
        signing_input = f"{b64({'alg': 'RS256', 'kid': ID_KEY.kid, 'typ': 'JWT'})}.{b64(body)}"
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        signature = ID_KEY.private.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
        bad = f"{signing_input}.{b64(signature)}"
    else:
        bad = token(**{"sub": "sub-intruder", "email": "intruder@umd.edu"} | over)

    r = me(client, bad)
    assert r.status_code == 401, f"{what}: {r.status_code} {r.text}"
    assert r.json() == REFUSED, what
    assert [u.cognito_sub for u in users(db)] == ["sub-ada"], "a refused token made a user"


def test_signed_by_someone_else(client, pool, db):
    """The right kid, the right claims, the wrong key."""
    r = me(client, token(key=STRANGER))
    assert r.status_code == 401 and r.json() == REFUSED
    assert users(db) == []


def test_signed_with_the_pools_other_key(client, pool):
    """A pool signs ID tokens and access tokens with different keys. A token
    claiming to be an ID token under the access key's kid is signed validly
    by the pool, and is still not an ID token the pool would issue. It is
    accepted or refused on its claims alone, and these claim to be an ID
    token; what matters is that an access token is not."""
    access = token(key=ACCESS_KEY, token_use="access", aud=None, client_id=CLIENT)
    assert me(client, access).json() == REFUSED


def test_altered_after_signing(client, pool):
    header, payload, signature = token().split(".")
    body = json.loads(base64.urlsafe_b64decode(payload + "=="))
    body["sub"], body["email"] = "sub-victim", "victim@umd.edu"
    assert me(client, f"{header}.{b64(body)}.{signature}").json() == REFUSED
    assert me(client, f"{header}.{payload}.{signature[:-6]}AAAAAA").json() == REFUSED
    assert me(client, f"{header}.{payload}.").json() == REFUSED
    assert me(client, f"{header}.{payload}").json() == REFUSED


def test_algorithm_none(client, pool, db):
    """The token says it needs no signature."""
    for alg in ("none", "None", "NONE", "nOnE"):
        header = {"alg": alg, "kid": ID_KEY.kid, "typ": "JWT"}
        for signature in ("", "anything"):
            r = me(client, f"{b64(header)}.{b64(claims())}.{signature}")
            assert r.status_code == 401 and r.json() == REFUSED, (alg, signature)
    assert users(db) == []
    assert pool.requests == 0, "the algorithm is refused before any key is fetched"


def test_hs256_signed_with_the_public_key(client, pool, db):
    """The classic. The public key is public; if the server could be talked
    into treating it as an HMAC secret, anyone could sign anything."""
    me(client, token())  # so the keys are loaded, as they would be
    for secret in (
        ID_KEY.public_pem,
        ID_KEY.public_pem.strip(),
        json.dumps(ID_KEY.jwk).encode(),
        base64.urlsafe_b64decode(ID_KEY.jwk["n"] + "=="),
    ):
        for alg, digest in (("HS256", hashlib.sha256), ("HS384", hashlib.sha384),
                            ("HS512", hashlib.sha512)):  # fmt: skip
            header = {"alg": alg, "kid": ID_KEY.kid, "typ": "JWT"}
            body = claims(sub="sub-forged", email="forged@umd.edu")
            signing_input = f"{b64(header)}.{b64(body)}".encode()
            forged = (
                f"{signing_input.decode()}.{b64(hmac.new(secret, signing_input, digest).digest())}"
            )
            r = me(client, forged)
            assert r.status_code == 401 and r.json() == REFUSED, alg
    assert [u.cognito_sub for u in users(db)] == ["sub-ada"]


def test_other_algorithms_are_refused_by_name(client, pool):
    for alg in ("RS384", "RS512", "PS256", "ES256", "EdDSA", "HS256", "", None, 5):
        header = {"alg": alg, "kid": ID_KEY.kid, "typ": "JWT"}
        assert me(client, f"{b64(header)}.{b64(claims())}.{b64(b'x' * 256)}").json() == REFUSED


def test_a_token_of_ours_is_not_a_token_of_the_pools(client, pool):
    """Local tokens are HS256 under JWT_SECRET. In cognito mode that secret
    signs nobody in, even though it is still configured."""
    ours = jwt.encode(
        {"sub": "1", "email": "ada@umd.edu", "iat": NOW, "exp": NOW + 3600},
        config.JWT_SECRET,
        algorithm="HS256",
    )
    assert me(client, ours).json() == REFUSED


@pytest.mark.parametrize("junk", ["", "x", "a.b.c", "....", "Bearer", "e30.e30.e30", "a" * 5000])
def test_things_that_are_not_tokens(client, pool, junk):
    r = me(client, junk)
    assert r.status_code == 401
    assert r.json() in (REFUSED, {"detail": "Not authenticated."})


def test_a_refusal_never_says_why(client, pool):
    me(client, token())
    seen = {
        json.dumps(me(client, bad).json())
        for bad in (
            token(exp=NOW - 60),
            token(aud="other"),
            token(iss="https://evil.example"),
            token(key=STRANGER),
            token(token_use="access"),
            token(kid="no-such-key"),
            "junk",
        )
    }
    assert seen == {json.dumps(REFUSED)}


# --------------------------------------------------------------------------- #
# A kid that is not known
# --------------------------------------------------------------------------- #


def test_an_unknown_kid_fetches_the_keys_once(client, pool):
    assert me(client, token()).status_code == 200
    assert pool.requests == 1

    assert me(client, token(kid="made-up-1")).json() == REFUSED
    assert pool.requests == 2, "one look, in case the pool has rotated its keys"

    # And then no more, whatever is sent. Each would be a request to Cognito
    # that anyone on the internet could cause.
    for n in range(50):
        assert me(client, token(kid=f"made-up-{n}")).status_code == 401
    assert pool.requests == 2

    # Known keys are unaffected throughout.
    assert me(client, token()).status_code == 200
    assert pool.requests == 2


def test_a_rotated_key_is_picked_up_without_a_restart(client, pool):
    assert me(client, token()).status_code == 200
    # The pool rotates: the old key is gone from the set, a new one is in it.
    pool.keys = [ROTATED.jwk, ACCESS_KEY.jwk]

    after = token(key=ROTATED)
    assert me(client, after).status_code == 200, "the first token under the new key"
    assert pool.requests == 2
    assert me(client, after).status_code == 200
    assert pool.requests == 2

    # The retired key is no longer in the set, and no longer accepted.
    assert me(client, token(key=ID_KEY)).json() == REFUSED


def test_a_rotation_during_the_cooldown_is_picked_up_after_it(client, pool):
    me(client, token())
    assert me(client, token(kid="made-up")).status_code == 401  # uses up the one look
    pool.keys = [ROTATED.jwk]
    assert me(client, token(key=ROTATED)).status_code == 401  # too soon to look again
    pool.allow_another_lookup_of_an_unknown_kid()
    assert me(client, token(key=ROTATED)).status_code == 200


# --------------------------------------------------------------------------- #
# Keys that cannot be fetched
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("failure", ["error", "garbage", "empty", "wrong-shape", "slow", "down"])
def test_with_no_keys_nobody_is_let_in_and_nothing_breaks(client, pool, db, failure):
    """Fails closed. 503, because the token may be fine and the fault is
    upstream: not 401, not 500, and above all not 200."""
    if failure == "down":
        pool.stop()
    else:
        pool.mode = failure

    for value in (token(), token(sub="sub-forged", key=STRANGER), token(kid="made-up")):
        r = me(client, value)
        assert r.status_code == 503, f"{failure}: {r.status_code} {r.text}"
        assert r.json() == UNAVAILABLE
        assert r.headers["retry-after"] == "60"
    assert users(db) == []

    # What does not need a token still answers.
    assert client.get("/health").status_code == 200
    assert client.get("/stats").status_code == 200


def test_an_unreachable_pool_is_not_hammered(client, pool):
    pool.mode = "error"
    for _ in range(20):
        assert me(client, token()).status_code == 503
    assert pool.requests == 1, "tried once, then left alone for a minute"


def test_it_recovers_when_the_pool_does(client, pool):
    pool.mode = "error"
    assert me(client, token()).status_code == 503
    pool.mode = "ok"
    assert me(client, token()).status_code == 503  # still inside the minute
    pool.expire_cache()
    assert me(client, token()).status_code == 200


@pytest.mark.parametrize("failure", ["error", "garbage", "empty", "down"])
def test_keys_already_held_keep_working(client, pool, failure):
    """The pool's keys change rarely. An hour without Cognito is not an hour
    without sign-in."""
    assert me(client, token()).status_code == 200
    if failure == "down":
        pool.stop()
    else:
        pool.mode = failure
    pool.expire_cache()  # an hour later, the refresh fails

    for _ in range(5):
        assert me(client, token()).status_code == 200
    # Still checked properly against the keys held.
    assert me(client, token(key=STRANGER)).json() == REFUSED
    assert me(client, token(exp=NOW - 60)).json() == REFUSED
    assert me(client, token(kid="made-up")).json() == REFUSED


def test_keys_are_refreshed_after_an_hour(client, pool):
    me(client, token())
    assert pool.requests == 1
    pool.expire_cache()
    me(client, token())
    assert pool.requests == 2
    assert cognito.KEYS_TTL_S == 3600


# --------------------------------------------------------------------------- #
# Keys from a file
# --------------------------------------------------------------------------- #


def test_keys_can_be_read_from_a_file(client, pool, monkeypatch, tmp_path):
    """For a task with no route to the pool. Nothing is fetched at all."""
    path = tmp_path / "jwks.json"
    path.write_text(json.dumps({"keys": [ID_KEY.jwk, ACCESS_KEY.jwk]}))
    monkeypatch.setattr(config, "COGNITO_JWKS_PATH", str(path))
    monkeypatch.setattr(config, "COGNITO_JWKS_URL", "https://unreachable.invalid/jwks.json")
    pool.stop()

    assert me(client, token()).status_code == 200
    assert me(client, token(key=STRANGER)).json() == REFUSED
    assert me(client, token(kid="made-up")).json() == REFUSED
    assert pool.requests == 0


def test_a_file_takes_precedence_over_the_url(client, pool, monkeypatch, tmp_path):
    path = tmp_path / "jwks.json"
    path.write_text(json.dumps({"keys": [ROTATED.jwk]}))
    monkeypatch.setattr(config, "COGNITO_JWKS_PATH", str(path))
    assert me(client, token(key=ROTATED)).status_code == 200
    assert me(client, token(key=ID_KEY)).json() == REFUSED  # only the URL has it
    assert pool.requests == 0


def test_a_replaced_file_is_read_on_the_next_refresh(client, pool, monkeypatch, tmp_path):
    path = tmp_path / "jwks.json"
    path.write_text(json.dumps({"keys": [ID_KEY.jwk]}))
    monkeypatch.setattr(config, "COGNITO_JWKS_PATH", str(path))
    assert me(client, token()).status_code == 200
    path.write_text(json.dumps({"keys": [ROTATED.jwk]}))
    assert me(client, token(key=ROTATED)).status_code == 200  # an unknown kid reads it again


def test_a_file_that_goes_missing(client, pool, monkeypatch, tmp_path):
    path = tmp_path / "jwks.json"
    monkeypatch.setattr(config, "COGNITO_JWKS_PATH", str(path))
    assert me(client, token()).json() == UNAVAILABLE

    path.write_text(json.dumps({"keys": [ID_KEY.jwk]}))
    pool.expire_cache()
    assert me(client, token()).status_code == 200
    path.unlink()
    pool.expire_cache()
    assert me(client, token()).status_code == 200  # the keys held keep working


# --------------------------------------------------------------------------- #
# The routes that change with the mode
# --------------------------------------------------------------------------- #


def test_register_and_login_do_not_exist(client, pool, db):
    body = {"email": "ada@umd.edu", "password": "correct-horse"}
    for path in ("/auth/register", "/auth/login"):
        r = client.post(path, json=body)
        assert r.status_code == 404, path
        assert isinstance(r.json()["detail"], str)
    assert users(db) == []


def test_delete_me_asks_for_no_password(client, pool, db):
    seed([make_row("a")])
    headers = bearer(token())
    assert upload_resume(client, headers).status_code == 200
    onboard(client, headers)
    client.post("/saved/simplify:a", headers=headers)

    assert client.delete("/me", headers=headers).status_code == 204
    assert users(db) == []

    # The token is still the pool's and still valid: deleting here removes
    # what this service holds, not the person's place in the pool. Signing in
    # again starts a new, empty account.
    again = client.get("/me", headers=headers)
    assert again.status_code == 200
    assert again.json()["id"] != 1 and again.json()["onboarded"] is False
    assert client.get("/saved", headers=headers).json()["total"] == 0


def test_delete_me_ignores_a_password_if_one_is_sent(client, pool):
    headers = bearer(token())
    me(client, token())
    r = client.request("DELETE", "/me", json={"password": "whatever"}, headers=headers)
    assert r.status_code == 204


def test_delete_me_still_needs_a_valid_token(client, pool, db):
    me(client, token())
    for bad in (token(exp=NOW - 60), token(key=STRANGER), token(token_use="access")):
        assert client.delete("/me", headers=bearer(bad)).status_code == 401
    assert client.delete("/me").status_code == 401
    assert len(users(db)) == 1


def test_no_pool_configured(client, pool, monkeypatch):
    monkeypatch.setattr(config, "COGNITO_USER_POOL_ID", "")
    monkeypatch.setattr(config, "COGNITO_JWKS_URL", "")
    cognito.forget_keys()
    r = me(client, token())
    assert r.status_code == 503 and r.json() == UNAVAILABLE
    assert cognito.issuers() == ()
