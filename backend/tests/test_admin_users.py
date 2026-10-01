"""GET /admin/users, /admin/users/{id} and the resume file: the owner's view
of every person. To everyone else these paths are not there."""

from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, urlparse

import pytest

from app import config
from app.routes import admin as admin_routes
from tests.conftest import make_pdf, make_row, onboard, register, seed, upload_resume

OWNER = "owner@example.com"
NOT_FOUND = {"detail": "Not found."}
Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


@pytest.fixture()
def owner(client, monkeypatch) -> dict:
    monkeypatch.setattr(config, "ADMIN_EMAILS", frozenset({OWNER}))
    return register(client, email=OWNER, name="The Owner")


@pytest.fixture()
def audit_log(monkeypatch, caplog):
    # alembic's logging setup in the test session disables existing loggers.
    monkeypatch.setattr(admin_routes.audit, "disabled", False)
    caplog.set_level(logging.INFO, logger="audit")
    return caplog


@pytest.fixture()
def ada(client) -> tuple[dict, int]:
    seed([make_row("a", company="Acme"), make_row("b", company="Globex")])
    headers = register(client, email="ada@umd.edu", name="Ada Lovelace")
    assert upload_resume(client, headers, make_pdf(), "Ada CV.pdf").status_code == 200
    onboard(client, headers, school="UMD", major="Info Sci")
    client.post("/saved/simplify:a", headers=headers)
    app_id = client.post(
        "/applications", json={"posting_id": "simplify:b"}, headers=headers
    ).json()["id"]
    client.post(
        f"/applications/{app_id}/events", json={"kind": "note", "note": "called"}, headers=headers
    )
    client.post("/reviews", json={"rating": 4, "body": "good"}, headers=headers)
    me = client.get("/me", headers=headers).json()
    return headers, me["id"]


def test_the_list(client, owner, ada):
    _, ada_id = ada
    register(client, email="bob_x@example.com", name="Bob 100%")
    r = client.get("/admin/users", headers=owner)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"items", "page", "total", "has_more"}
    assert body["total"] == 3 and body["has_more"] is False
    # Newest first.
    assert [u["email"] for u in body["items"]] == ["bob_x@example.com", "ada@umd.edu", OWNER]
    row = next(u for u in body["items"] if u["id"] == ada_id)
    assert row == {
        "id": ada_id,
        "email": "ada@umd.edu",
        "display_name": "Ada Lovelace",
        "created_at": row["created_at"],
        "onboarded": True,
        "school": "UMD",
        "major": "Info Sci",
        "grad_year": 2028,
        "applications": 1,
        "saved": 1,
        "tailored_resumes": 0,
        "has_resume": True,
        "last_active_at": row["last_active_at"],
    }
    assert Z.match(row["created_at"]) and Z.match(row["last_active_at"])
    bob = next(u for u in body["items"] if u["email"] == "bob_x@example.com")
    assert bob["onboarded"] is False and bob["last_active_at"] is None and not bob["has_resume"]


@pytest.mark.parametrize(
    "q, emails",
    [
        ("ADA", ["ada@umd.edu"]),
        ("lovelace", ["ada@umd.edu"]),
        ("%", ["bob_x@example.com"]),  # a literal percent, in Bob's name
        ("_x", ["bob_x@example.com"]),  # a literal underscore
        ("nobody", []),
        ("   ", ["bob_x@example.com", "ada@umd.edu", OWNER]),
    ],
)
def test_search_is_case_insensitive_and_literal(client, owner, ada, q, emails):
    register(client, email="bob_x@example.com", name="Bob 100%")
    r = client.get("/admin/users", params={"q": q}, headers=owner)
    assert [u["email"] for u in r.json()["items"]] == emails


def test_pages(client, owner):
    for n in range(4):
        register(client, email=f"p{n}@example.com")
    first = client.get("/admin/users?page=1&page_size=2", headers=owner).json()
    third = client.get("/admin/users?page=3&page_size=2", headers=owner).json()
    assert first["total"] == 5 and first["has_more"] and len(first["items"]) == 2
    assert [u["email"] for u in third["items"]] == [OWNER] and not third["has_more"]


def test_one_person_in_full(client, owner, ada, audit_log):
    headers, ada_id = ada
    r = client.get(f"/admin/users/{ada_id}", headers=owner)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"user", "profile", "saved", "applications", "resumes", "reviews"}
    assert body["user"] == {
        "id": ada_id,
        "email": "ada@umd.edu",
        "display_name": "Ada Lovelace",
        "created_at": body["user"]["created_at"],
        "is_admin": False,
    }
    # Exactly what Ada herself sees at GET /profile.
    assert body["profile"] == client.get("/profile", headers=headers).json()

    # Her saved posting and her application, in her own shapes, without scores.
    assert [p["id"] for p in body["saved"]] == ["simplify:a"]
    assert body["saved"][0]["saved"] is True
    assert body["saved"][0]["score"] is None and body["saved"][0]["reasons"] == []
    (application,) = body["applications"]
    hers = client.get(f"/applications/{application['id']}", headers=headers).json()
    hers["posting"] |= {"score": None, "reasons": []}
    assert application == hers
    assert [e["kind"] for e in application["events"]] == ["applied", "note"]

    assert body["resumes"] == []
    assert [(x["rating"], x["body"]) for x in body["reviews"]] == [(4, "good")]

    # One audit line: who, whose, which route. Not what.
    lines = [rec for rec in audit_log.records if rec.name == "audit"]
    assert len(lines) == 1
    assert lines[0].admin_email == OWNER and lines[0].target_user_id == ada_id
    assert lines[0].route == "GET /admin/users/{id}"
    assert "Lovelace" not in audit_log.text and "called" not in audit_log.text


