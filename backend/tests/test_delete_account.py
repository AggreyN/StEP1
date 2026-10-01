"""DELETE /me: the account, and everything that was ever stored about it."""

from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from app import config
from app.database import Base, SessionLocal, engine
from app.ratelimit import limiter
from app.services import feed_state
from tests.conftest import (
    base_resume,
    make_pdf,
    make_row,
    onboard,
    presign,
    put_upload,
    register,
    resume_doc,
    seed,
    upload_resume,
)

PASSWORD = "correct-horse"


def delete_me(client, headers, password=PASSWORD, **body):
    payload = ({"password": password} if password is not None else {}) | body
    return client.request("DELETE", "/me", json=payload, headers=headers)


# Every table with rows that belong to a user, and how to find one user's.
OWNED = {
    "users": "id = :u",
    "profiles": "user_id = :u",
    "profile_interests": "user_id = :u",
    "resume_uploads": "user_id = :u",
    "match_scores": "user_id = :u",
    "saved_postings": "user_id = :u",
    "applications": "user_id = :u",
    "application_events": "application_id IN (SELECT id FROM applications WHERE user_id = :u)",
    "contacts": "user_id = :u",
    "outreach_messages": "application_id IN (SELECT id FROM applications WHERE user_id = :u)",
    "integrations": "user_id = :u",
    "reviews": "user_id = :u",
    "base_resumes": "user_id = :u",
    "tailored_resumes": "user_id = :u",
}
SHARED = {"postings", "companies", "ingest_runs"}


def rows(user_id: int) -> dict[str, int]:
    with SessionLocal() as db:
        return {
            table: db.execute(
                text(f"SELECT count(*) FROM {table} WHERE {mine}"), {"u": user_id}
            ).scalar()
            for table, mine in OWNED.items()
        }


def snapshot(user_id: int) -> dict:
    with SessionLocal() as db:
        return {
            table: sorted(
                repr(sorted(dict(r).items()))
                for r in db.execute(
                    text(f"SELECT * FROM {table} WHERE {mine}"), {"u": user_id}
                ).mappings()
            )
            for table, mine in OWNED.items()
        }


def someone_with_everything(client, email: str) -> tuple[dict, int, list[Path]]:
    """An account with a row in every table that can hold one, a committed
    resume, and a second upload in progress."""
    headers = register(client, email=email)
    assert upload_resume(client, headers, make_pdf(), "resume.pdf").status_code == 200
    onboard(client, headers)
    client.post("/saved/simplify:a", headers=headers)
    app_id = client.post(
        "/applications", json={"posting_id": "simplify:b"}, headers=headers
    ).json()["id"]
    client.post(
        f"/applications/{app_id}/events", json={"kind": "note", "note": "mine"}, headers=headers
    )
    pending = presign(client, headers, len(make_pdf()))
    assert put_upload(client, headers, pending, make_pdf()).status_code == 204
    reviewed = client.post(
        "/reviews", json={"rating": 5, "body": f"{email} likes it"}, headers=headers
    )
    assert reviewed.status_code == 201, reviewed.text
    assert client.put("/resume/base", json=base_resume(), headers=headers).status_code == 200
    saved = client.post(
        "/resumes",
        json={"name": "For Acme", "doc": resume_doc(), "posting_id": "simplify:a"},
        headers=headers,
    )
    assert saved.status_code == 201, saved.text

    with SessionLocal() as db:
        user_id = db.execute(text("SELECT id FROM users WHERE email = :e"), {"e": email}).scalar()
        # No route writes these three yet. Deleting an account must already
        # remove them, so that it still does on the day one does.
        contact = db.execute(
            text(
                "INSERT INTO contacts (user_id, application_id, name, email) "
                "VALUES (:u, :a, 'A Recruiter', 'recruiter@example.com') RETURNING id"
            ),
            {"u": user_id, "a": app_id},
        ).scalar()
        db.execute(
            text(
                "INSERT INTO outreach_messages (application_id, contact_id, channel, body, status) "
                "VALUES (:a, :c, 'email', 'Hello', 'draft')"
            ),
            {"a": app_id, "c": contact},
        )
        db.execute(
            text(
                "INSERT INTO integrations (user_id, provider, external_id) "
                "VALUES (:u, 'github', 'octocat')"
            ),
            {"u": user_id},
        )
        db.commit()
        key = db.execute(
            text("SELECT resume_s3_key FROM profiles WHERE user_id = :u"), {"u": user_id}
        ).scalar()
    files = [Path(config.UPLOAD_DIR) / key, Path(config.UPLOAD_DIR) / pending["key"]]
    assert all(f.exists() for f in files)
    return headers, user_id, files


