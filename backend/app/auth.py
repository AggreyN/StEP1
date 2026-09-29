"""Authentication: Amazon Cognito in production, local passwords in development.

Two modes, selected by AUTH_MODE:

- **local** (default): /auth/register and /auth/login hash passwords with
  bcrypt into users.password_hash and hand back an HS256 JWT we sign. No AWS.

- **cognito**: the frontend signs in against a Cognito user pool and sends
  the pool's ID token. services/cognito.py checks it. Passwords never touch
  this service.

`current_user` is the one dependency routes use; it does the right thing for
whichever mode is active.

In cognito mode a user is known by the token's `sub`, the pool's own
identifier for them, and by nothing else. The first token with a new `sub`
creates a row; every later one finds it by `sub`. An email address is kept to
show and is never used to find anyone: it is an attribute a user can change,
and one that two different sign-ins can both claim.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import config, limits
from app.database import get_db
from app.models import User
from app.services import cognito

log = logging.getLogger(__name__)

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=config.BCRYPT_ROUNDS)
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
        # `algorithms` is a list of one, and it is ours. A token that names
        # another algorithm in its own header ("none", or RS256 with our
        # secret as the public key) is refused for that alone.
        payload = jwt.decode(
            token,
            config.JWT_SECRET,
            algorithms=[config.JWT_ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token.") from None
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists.")
    return user


# --------------------------------------------------------------------------- #
# Cognito mode
# --------------------------------------------------------------------------- #
def _claims(token: str) -> dict:
    try:
        return cognito.verify(token)
    except cognito.InvalidToken as exc:
        # Why, for whoever reads the log. Not for whoever sent the token: to
        # someone forging one, the reason is the next thing to fix.
        log.info("cognito: token refused: %s", exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token.") from None
    except cognito.KeysUnavailable:
        # Not 401: the token may be perfectly good. Not 500: nothing is
        # broken here. And never a pass.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Sign-in can't be checked right now. Try again in a minute.",
            headers={"Retry-After": "60"},
        ) from None


def _email_from(claims: dict) -> str:
    email = claims.get("email")
    if isinstance(email, str) and 3 <= len(email) <= limits.EMAIL_MAX and "@" in email:
        return email.strip().lower()
    # A pool can be set up without email. The column is required and unique,
    # and the sub is both.
    return f"{claims['sub']}@users.cognito.invalid"


def _name_from(claims: dict) -> str | None:
    name = claims.get("name")
    if not isinstance(name, str):
        return None
    return " ".join(name.split())[: limits.DISPLAY_NAME_MAX] or None


_TAKEN = (
    "An account with that email address already exists and is not linked to this "
    "sign-in. Ask for the two to be linked."
)


def _user_for(claims: dict, db: Session) -> User:
    """The user this token belongs to, created if this is their first."""
    sub = claims["sub"]
    email, name = _email_from(claims), _name_from(claims)

    user = db.scalar(select(User).where(User.cognito_sub == sub))
    if user is None:
        # Never looked up by email. A row with this address and a different
        # sub, or none, is a different account: someone who registered with
        # a password, or another identity claiming the same address. Handing
        # it to whoever arrives with a matching email would be handing over
        # the account.
        if db.scalar(select(User.id).where(User.email == email)) is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, _TAKEN)
        user = User(email=email, cognito_sub=sub, display_name=name)
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            # Two first requests at once, as a page fires several. One
            # created the row; this one finds it.
            db.rollback()
            user = db.scalar(select(User).where(User.cognito_sub == sub))
            if user is None:
                raise HTTPException(status.HTTP_409_CONFLICT, _TAKEN) from None
        return user

    # Known. The pool owns the name and the address; mirror a change, unless
    # the new address is already someone else's.
    changed = False
    if name and name != user.display_name:
        user.display_name, changed = name, True
    if email != user.email:
        if db.scalar(select(User.id).where(User.email == email, User.id != user.id)) is None:
            user.email, changed = email, True
    if changed:
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
        return _user_for(_claims(creds.credentials), db)
    return _user_from_local_token(creds.credentials, db)