def test_someone_with_nothing_yet(client, owner):
    bob = register(client, email="bob@example.com")
    bob_id = client.get("/me", headers=bob).json()["id"]
    body = client.get(f"/admin/users/{bob_id}", headers=owner).json()
    assert body["profile"] is None
    assert body["saved"] == body["applications"] == body["resumes"] == body["reviews"] == []
    r = client.get(f"/admin/users/{bob_id}/resume-file", headers=owner)
    assert (r.status_code, r.json()) == (404, {"detail": "This person has no resume."})


def test_no_such_person(client, owner):
    for path in ("/admin/users/999999", "/admin/users/999999/resume-file"):
        r = client.get(path, headers=owner)
        assert (r.status_code, r.json()) == (404, NOT_FOUND)


def test_the_resume_file_locally(client, owner, ada, audit_log):
    _, ada_id = ada
    r = client.get(f"/admin/users/{ada_id}/resume-file", headers=owner)
    assert r.status_code == 200, r.text
    link = r.json()
    assert set(link) == {"url", "filename", "expires_at"}
    assert link["filename"] == "Ada CV.pdf" and Z.match(link["expires_at"])
    assert link["url"].startswith(f"{config.PUBLIC_API_BASE}/admin/resume-files/")

    # The link is the permission: no token needed, as with S3's.
    got = client.get(link["url"].removeprefix(config.PUBLIC_API_BASE))
    assert got.status_code == 200
    assert got.content == make_pdf()
    assert got.headers["content-type"] == "application/pdf"
    assert got.headers["content-disposition"] == (
        "attachment; filename=\"Ada CV.pdf\"; filename*=UTF-8''Ada%20CV.pdf"
    )
    assert [rec.route for rec in audit_log.records if rec.name == "audit"] == [
        "GET /admin/users/{id}/resume-file"
    ]


def test_a_link_cannot_be_forged_or_reused_late(client, owner, ada, monkeypatch):
    import jwt

    _, ada_id = ada
    url = client.get(f"/admin/users/{ada_id}/resume-file", headers=owner).json()["url"]
    token = url.rsplit("/", 1)[1]
    claims = jwt.decode(token, options={"verify_signature": False})
    forged = [
        token[:-3] + ("aaa" if not token.endswith("aaa") else "bbb"),
        jwt.encode(claims, "guess", algorithm="HS256"),
        jwt.encode(claims | {"k": "../../etc/passwd"}, admin_routes._LOCAL_LINK_KEY, "HS256"),
        jwt.encode(claims | {"exp": 1}, admin_routes._LOCAL_LINK_KEY, "HS256"),
        jwt.encode(claims | {"aud": "other"}, admin_routes._LOCAL_LINK_KEY, "HS256"),
    ]
    for bad in forged:
        r = client.get(f"/admin/resume-files/{bad}")
        assert (r.status_code, r.json()) == (404, NOT_FOUND)
    # And in S3 mode the local route is not there at all.
    monkeypatch.setattr(config, "STORAGE_BACKEND", "s3")
    assert client.get(f"/admin/resume-files/{token}").status_code == 404


def test_the_resume_file_from_s3(client, owner, ada, monkeypatch):
    """S3 mode hands out a presigned GET that downloads as an attachment."""
    from app.services import storage

    _, ada_id = ada
    monkeypatch.setattr(config, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(config, "S3_BUCKET", "step1-resumes-test")
    monkeypatch.setattr(config, "S3_ENDPOINT_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAIOSFODNN7EXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
    link = client.get(f"/admin/users/{ada_id}/resume-file", headers=owner).json()
    url = urlparse(link["url"])
    query = parse_qs(url.query)
    assert url.path.startswith("/step1-resumes-test/resumes/")
    assert query["response-content-disposition"] == [storage.attachment("Ada CV.pdf")]
    assert query["X-Amz-Expires"] == [str(config.PRESIGN_EXPIRY_SECONDS)]


def test_to_anyone_else_none_of_it_is_there(client, owner, ada):
    headers, ada_id = ada
    for path in (
        "/admin/users",
        f"/admin/users/{ada_id}",
        f"/admin/users/{ada_id}/resume-file",
        "/admin/users/not-a-number",
    ):
        for who in (headers, {}):
            r = client.get(path, headers=who)
            assert (r.status_code, r.json()) == (404, NOT_FOUND), path
        assert client.post(path, headers=headers).json() == NOT_FOUND