@pytest.fixture()
def board():
    seed([make_row("a", company="Acme"), make_row("b", company="Globex")])


def test_every_table_is_accounted_for():
    """A table added later must be listed here as owned or shared. If it is
    owned, the test below proves deleting an account empties it."""
    assert set(Base.metadata.tables) == set(OWNED) | SHARED
    # And every owned table is reachable from users by cascading deletes.
    inspector = inspect(engine)
    for table in set(OWNED) - {"users"}:
        cascades = [
            fk for fk in inspector.get_foreign_keys(table)
            if fk["options"].get("ondelete") == "CASCADE"
            and fk["referred_table"] in ("users", "profiles", "applications")
        ]  # fmt: skip
        assert cascades, f"{table} has no cascading foreign key back to its owner"


def test_deletes_everything_and_only_that(client, board):
    me, my_id, my_files = someone_with_everything(client, "me@example.com")
    other, their_id, their_files = someone_with_everything(client, "other@example.com")

    mine_before = rows(my_id)
    assert all(count >= 1 for count in mine_before.values()), mine_before
    theirs_before = snapshot(their_id)
    shared_before = {t: _count(t) for t in SHARED}
    feed_state.begin(my_id)  # as if a build were in flight

    r = delete_me(client, me)
    assert r.status_code == 204 and r.content == b""

    assert rows(my_id) == dict.fromkeys(OWNED, 0)
    assert not any(f.exists() for f in my_files)
    assert my_id not in feed_state._progress

    # The other account: every row identical, both files still there, and
    # everything still works for them.
    assert snapshot(their_id) == theirs_before
    assert all(f.exists() for f in their_files)
    assert client.get("/profile", headers=other).json()["resume"]["filename"] == "resume.pdf"
    assert client.get("/saved", headers=other).json()["total"] == 1
    assert len(client.get("/applications", headers=other).json()["items"]) == 1
    assert client.get("/feed", headers=other).json()["total"] == 2
    # The board is nobody's, and is as it was.
    assert {t: _count(t) for t in SHARED} == shared_before


def _count(table: str) -> int:
    with SessionLocal() as db:
        return db.execute(text(f"SELECT count(*) FROM {table}")).scalar()


def test_the_token_stops_working(client, board):
    me, _, _ = someone_with_everything(client, "me@example.com")
    assert delete_me(client, me).status_code == 204
    for method, path in [
        ("GET", "/me"), ("GET", "/profile"), ("GET", "/feed"), ("GET", "/saved"),
        ("GET", "/applications"), ("POST", "/saved/simplify:a"), ("DELETE", "/me"),
    ]:  # fmt: skip
        r = client.request(method, path, headers=me, json={"password": PASSWORD})
        assert r.status_code == 401, f"{method} {path}"
        assert r.json() == {"detail": "User no longer exists."}
    login = client.post("/auth/login", json={"email": "me@example.com", "password": PASSWORD})
    assert login.status_code == 401


def test_the_email_can_register_again_and_starts_empty(client, board):
    me, old_id, _ = someone_with_everything(client, "me@example.com")
    delete_me(client, me)

    again = client.post(
        "/auth/register", json={"email": "me@example.com", "password": "a-new-password"}
    )
    assert again.status_code == 200
    assert again.json()["user"]["id"] != old_id  # ids are never reused
    fresh = {"Authorization": f"Bearer {again.json()['access_token']}"}
    assert client.get("/me", headers=fresh).json()["onboarded"] is False
    assert client.get("/profile", headers=fresh).status_code == 404
    assert client.get("/saved", headers=fresh).json()["total"] == 0
    assert client.get("/applications", headers=fresh).json() == {"items": []}
    # The old token is for the old account, which still does not exist.
    assert client.get("/me", headers=me).status_code == 401


