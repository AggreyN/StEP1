"""Checking a token issued by an Amazon Cognito user pool.

In cognito mode this service holds no passwords and signs nothing. The pool
signs a token with its private key; this module checks the signature with the
pool's public keys, and then checks that the token is what it has to be: from
this pool, for this app, an ID token, within its time.

What is checked, and why each matters on its own:

    signature    RS256, against the pool's key with the token's `kid`. The
                 algorithm is ours to choose, never the token's: a token that
                 says `none`, or says HS256 and is signed with the public
                 key, is refused for saying so.
    iss          This pool. Any pool in any account can sign a token.
    aud          This app client. Another app in the same pool is someone
                 else's users.
    token_use    `id`. The access token has no email and no `aud`; accepting
                 either kind would mean checking neither properly.
    exp, nbf     Now.

The public keys are fetched from the pool over https, or read from a file
(COGNITO_JWKS_PATH) by a task that cannot reach it. They are cached. If a
refresh fails, the keys already held go on being used: a pool's keys change
rarely, and an hour without Cognito must not be an hour without sign-in. With
no keys at all the answer is 503. Never a pass, and never a 500.
"""

from __future__ import annotations

import json
import logging
import threading
import time

import jwt
import requests

from app import config

log = logging.getLogger(__name__)

ALGORITHM = "RS256"
# Seconds a token's times may be off by. The pool's clock and this task's
# agree to well within it; without it, a token used in the same second it
# was issued can be refused as not yet valid.
LEEWAY_S = 5
# How long fetched keys are used before they are fetched again.
KEYS_TTL_S = 3600.0
# After a failed refresh, how long before the next attempt. The keys held go
# on being used meanwhile; this is only how hard an unreachable pool is tried.
RETRY_AFTER_FAILURE_S = 60.0
# A token with a `kid` we have not seen may mean the pool has rotated its
# keys, so the keys are fetched again. But anyone can send a token with a
# made-up `kid`, and each would cost a request to Cognito. One such fetch per
# window; a real rotation is picked up by the first.
UNKNOWN_KID_COOLDOWN_S = 60.0


class InvalidToken(Exception):
    """The token is not acceptable. The reason is for the log, not the caller."""


class KeysUnavailable(Exception):
    """There are no keys to check a token with, and none could be fetched."""


_lock = threading.Lock()
_state: dict = {"keys": None, "next_refresh": 0.0, "next_unknown_kid_fetch": 0.0}


def forget_keys() -> None:
    """Drop the cache. For tests, and for a pool that has been replaced."""
    with _lock:
        _state.update(keys=None, next_refresh=0.0, next_unknown_kid_fetch=0.0)


def issuers() -> tuple[str, ...]:
    """The values this pool may put in `iss`. A pool uses the first unless it
    has been switched to the newer form, which differs only in the host name."""
    pool, region = config.COGNITO_USER_POOL_ID, config.AWS_REGION
    if not pool:
        return ()
    return (
        f"https://cognito-idp.{region}.amazonaws.com/{pool}",
        f"https://issuer-cognito-idp.{region}.amazonaws.com/{pool}",
    )


def _read_keys() -> dict[str, dict]:
    """The pool's public keys, by `kid`. Raises on any failure."""
    if config.COGNITO_JWKS_PATH:
        with open(config.COGNITO_JWKS_PATH, encoding="utf-8") as f:
            document = json.load(f)
    else:
        if not config.COGNITO_JWKS_URL:
            raise ValueError("no COGNITO_USER_POOL_ID, so no keys URL")
        response = requests.get(config.COGNITO_JWKS_URL, timeout=config.COGNITO_JWKS_TIMEOUT_S)
        response.raise_for_status()
        document = response.json()
    keys = {
        key["kid"]: key
        for key in document["keys"]
        if isinstance(key, dict) and key.get("kid") and key.get("kty") == "RSA"
    }
    if not keys:
        raise ValueError("the key set holds no RSA keys")
    return keys


def _keys(*, refresh: bool = False) -> dict[str, dict]:
    """Call with the lock held."""
    now = time.monotonic()
    if not refresh and now < _state["next_refresh"]:
        # Too soon to fetch again, whether the last fetch worked or not.
        # With nothing held, that means a minute of 503s rather than a
        # request to the pool for every request to us.
        if _state["keys"] is None:
            raise KeysUnavailable
        return _state["keys"]
    try:
        _state["keys"] = _read_keys()
        _state["next_refresh"] = now + KEYS_TTL_S
    except Exception as exc:  # noqa: BLE001 — network, HTTP status, JSON, shape
        _state["next_refresh"] = now + RETRY_AFTER_FAILURE_S
        if _state["keys"] is None:
            log.error("cognito: no signing keys, and they could not be fetched: %s",
                      type(exc).__name__)  # fmt: skip
            raise KeysUnavailable from exc
        log.warning("cognito: signing keys could not be refreshed; using the ones held: %s",
                    type(exc).__name__)  # fmt: skip
    return _state["keys"]


def _key_for(kid: str) -> dict | None:
    with _lock:
        key = _keys().get(kid)
        if key is not None:
            return key
        now = time.monotonic()
        if now < _state["next_unknown_kid_fetch"]:
            return None
        _state["next_unknown_kid_fetch"] = now + UNKNOWN_KID_COOLDOWN_S
        return _keys(refresh=True).get(kid)


def verify(token: str) -> dict:
    """The token's claims, if it is a valid ID token from this pool for this
    app. Raises InvalidToken if it is not, KeysUnavailable if that cannot be
    decided."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        raise InvalidToken("unreadable header") from exc
    # Before any key is looked up. What algorithm to trust is decided here,
    # not by the token.
    if header.get("alg") != ALGORITHM:
        raise InvalidToken(f"algorithm is {header.get('alg')!r}")
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise InvalidToken("no kid")

    key = _key_for(kid)
    if key is None:
        raise InvalidToken("unknown kid")

    try:
        claims = jwt.decode(
            token,
            jwt.PyJWK(key, algorithm=ALGORITHM).key,
            algorithms=[ALGORITHM],
            audience=config.COGNITO_APP_CLIENT_ID,
            issuer=list(issuers()),
            leeway=LEEWAY_S,
            options={"require": ["exp", "iat", "sub", "iss", "aud", "token_use"]},
        )
    except (jwt.InvalidTokenError, jwt.PyJWKError) as exc:
        raise InvalidToken(type(exc).__name__) from exc

    if claims.get("token_use") != "id":
        raise InvalidToken(f"token_use is {claims.get('token_use')!r}")
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise InvalidToken("sub is not a string")
    return claims
