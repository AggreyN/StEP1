"""Local-mode auth: register, login, /me.

Only mounted when AUTH_MODE=local. In cognito mode the pool owns registration
and login, and /me is served from the validated Cognito token instead.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.auth import create_local_token, hash_password, verify_password
from app.deps import current_user, get_db
from app.models import Profile, User
from app.ratelimit import limiter, login_limit, register_limit
from app.schemas import LoginIn, MeOut, RegisterIn, TokenOut, UserOut

router = APIRouter(tags=["auth"])


def _token_response(user: User) -> TokenOut:
    return TokenOut(access_token=create_local_token(user), user=UserOut.model_validate(user))


# A hash of nothing in particular, for the sign-in that names no account.
# Checking a password against it takes as long as checking one against a
# real hash, so how long a refusal takes does not say whether the email
# belongs to anyone.
_NO_ACCOUNT = hash_password("there is no account with this password")


@router.post("/auth/register", response_model=TokenOut)
@limiter.limit(register_limit, error_message="Too many accounts created from here.")
def register(request: Request, body: RegisterIn, db: Session = Depends(get_db)):
    if config.AUTH_MODE != "local":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Registration is handled by Cognito.")
    email = body.email.lower()
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with that email already exists.")
    user = User(
        email=email, password_hash=hash_password(body.password), display_name=body.display_name
    )
    db.add(user)
    db.commit()
    return _token_response(user)


@router.post("/auth/login", response_model=TokenOut)
@limiter.limit(login_limit, error_message="Too many sign-in attempts.")
def login(request: Request, body: LoginIn, db: Session = Depends(get_db)):
    if config.AUTH_MODE != "local":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Login is handled by Cognito.")
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    # One message for both "no such user" and "wrong password", so the login
    # form can't be used to enumerate accounts.
    known = user is not None and bool(user.password_hash)
    matches = verify_password(body.password, user.password_hash if known else _NO_ACCOUNT)
    if not (known and matches):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")
    return _token_response(user)


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    onboarded_at = db.scalar(select(Profile.onboarded_at).where(Profile.user_id == user.id))
    return MeOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        onboarded=onboarded_at is not None,
    )