def test_the_wrong_password_deletes_nothing(client, board):
    me, my_id, my_files = someone_with_everything(client, "me@example.com")
    before = snapshot(my_id)
    for wrong in ("not-the-password", "correct-horse ", "Correct-Horse", "x"):
        r = delete_me(client, me, password=wrong)
        assert r.status_code == 403
        assert r.json() == {"detail": "Password is incorrect."}
    assert snapshot(my_id) == before and all(f.exists() for f in my_files)
    assert client.get("/me", headers=me).status_code == 200


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ({}, "password: Field required"),
        ({"password": ""}, "password: Field required"),
        ({"password": None}, "password: Field required"),
        ({"password": "p" * 129}, "password: must be at least"),
        ({"password": PASSWORD, "user_id": 2}, "user_id: this field can't be set"),
        ({"password": PASSWORD, "email": "other@example.com"}, "email: this field can't be set"),
    ],
)
def test_a_malformed_request_deletes_nothing(client, board, payload, detail):
    me, my_id, _ = someone_with_everything(client, "me@example.com")
    r = client.request("DELETE", "/me", json=payload, headers=me)
    assert r.status_code == 422
    if "at least" in detail:
        assert r.json() == {"detail": "password: must be at most 128 characters"}
    else:
        assert r.json() == {"detail": detail}
    assert rows(my_id)["users"] == 1


def test_no_body_at_all_is_a_422(client, auth):
    r = client.delete("/me", headers=auth)
    assert r.status_code == 422 and r.json() == {"detail": "password: Field required"}
    assert client.get("/me", headers=auth).status_code == 200


def test_needs_a_token(client, auth):
    assert client.request("DELETE", "/me", json={"password": PASSWORD}).status_code == 401
    assert client.get("/me", headers=auth).status_code == 200


def test_an_account_with_nothing_can_be_deleted(client):
    headers = register(client, email="empty@example.com")
    assert delete_me(client, headers).status_code == 204
    assert client.get("/me", headers=headers).status_code == 401


def test_a_resume_stored_under_an_old_key_is_deleted_too(client, board):
    me, my_id, files = someone_with_everything(client, "me@example.com")
    old = Path(config.UPLOAD_DIR) / f"resumes/{my_id}/0123456789ab-My_Resume.pdf"
    files[0].rename(old)
    with SessionLocal() as db:
        db.execute(
            text("UPDATE profiles SET resume_s3_key = :k WHERE user_id = :u"),
            {"k": f"resumes/{my_id}/0123456789ab-My_Resume.pdf", "u": my_id},
        )
        db.commit()
    assert delete_me(client, me).status_code == 204
    assert not old.exists() and not files[1].exists()


def test_files_that_cannot_be_removed_do_not_bring_the_account_back(client, board, monkeypatch):
    """The rows are gone and committed before storage is touched. If storage
    then fails, the account is still deleted; the failure is logged."""
    from app.services import storage

    me, my_id, _ = someone_with_everything(client, "me@example.com")
    monkeypatch.setattr(storage, "delete", lambda key: False)
    assert delete_me(client, me).status_code == 204
    assert rows(my_id) == dict.fromkeys(OWNED, 0)


def test_in_cognito_mode_no_password_is_asked_for(client, board, monkeypatch):
    me, my_id, my_files = someone_with_everything(client, "me@example.com")
    monkeypatch.setattr(config, "AUTH_MODE", "cognito")
    # The token is a local one, so it no longer validates; stand in for a
    # caller the pool has already authenticated.
    from app.deps import current_user
    from app.main import app
    from app.models import User

    def authenticated():
        with SessionLocal() as db:
            return db.get(User, my_id)

    app.dependency_overrides[current_user] = authenticated
    try:
        r = client.delete("/me")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 204
    assert rows(my_id) == dict.fromkeys(OWNED, 0) and not any(f.exists() for f in my_files)


@pytest.fixture()
def limits_on(monkeypatch):
    limiter.reset()
    monkeypatch.setattr(limiter, "enabled", True)
    yield
    limiter.reset()


def test_is_rate_limited(client, limits_on):
    """Five guesses at the password an hour, and then not even the right
    one: the limit is on attempts."""
    assert config.DELETE_ACCOUNT_RATE_LIMIT == "5/hour"
    me = register(client, email="me@example.com")
    limiter.reset()
    for _ in range(5):
        assert delete_me(client, me, password="a-wrong-guess").status_code == 403
    r = delete_me(client, me)
    assert r.status_code == 429
    assert r.json() == {
        "detail": "Too many attempts to delete an account. Try again in about an hour."
    }
    assert 3000 <= int(r.headers["retry-after"]) <= 3600
    assert client.get("/me", headers=me).status_code == 200
