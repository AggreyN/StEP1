"""Responses carry what the contract says and nothing else.

Every JSON route declares a response model, so what leaves is what the model
lists, whatever the handler happened to return. The models themselves are
checked for fields that must never leave, and then a whole session's worth of
real responses is searched for the values.
"""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy import text

from app.database import Base, SessionLocal
from app.main import app
from tests.conftest import (
    api_routes,
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

ROUTES = api_routes(app)

# Column names that exist in the database and must not exist in any response.
NEVER = {
    "password_hash", "password", "cognito_sub", "resume_text", "resume_s3_key",
    "token_secret_arn", "user_id", "raw", "content_hash", "search_tsv", "scores_version",
    "company_id", "posting_id", "application_id",
}  # fmt: skip
# The one place a storage key is returned: to its owner, who needs it to
# finish the upload they just started.
KEY_ALLOWED_IN = {("POST", "/profile/resume/presign")}
# Routes whose body is a file, not JSON. Each is listed on purpose.
FILE_ROUTES = {
    ("GET", "/admin/resume-files/{token}"),
    ("GET", "/resumes/{resume_id}/download"),
    ("GET", "/admin/users/{user_id}/resumes/{resume_id}/download"),
}
# The one route whose job is to hand a person's own resume text back to
# them, as a structured draft for them to review.
OWN_TEXT_ALLOWED_IN = {("POST", "/resume/base/extract")}


def _fields(model, seen=None) -> dict[str, set[str]]:
    """{model name: field names}, for a model and every model inside it."""
    seen = {} if seen is None else seen
    stack = [model]
    while stack:
        t = stack.pop()
        if isinstance(t, type) and issubclass(t, BaseModel):
            if t.__name__ in seen:
                continue
            seen[t.__name__] = set(t.model_fields)
            stack.extend(f.annotation for f in t.model_fields.values())
        stack.extend(getattr(t, "__args__", ()))
    return seen


def test_the_walk_found_the_routes():
    assert len(ROUTES) >= 20 and ("GET", "/feed") in ROUTES


def test_every_route_declares_what_it_returns():
    """A response model, or an explicit 204 with no body. A route with
    neither returns whatever its handler returns, and the day that is an ORM
    object, every column of it is in the response."""
    undeclared = []
    for (method, path), route in sorted(ROUTES.items()):
        if route.response_model is None and route.status_code != 204:
            # A file download: the body is the file, sent as an attachment.
            if getattr(route.response_class, "__name__", "") in ("FileResponse", "Response") and (
                (method, path) in FILE_ROUTES
            ):
                continue
            undeclared.append(f"{method} {path}")
    assert undeclared == [], (
        f"Give these a response_model=, or status_code=204 if they return nothing: {undeclared}"
    )


def test_no_response_model_is_a_database_row():
    tables = {m.class_.__name__ for m in Base.registry.mappers}
    assert {"User", "Profile", "Application"} <= tables
    for (method, path), route in ROUTES.items():
        if route.response_model is None:
            continue
        for name in _fields(route.response_model):
            assert name not in tables, f"{method} {path} returns the {name} row itself"
        assert not issubclass_safe(route.response_model, Base), f"{method} {path}"


def issubclass_safe(candidate, parent) -> bool:
    return isinstance(candidate, type) and issubclass(candidate, parent)


def test_no_response_model_has_a_field_that_must_not_leave():
    checked = set()
    for (method, path), route in ROUTES.items():
        if route.response_model is None:
            continue
        for name, fields in _fields(route.response_model).items():
            checked.add(name)
            leaked = fields & NEVER
            assert not leaked, f"{method} {path}: {name} exposes {sorted(leaked)}"
            if (method, path) not in KEY_ALLOWED_IN:
                assert "key" not in fields, f"{method} {path}: {name} exposes a storage key"
    assert {"PostingOut", "ProfileOut", "ResumeOut", "UserOut", "ApplicationDetailOut"} <= checked


def _walk(value, path=""):
    """Every (path, key, value) in a JSON document."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield path, k, v
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(value, list):
        for n, v in enumerate(value):
            yield from _walk(v, f"{path}[{n}]")


def test_a_whole_session_leaks_nothing(client, monkeypatch):
    """Every route, called for real by a user who has one of everything,
    beside another user who also does. Then every response is searched."""
    seed([make_row("a", company="Acme"), make_row("b", company="Globex")])
    me = register(client, email="me@example.com", password="my-own-password", name="Me")
    other = register(client, email="other@example.com", password="their-password", name="Them")
    for who, school in ((me, "My School"), (other, "Their Secret School")):
        upload_resume(client, who, make_pdf(extra=f" {school} thesis"))
        onboard(client, who, school=school)
        client.post("/saved/simplify:a", headers=who)
    theirs = client.post("/applications", json={"posting_id": "simplify:b"}, headers=other).json()
    client.post(
        f"/applications/{theirs['id']}/events",
        json={"kind": "note", "note": "their private note"},
        headers=other,
    )
    mine = client.post("/applications", json={"posting_id": "simplify:b"}, headers=me).json()

    with SessionLocal() as db:
        rows = db.execute(
            text(
                "SELECT u.email, u.password_hash, p.resume_s3_key, p.resume_text "
                "FROM users u JOIN profiles p ON p.user_id = u.id ORDER BY u.id"
            )
        ).all()
    (my_email, my_hash, my_key, my_text), (_, their_hash, their_key, their_text) = rows

    # "me" is the admin here, so that the admin route is called for real. Only
    # "me" has written a review: the other user's email must still not appear.
    from app import config

    monkeypatch.setattr(config, "ADMIN_EMAILS", frozenset({"me@example.com"}))
    with SessionLocal() as db:
        my_id = db.execute(text("SELECT id FROM users WHERE email = 'me@example.com'")).scalar()
    slot = presign(client, me, len(make_pdf()))
    calls = {
        ("GET", "/health"): client.get("/health"),
        ("POST", "/auth/register"): client.post(
            "/auth/register", json={"email": "third@example.com", "password": "third-password"}
        ),
        ("POST", "/auth/login"): client.post(
            "/auth/login", json={"email": my_email, "password": "my-own-password"}
        ),
        ("GET", "/me"): client.get("/me", headers=me),
        ("GET", "/profile"): client.get("/profile", headers=me),
        ("PUT", "/profile"): client.put(
            "/profile", json=onboard(client, me, school="My School"), headers=me
        ),
        ("POST", "/profile/resume/presign"): client.post(
            "/profile/resume/presign",
            json={"filename": "r.pdf", "content_type": "application/pdf", "size": 4096},
            headers=me,
        ),
        ("PUT", "/profile/resume/local/{key:path}"): put_upload(
            client, me, presign(client, me, len(make_pdf())), make_pdf()
        ),
        ("POST", "/profile/resume/commit"): upload_resume(client, me),
        ("GET", "/feed"): client.get("/feed?page_size=100", headers=me),
        ("GET", "/feed/status"): client.get("/feed/status", headers=me),
        ("GET", "/postings/{posting_id}"): client.get("/postings/simplify:b", headers=me),
        ("GET", "/saved"): client.get("/saved", headers=me),
        ("POST", "/saved/{posting_id}"): client.post("/saved/simplify:b", headers=me),
        ("DELETE", "/saved/{posting_id}"): client.delete("/saved/simplify:b", headers=me),
        ("GET", "/applications"): client.get("/applications", headers=me),
        ("POST", "/applications"): client.post(
            "/applications", json={"posting_id": "simplify:a"}, headers=me
        ),
        ("GET", "/applications/{application_id}"): client.get(
            f"/applications/{mine['id']}", headers=me
        ),
        ("POST", "/applications/{application_id}/events"): client.post(
            f"/applications/{mine['id']}/events", json={"kind": "acknowledged"}, headers=me
        ),
        ("GET", "/ingest/status"): client.get("/ingest/status", headers=me),
        ("GET", "/stats"): client.get("/stats"),
        ("POST", "/reviews"): client.post(
            "/reviews", json={"rating": 5, "body": "Useful."}, headers=me
        ),
        ("GET", "/admin/reviews"): client.get("/admin/reviews", headers=me),
        # The admin's views of a person, pointed at "me": the other user's
        # details are what the admin pages exist to show, and are tested there.
        ("POST", "/resume/base/extract"): client.post("/resume/base/extract", headers=me),
        ("PUT", "/resume/base"): client.put("/resume/base", json=base_resume(), headers=me),
        ("GET", "/resume/base"): client.get("/resume/base", headers=me),
        ("POST", "/tailor"): client.post("/tailor", json={"posting_id": "simplify:a"}, headers=me),
        ("POST", "/resumes"): (
            saved_resume := client.post(
                "/resumes",
                json={"name": "Mine", "doc": resume_doc(), "posting_id": "simplify:a"},
                headers=me,
            )
        ),
        ("GET", "/resumes"): client.get("/resumes", headers=me),
        ("GET", "/resumes/{resume_id}"): client.get(
            f"/resumes/{saved_resume.json()['id']}", headers=me
        ),
        ("PUT", "/resumes/{resume_id}"): client.put(
            f"/resumes/{saved_resume.json()['id']}", json={"name": "Mine, renamed"}, headers=me
        ),
        ("GET", "/admin/users/{user_id}/resumes/{resume_id}"): client.get(
            f"/admin/users/{my_id}/resumes/{saved_resume.json()['id']}", headers=me
        ),
        ("GET", "/admin/users/{user_id}/resumes/{resume_id}/download"): client.get(
            f"/admin/users/{my_id}/resumes/{saved_resume.json()['id']}/download", headers=me
        ),
        ("GET", "/resumes/{resume_id}/download"): client.get(
            f"/resumes/{saved_resume.json()['id']}/download?format=docx", headers=me
        ),
        ("DELETE", "/resumes/{resume_id}"): client.delete(
            f"/resumes/{saved_resume.json()['id']}", headers=me
        ),
        ("GET", "/admin/users"): client.get("/admin/users?q=me@example", headers=me),
        ("GET", "/admin/users/{user_id}"): client.get(f"/admin/users/{my_id}", headers=me),
        ("GET", "/admin/users/{user_id}/resume-file"): (
            link := client.get(f"/admin/users/{my_id}/resume-file", headers=me)
        ),
        ("GET", "/admin/resume-files/{token}"): client.get(
            link.json()["url"].removeprefix("http://testserver")
        ),
        # Last: after this there is no "me" to make the other calls as.
        ("DELETE", "/me"): client.request(
            "DELETE", "/me", json={"password": "my-own-password"}, headers=me
        ),
    }
    assert slot["key"]
    assert set(calls) == set(ROUTES), (
        f"tests/test_responses.py does not call every route: {sorted(set(ROUTES) ^ set(calls))}"
    )

    forbidden_values = {
        "my password hash": my_hash,
        "their password hash": their_hash,
        "their storage key": their_key,
        "their email": "other@example.com",
        "their name": "Them",
        "their school": "Their Secret School",
        "their note": "their private note",
        "my password": "my-own-password",
        "text from my resume": "Trained machine learning ranking models",
        "text from their resume": "Their Secret School thesis",
    }
    assert my_text and their_text and my_hash.startswith("$2b$")

    for route, r in calls.items():
        assert r.status_code < 400, f"{route}: {r.status_code} {r.text}"
        if r.status_code == 204:
            assert r.content == b"", route
            continue
        if route in FILE_ROUTES:
            assert r.headers["content-disposition"].startswith("attachment;"), route
            continue
        assert r.headers["content-type"].startswith("application/json"), route
        for where, key, _ in _walk(r.json()):
            assert key not in NEVER, f"{route} has {key!r} at {where or 'the top'}"
        for what, value in forbidden_values.items():
            if what == "text from my resume" and route in OWN_TEXT_ALLOWED_IN:
                continue
            assert value not in r.text, f"{route} contains {what}"
        if route not in KEY_ALLOWED_IN:
            assert "resumes/" not in r.text, f"{route} contains a storage key"
            assert my_key not in r.text


def test_error_responses_leak_nothing_either(client, auth, db):
    """An error is a response too. Not the SQL, not the traceback, not the
    path on disk, not whether the email exists."""
    from app.deps import get_db

    def broken():
        raise RuntimeError("secret internal detail: /Users/someone/step1/app/config.py")
        yield

    app.dependency_overrides[get_db] = broken
    try:
        from fastapi.testclient import TestClient

        with TestClient(app, raise_server_exceptions=False) as quiet:
            r = quiet.get("/saved", headers=auth)
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 500
    assert r.json() == {"detail": "Something went wrong on our side. Please try again."}
    assert "secret internal detail" not in r.text and "Traceback" not in r.text

    wrong_password = client.post(
        "/auth/login", json={"email": "ada@umd.edu", "password": "not-the-password"}
    )
    no_such_user = client.post(
        "/auth/login", json={"email": "nobody@umd.edu", "password": "not-the-password"}
    )
    assert wrong_password.status_code == no_such_user.status_code == 401
    assert wrong_password.json() == no_such_user.json()


def test_every_timestamp_has_one_form(client):
    """UTC, to the second, with a Z: 2026-09-29T02:42:53Z. Everywhere."""
    import re

    from app.services import ingest_scheduler
    from tests.conftest import fake_source

    ingest_scheduler.run_due({"simplify": fake_source("simplify")})
    me = register(client)
    upload_resume(client, me)
    onboard(client, me)
    client.post("/saved/simplify:a", headers=me)
    app_id = client.post("/applications", json={"posting_id": "simplify:b"}, headers=me).json()[
        "id"
    ]
    client.post(f"/applications/{app_id}/events", json={"kind": "acknowledged"}, headers=me)

    form = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
    looks_like_a_time = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]")
    found = 0
    for path in ("/profile", "/feed", "/saved", "/applications", f"/applications/{app_id}",
                 "/postings/simplify:a", "/ingest/status", "/stats"):  # fmt: skip
        for where, key, value in _walk(client.get(path, headers=me).json()):
            if isinstance(value, str) and looks_like_a_time.match(value):
                found += 1
                assert form.match(value), f"{path} {where}.{key} = {value!r}"
    assert found >= 12
