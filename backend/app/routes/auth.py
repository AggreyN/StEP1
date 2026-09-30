"""Accounts: register, sign in, /me, and deleting an account.

Register and sign-in are for AUTH_MODE=local. In cognito mode the pool owns
both, and they answer 404 here.
"""

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import config
from app.auth import create_local_token, hash_password, is_admin, verify_password
from app.deps import current_user, get_db
from app.models import Profile, ResumeUpload, User
from app.ratelimit import delete_account_limit, limiter, login_limit, register_limit
from app.schemas import DeleteAccountIn, LoginIn, MeOut, RegisterIn, TokenOut, UserOut
from app.services import cognito, feed_state, storage

router = APIRouter(tags=["auth"])
log = logging.getLogger(__name__)


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
def me(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    onboarded_at = db.scalar(select(Profile.onboarded_at).where(Profile.user_id == user.id))
    return MeOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        onboarded=onboarded_at is not None,
        # For the frontend to show the admin link. The admin routes check
        # for themselves; this grants nothing.
        is_admin=is_admin(request),
    )


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
@limiter.limit(delete_account_limit, error_message="Too many attempts to delete an account.")
def delete_me(
    request: Request,
    body: DeleteAccountIn | None = Body(default=None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Delete the caller's account and everything that belongs to it.

    Everything: the profile and its ranked interests, the resume and its
    extracted text, cached scores, saved postings, applications and their
    whole history, contacts, drafted messages, connected integrations, and
    any upload in progress. Nothing is kept, anonymised or soft-deleted.
    """
    if config.AUTH_MODE == "local":
        if body is None or not body.password:
            raise HTTPException(422, "password: Field required")
        if not user.password_hash or not verify_password(body.password, user.password_hash):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Password is incorrect.")
    # In cognito mode the pool holds the password and has already checked it
    # to issue the token. The person is removed from the pool too, below,
    # once everything this service holds is gone.

    user_id = user.id
    sub = user.cognito_sub
    # Found before the rows that say where they are have gone.
    keys = set(db.scalars(select(ResumeUpload.key).where(ResumeUpload.user_id == user_id)))
    resume = db.scalar(select(Profile.resume_s3_key).where(Profile.user_id == user_id))
    if resume:
        keys.add(resume)

    # One statement, one transaction. Every table that holds a user's rows
    # references users with ON DELETE CASCADE, directly or through a parent,
    # so the database removes all of them or none. A test inserts a row into
    # each and checks; a table added without the cascade fails it.
    db.execute(delete(User).where(User.id == user_id))
    db.commit()

    # Files after rows. If the process dies in between, what is left is an
    # object no row points to, under a key nobody holds, which is recoverable;
    # the other order could leave an account pointing at a resume that is gone.
    failed = [key for key in keys if not storage.delete(key)]
    if failed:
        log.error(
            "account deleted but stored files could not be removed",
            extra={"user_id": user_id, "objects": len(failed)},
        )
    feed_state.forget(user_id)

    # Last, like the files: a failure here leaves a sign-in with nothing
    # behind it, which an operator can remove, never data without an owner.
    if config.AUTH_MODE == "cognito" and sub and not cognito.remove_from_pool(sub):
        log.error("account deleted but the pool still has the user", extra={"user_id": user_id})
    log.info("account deleted", extra={"user_id": user_id, "objects": len(keys)})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
