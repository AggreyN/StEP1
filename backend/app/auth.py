"""Authentication — Amazon Cognito (prod) with a local bcrypt fallback (dev).

Two modes, selected by AUTH_MODE:

- **local** (default): /auth/register and /auth/login hash passwords with
  bcrypt into users.password_hash and hand back an HS256 JWT we sign. No AWS.

- **cognito**: the frontend logs in against a Cognito User Pool and sends the
  pool-issued RS256 JWT. We validate it against the pool's public JWKS
  (signature, issuer, audience, expiry) and upsert a users row keyed by `sub`.
  Passwords never touch this service. Built now, untested and unconfigured
  until step 8 of the build order.

`current_user` is the one dependency routes use; it does the right thing for
whichever mode is active.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta

import requests
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.database import get_db
from app.models import User

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
# auto_error=False so we raise our own 401 with the {"detail": str} shape.
_bearer = HTTPBearer(auto_error=False)


# --------------------------------------------------------------------------- #
# Local mode — password hashing + our own JWT
# --------------------------------------------------------------------------- #
def hash_password(plain: str) -> str:
    return _pwd.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd.verify(plain, hashed)


def create_local_token(user: User) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "iat": now,
        "exp": now + timedelta(minutes=config.JWT_EXPIRY_MINUTES),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def _user_from_local_token(token: str, db: Session) -> User:
    try:
        payload = jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token.") from None
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists.")
    return user


# --------------------------------------------------------------------------- #
# Cognito mode — validate the pool's JWT against its JWKS (untested in v1)
# --------------------------------------------------------------------------- #
_jwks_cache: dict = {"keys": None, "fetched_at": 0.0, "miss_refetch_at": None}
_jwks_miss_lock = threading.Lock()
# An unknown kid triggers a JWKS refetch — but anyone can mint tokens with
# bogus kids, so unthrottled that is an unauthenticated make-us-hammer-Cognito
# vector. One miss-refetch per window; a real rotation lands on the first miss.
_JWKS_MISS_COOLDOWN_S = 60.0


def _get_jwks(*, force_refresh: bool = False) -> list[dict]:
    if not config.COGNITO_JWKS_URL:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "AUTH_MODE=cognito but COGNITO_USER_POOL_ID is not configured.",
        )
    stale = _jwks_cache["keys"] is None or (time.monotonic() - _jwks_cache["fetched_at"]) > 3600
    if force_refresh or stale:
        resp = requests.get(config.COGNITO_JWKS_URL, timeout=5)
        resp.raise_for_status()
        _jwks_cache["keys"] = resp.json()["keys"]
        _jwks_cache["fetched_at"] = time.monotonic()
    return _jwks_cache["keys"]


def _key_for(kid: str | None) -> dict | None:
    key = next((k for k in _get_jwks() if k.get("kid") == kid), None)
    if key is not None:
        return key
    with _jwks_miss_lock:
        key = next((k for k in _get_jwks() if k.get("kid") == kid), None)
        if key is not None:
            return key
        last = _jwks_cache["miss_refetch_at"]
        now = time.monotonic()
        if last is not None and now - last < _JWKS_MISS_COOLDOWN_S:
            return None
        keys = _get_jwks(force_refresh=True)
        _jwks_cache["miss_refetch_at"] = now
        return next((k for k in keys if k.get("kid") == kid), None)


def _verify_cognito_token(token: str) -> dict:
    try:
        header = jwt.get_unverified_header(token)
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Malformed token header.") from None
    key = _key_for(header.get("kid"))
    if key is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Signing key not found in JWKS.")
    try:
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=config.COGNITO_APP_CLIENT_ID,
            issuer=config.COGNITO_ISSUER,
        )
    except JWTError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, f"Token validation failed: {exc}"
        ) from None


def _upsert_cognito_user(claims: dict, db: Session) -> User:
    sub = claims["sub"]
    email = (claims.get("email") or f"{sub}@cognito.local").lower()
    user = db.scalar(select(User).where(User.cognito_sub == sub))
    if user is None:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, cognito_sub=sub)
            db.add(user)
        else:
            user.cognito_sub = sub
        db.commit()
    claimed_name = (claims.get("name") or "").strip() or None
    if claimed_name and claimed_name != user.display_name:
        user.display_name = claimed_name
        db.commit()
    return user


# --------------------------------------------------------------------------- #
# The dependency every protected route uses
# --------------------------------------------------------------------------- #
def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Not authenticated.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if config.AUTH_MODE == "cognito":
        return _upsert_cognito_user(_verify_cognito_token(creds.credentials), db)
    return _user_from_local_token(creds.credentials, db)
