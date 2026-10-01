"""Object-level authorization: what belongs to A cannot be read or changed by
anyone else.

This is the failure that testing by hand never finds, because by hand you only
ever look at your own data. So it is a test, and the test is exhaustive by
construction: it is parametrized over every route the app actually has, and a
route with neither a case nor a written exemption fails. Adding an endpoint
without deciding how it is scoped is not possible.

The world has three users:

    A   owns one of everything: a profile, a resume, a saved posting, an
        application with events and a private note, cached scores
    B   is onboarded and has data of their own
    C   has only just registered

For each route, B and C try to reach what is A's. Where the route names an
object (an application id, a storage key) the answer must be 404: not 403,
which would confirm the object exists. Where the route is scoped by the token
alone (/profile, /saved, /feed) there is nothing to name, so the assertion is
that the response is the caller's own and carries nothing of A's. Either way,
A's rows and A's stored file are compared before and after: nothing changed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from app import config
from app.database import Base, SessionLocal
from app.main import app
from tests.conftest import (
    PROFILE,
    api_routes,
    base_resume,
    make_pdf,
    make_row,
    onboard,
    presign,
    register,
    resume_doc,
    seed,
    upload_resume,
)

ROUTES = api_routes(app)

# Strings that exist only in A's data. None may appear in anything B or C is sent.
A_SCHOOL = "Alpha-Only Polytechnic"
A_MAJOR = "Alpha-Only Studies"
A_NOTE = "alpha-private-note-7f3a"
A_RESUME_NAME = "alpha-private-resume.pdf"
A_SKILL = "Haskell"
A_EMAIL = "alpha@example.com"
A_NAME = "Alpha Owner"
A_PASSWORD = "alpha-own-password"
A_REVIEW = "alpha-private-review-91c2"
A_BASE_LINE = "Built alpha-only-pipeline in Python for 3 teams"
A_SAVED_NAME = "Alpha Only Saved Resume"
# Nobody in the world below is an admin: the admin route must be a 404 to
# every one of them.
OWNER = "owner@example.com"

# Admin-only routes: to anyone who is not an admin, signed in or not, they
# answer as a path that does not exist.
ADMIN_ONLY = {
    ("GET", "/admin/reviews"),
    ("GET", "/admin/users"),
    ("GET", "/admin/users/{user_id}"),
    ("GET", "/admin/users/{user_id}/resume-file"),
    ("GET", "/admin/resume-files/{token}"),
    ("GET", "/admin/users/{user_id}/resumes/{resume_id}"),
    ("GET", "/admin/users/{user_id}/resumes/{resume_id}/download"),
}

PDF = {"Content-Type": "application/pdf"}


# --------------------------------------------------------------------------- #
# The world
# --------------------------------------------------------------------------- #


@dataclass
class World:
    a: dict
    b: dict
    c: dict
    a_id: int
    b_id: int
    a_application: int
    a_resume_key: str
    a_pending_key: str  # a slot A was issued and has not uploaded to yet
    a_saved_resume: int = 0
    saved: str = "simplify:p-saved"  # A saved it
    applied: str = "simplify:p-applied"  # A applied to it
    other: str = "simplify:p-other"
    secrets: list[str] = field(default_factory=list)


@pytest.fixture()
def world(client, monkeypatch) -> World:
    monkeypatch.setattr(config, "ADMIN_EMAILS", frozenset({OWNER}))
    seed(
        [
            make_row("p-saved", "Software Engineer Intern", "Acme", days_ago=1),
            make_row("p-applied", "Haskell Compiler Engineer Intern", "Globex", days_ago=2),
            make_row("p-other", "Data Analyst Intern", "Initech", category="AI/ML/Data"),
        ]
    )
    a = register(client, email=A_EMAIL, name=A_NAME, password=A_PASSWORD)
    b = register(client, email="bravo@example.com", name="Bravo")
    c = register(client, email="charlie@example.com", name="Charlie")

    committed = upload_resume(client, a, make_pdf(), A_RESUME_NAME)
    assert committed.status_code == 200, committed.text
    onboard(client, a, school=A_SCHOOL, major=A_MAJOR, skills=[A_SKILL, "Python"])
    assert client.post("/saved/simplify:p-saved", headers=a).status_code == 204
    created = client.post(
        "/applications",
        json={"posting_id": "simplify:p-applied", "applied_at": "2026-09-01T12:00:00Z"},
        headers=a,
    )
    assert created.status_code == 201, created.text
    application = created.json()["id"]
    noted = client.post(
        f"/applications/{application}/events",
        json={"kind": "note", "note": A_NOTE},
        headers=a,
    )
    assert noted.status_code == 201, noted.text
    reviewed = client.post("/reviews", json={"rating": 4, "body": A_REVIEW}, headers=a)
    assert reviewed.status_code == 201, reviewed.text
    based = client.put("/resume/base", json=base_resume(line=A_BASE_LINE), headers=a)
    assert based.status_code == 200, based.text
    saved_resume = client.post(
        "/resumes",
        json={"name": A_SAVED_NAME, "doc": resume_doc(line=A_BASE_LINE),
              "posting_id": "simplify:p-applied"},
        headers=a,
    )  # fmt: skip
    assert saved_resume.status_code == 201, saved_resume.text

    # B differs from A wherever the scorer looks, so a score that leaked
    # across would be the wrong number and show.
    onboard(
        client,
        b,
        school="Bravo College",
        major="Bravo Studies",
        preferred_locations=["Austin, TX"],
        remote_ok=False,
        interests=[
            {"role": "hardware", "rank": 1},
            {"role": "quant", "rank": 2},
            {"role": "security", "rank": 3},
        ],
        skills=["Verilog"],
    )

    # Presigned last: issuing a slot discards the owner's unfinished ones.
    pending = presign(client, a, len(make_pdf()), "alpha-next-resume.pdf")["key"]

    with SessionLocal() as db:
        a_id, b_id = (
            db.execute(text("SELECT id FROM users WHERE email = :e"), {"e": e}).scalar_one()
            for e in (A_EMAIL, "bravo@example.com")
        )
        key = db.execute(
            text("SELECT resume_s3_key FROM profiles WHERE user_id = :u"), {"u": a_id}
        ).scalar_one()

    return World(
        a=a, b=b, c=c, a_id=a_id, b_id=b_id, a_application=application, a_resume_key=key,
        a_pending_key=pending, a_saved_resume=saved_resume.json()["id"],
        secrets=[A_SCHOOL, A_MAJOR, A_NOTE, A_RESUME_NAME, "alpha-next-resume", A_EMAIL,
                 A_NAME, key, pending, A_REVIEW, "alpha-only-pipeline", A_SAVED_NAME],
    )  # fmt: skip


# --------------------------------------------------------------------------- #
# What "nothing changed" means
# --------------------------------------------------------------------------- #

# Every table that holds a user's data, and how to find one user's rows in it.
OWNED_TABLES = {
    "users": "id = :u",
    "profiles": "user_id = :u",
    "profile_interests": "user_id = :u",
    "match_scores": "user_id = :u",
    "saved_postings": "user_id = :u",
    "applications": "user_id = :u",
    "application_events": "application_id IN (SELECT id FROM applications WHERE user_id = :u)",
    "contacts": "user_id = :u",
    "outreach_messages": "application_id IN (SELECT id FROM applications WHERE user_id = :u)",
    "integrations": "user_id = :u",
    "resume_uploads": "user_id = :u",
    "reviews": "user_id = :u",
    "base_resumes": "user_id = :u",
    "tailored_resumes": "user_id = :u",
}
# Shared by everyone, or bookkeeping: no row in these belongs to a user.
SHARED_TABLES = {"postings", "companies", "ingest_runs", "alembic_version"}


def snapshot(w: World, client) -> dict:
    """Everything that is A's: every row, the stored file, and A's own view."""
    state: dict = {}
    with SessionLocal() as db:
        for table, mine in OWNED_TABLES.items():
            rows = db.execute(text(f"SELECT * FROM {table} WHERE {mine}"), {"u": w.a_id})
            state[table] = sorted(repr(sorted(dict(r).items())) for r in rows.mappings())
    stored = Path(config.UPLOAD_DIR) / w.a_resume_key
    state["resume bytes"] = stored.read_bytes()
    for path in ("/me", "/profile", "/saved", "/applications", f"/applications/{w.a_application}"):
        r = client.get(path, headers=w.a)
        state[f"A's GET {path}"] = (r.status_code, r.json())
    return state


def test_every_table_is_classified():
    """A new table has to be declared owned or shared. If it is owned and
    missing from the snapshot, a route could change A's rows in it unseen."""
    tables = set(Base.metadata.tables) | {"alembic_version"}
    assert tables == set(OWNED_TABLES) | SHARED_TABLES, (
        "Classify the new table in tests/test_authorization.py: "
        f"{sorted(tables ^ (set(OWNED_TABLES) | SHARED_TABLES))}"
    )
    # And nothing marked shared has a user column hiding in it.
    from app.database import engine

    for table in SHARED_TABLES - {"alembic_version"}:
        columns = {c["name"] for c in inspect(engine).get_columns(table)}
        assert "user_id" not in columns, table


# --------------------------------------------------------------------------- #
# The attempts
# --------------------------------------------------------------------------- #

HIDDEN = "hidden"  # must be 404
OWN = "own"  # must succeed, as the caller's own


@dataclass
class Attempt:
    who: str  # "b" or "c"
    what: str
    method: str
    path: str
    expect: str | int = HIDDEN
    json: dict | None = None
    content: bytes | None = None
    headers: dict = field(default_factory=dict)
    check: object = None  # called with (response, world, client) when it succeeds


def _no_application_or_save(r, w, client):
    items = r.json()["items"] if "items" in r.json() else [r.json()]
    for item in items:
        posting = item.get("posting", item)
        assert posting["saved"] is False, posting["id"]
        assert posting["application"] is None, posting["id"]


def _scores_are_the_callers(r, w, client):
    """B ranks hardware first and lives in Austin; A ranks software and lives
    in Washington. On these postings their scores cannot coincide."""
    body = r.json()
    items = body["items"] if "items" in body else [body]
    theirs = {i["id"]: i for i in items}
    mine = {i["id"]: i for i in client.get("/feed?page_size=100", headers=w.a).json()["items"]}
    assert theirs, "expected postings in the response"
    for posting_id, item in theirs.items():
        assert item["score"] != mine[posting_id]["score"], posting_id
        assert A_SKILL not in str(item["reasons"]), posting_id
    _no_application_or_save(r, w, client)


def _is_b(r, w, client):
    assert r.json()["email"] == "bravo@example.com" and r.json()["id"] == w.b_id


def _profile_is_bs(r, w, client):
    assert r.json()["school"] == "Bravo College" and r.json()["resume"] is None


def _key_is_in_bs_namespace(r, w, client):
    assert r.json()["key"].startswith(f"resumes/{w.b_id}/")
    assert f"/resumes/{w.b_id}/" in r.json()["upload_url"]


def _list_is_empty(r, w, client):
    assert r.json().get("items") == [] and r.json().get("total", 0) == 0


def _review_is_bs(r, w, client):
    assert r.json()["body"] == "written by B" and r.json()["rating"] == 2


def _base_is_bs(r, w, client):
    assert r.json()["name"] == "Bravo"
    assert client.get("/resume/base", headers=w.b).json()["name"] == "Bravo"


def _only_b_is_gone(r, w, client):
    assert client.get("/me", headers=w.b).status_code == 401
    assert client.get("/me", headers=w.a).json()["email"] == A_EMAIL
    assert client.get("/me", headers=w.c).status_code == 200


def _b_saved_it_for_b(r, w, client):
    saved = client.get("/saved", headers=w.b).json()
    assert [i["id"] for i in saved["items"]] == [w.saved]


def _b_applied_as_b(r, w, client):
    body = r.json()
    assert body["id"] != w.a_application
    assert [e["kind"] for e in body["events"]] == ["applied"]  # A's note is not here
    assert body["posting"]["application"] == {"id": body["id"], "status": "applied"}


def _unsigned(claims: dict) -> str:
    """A token signed with nothing (alg "none"), built here rather than
    written out as a literal."""
    import base64
    import json

    def part(value: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'none'})}.{part(claims)}."


def cases(w: World) -> dict[tuple[str, str], list[Attempt]]:
    app_id = w.a_application
    note = {"kind": "note", "note": "written by someone else"}
    body = {**PROFILE, "school": "Bravo College II"}
    slot = {"filename": "mine.pdf", "content_type": "application/pdf", "size": 4096}
    pdf = make_pdf()
    return {
        ("GET", "/me"): [Attempt("b", "reads /me", "GET", "/me", OWN, check=_is_b)],
        ("DELETE", "/me"): [
            # There is no way to name another account. What can be tried is
            # another account's password, and that deletes nothing.
            Attempt("b", "deletes an account with A's password", "DELETE", "/me", 403,
                    json={"password": A_PASSWORD}),
            Attempt("c", "deletes an account with a guess", "DELETE", "/me", 403,
                    json={"password": "not-anyones-password"}),
            Attempt("b", "deletes their own account", "DELETE", "/me", 204,
                    json={"password": "correct-horse"}, check=_only_b_is_gone),
        ],
        ("GET", "/profile"): [
            Attempt("b", "reads /profile", "GET", "/profile", OWN, check=_profile_is_bs),
            Attempt("c", "reads /profile with none of their own", "GET", "/profile", HIDDEN),
        ],
        ("PUT", "/profile"): [
            Attempt("b", "saves a profile", "PUT", "/profile", 202, json=body),
            Attempt("c", "saves a first profile", "PUT", "/profile", 202, json=body),
        ],
        ("POST", "/profile/resume/presign"): [
            Attempt("b", "asks for an upload slot", "POST", "/profile/resume/presign", OWN,
                    json=slot, check=_key_is_in_bs_namespace),
        ],
        ("PUT", "/profile/resume/local/{key:path}"): [
            Attempt(who, what, "PUT", f"/profile/resume/local/{key}", HIDDEN,
                    content=pdf, headers=PDF)
            for who in ("b", "c")
            for what, key in [
                ("overwrites A's stored resume", w.a_resume_key),
                ("uploads into the slot A was issued", w.a_pending_key),
            ]
        ],
        ("POST", "/profile/resume/commit"): [
            Attempt(who, what, "POST", "/profile/resume/commit", HIDDEN,
                    json={"key": key, "filename": "stolen.pdf"})
            for who in ("b", "c")
            for what, key in [
                ("claims A's resume as their own", w.a_resume_key),
                ("commits the slot A was issued", w.a_pending_key),
            ]
        ],
        ("GET", "/feed"): [
            Attempt("b", "reads the feed", "GET", "/feed?page_size=100", OWN,
                    check=_scores_are_the_callers),
            Attempt("c", "reads the feed before onboarding", "GET", "/feed", 409),
        ],
        ("GET", "/feed/status"): [
            Attempt("b", "polls build status", "GET", "/feed/status", OWN),
            Attempt("c", "polls build status before onboarding", "GET", "/feed/status", 409),
        ],
        ("GET", "/postings/{posting_id}"): [
            Attempt("b", "opens the posting A saved", "GET", f"/postings/{w.saved}", OWN,
                    check=_scores_are_the_callers),
            Attempt("b", "opens the posting A applied to", "GET", f"/postings/{w.applied}", OWN,
                    check=_scores_are_the_callers),
            Attempt("c", "opens the posting A applied to", "GET", f"/postings/{w.applied}", OWN,
                    check=_no_application_or_save),
        ],
        ("GET", "/saved"): [
            Attempt(who, "lists saved postings", "GET", "/saved", OWN, check=_list_is_empty)
            for who in ("b", "c")
        ],
        ("POST", "/saved/{posting_id}"): [
            Attempt("b", "saves the posting A saved", "POST", f"/saved/{w.saved}", 204,
                    check=_b_saved_it_for_b),
        ],
        ("DELETE", "/saved/{posting_id}"): [
            Attempt(who, "unsaves the posting A saved", "DELETE", f"/saved/{w.saved}", 204)
            for who in ("b", "c")
        ],
        ("GET", "/applications"): [
            Attempt(who, "lists applications", "GET", "/applications", OWN,
                    check=lambda r, w, client: r.json() == {"items": []})
            for who in ("b", "c")
        ],
        ("POST", "/applications"): [
            Attempt("b", "applies to the posting A applied to", "POST", "/applications", 201,
                    json={"posting_id": w.applied}, check=_b_applied_as_b),
        ],
        ("GET", "/applications/{application_id}"): [
            Attempt(who, "opens A's application", "GET", f"/applications/{app_id}", HIDDEN)
            for who in ("b", "c")
        ],
        ("POST", "/applications/{application_id}/events"): [
            Attempt("b", "adds a note to A's application", "POST",
                    f"/applications/{app_id}/events", HIDDEN, json=note),
            Attempt("b", "withdraws A's application", "POST",
                    f"/applications/{app_id}/events", HIDDEN, json={"kind": "withdrawn"}),
            Attempt("c", "rejects A's application", "POST",
                    f"/applications/{app_id}/events", HIDDEN, json={"kind": "rejected"}),
            # An illegal kind must not answer differently for A's id than for
            # an id that does not exist: 422 here would confirm the row.
            Attempt("b", "probes A's application with an illegal step", "POST",
                    f"/applications/{app_id}/events", HIDDEN, json={"kind": "offer"}),
        ],
        ("POST", "/reviews"): [
            Attempt("b", "writes a review", "POST", "/reviews", 201,
                    json={"rating": 2, "body": "written by B"}, check=_review_is_bs),
        ],
        ("GET", "/admin/reviews"): [
            Attempt(who, "lists every review, not being an admin", "GET", path, HIDDEN)
            for who in ("b", "c")
            for path in ("/admin/reviews", "/admin/reviews?page=2&page_size=5",
                         "/admin/reviews?page=nonsense")
        ],
        ("POST", "/resume/base/extract"): [
            # B's own upload, if any; C has none. Never A's.
            Attempt("c", "drafts a base resume with no upload", "POST",
                    "/resume/base/extract", 409),
        ],
        ("GET", "/resume/base"): [
            Attempt(who, "reads a base resume, having none", "GET", "/resume/base", HIDDEN)
            for who in ("b", "c")
        ],
        ("PUT", "/resume/base"): [
            Attempt("b", "saves a base resume", "PUT", "/resume/base", 200,
                    json=base_resume(name="Bravo"), check=_base_is_bs),
        ],
        ("POST", "/tailor"): [
            Attempt("c", "tailors with no base resume", "POST", "/tailor", 409,
                    json={"job_text": "Data intern"}),
        ],
        ("POST", "/resumes"): [
            Attempt("b", "saves a resume", "POST", "/resumes", 201,
                    json={"name": "Bravo resume", "doc": resume_doc(name="Bravo")}),
        ],
        ("GET", "/resumes"): [
            Attempt(who, "lists saved resumes", "GET", "/resumes", OWN, check=_list_is_empty)
            for who in ("b", "c")
        ],
        ("GET", "/resumes/{resume_id}"): [
            Attempt(who, "opens A's saved resume", "GET", f"/resumes/{w.a_saved_resume}", HIDDEN)
            for who in ("b", "c")
        ],
        ("PUT", "/resumes/{resume_id}"): [
            Attempt(who, "renames A's saved resume", "PUT", f"/resumes/{w.a_saved_resume}",
                    HIDDEN, json={"name": "mine now"})
            for who in ("b", "c")
        ],
        ("DELETE", "/resumes/{resume_id}"): [
            Attempt(who, "deletes A's saved resume", "DELETE", f"/resumes/{w.a_saved_resume}",
                    HIDDEN)
            for who in ("b", "c")
        ],
        ("GET", "/resumes/{resume_id}/download"): [
            Attempt(who, "downloads A's saved resume", "GET",
                    f"/resumes/{w.a_saved_resume}/download?format={fmt}", HIDDEN)
            for who in ("b", "c") for fmt in ("pdf", "docx")
        ],
        ("GET", "/admin/users"): [
            Attempt(who, "lists every user, not being an admin", "GET", path, HIDDEN)
            for who in ("b", "c")
            for path in ("/admin/users", f"/admin/users?q={A_EMAIL}", "/admin/users?page=x")
        ],
        ("GET", "/admin/users/{user_id}"): [
            Attempt(who, "reads A's everything, not being an admin", "GET",
                    f"/admin/users/{uid}", HIDDEN)
            for who in ("b", "c") for uid in (w.a_id, w.b_id, 999_999, "x")
        ],
        ("GET", "/admin/users/{user_id}/resume-file"): [
            Attempt(who, "asks for A's resume file, not being an admin", "GET",
                    f"/admin/users/{w.a_id}/resume-file", HIDDEN)
            for who in ("b", "c")
        ],
        ("GET", "/admin/users/{user_id}/resumes/{resume_id}"): [
            Attempt(who, "opens A's saved resume through the admin page", "GET",
                    f"/admin/users/{w.a_id}/resumes/{w.a_saved_resume}", HIDDEN)
            for who in ("b", "c")
        ],
        ("GET", "/admin/users/{user_id}/resumes/{resume_id}/download"): [
            Attempt(who, "downloads A's saved resume through the admin page", "GET",
                    f"/admin/users/{w.a_id}/resumes/{w.a_saved_resume}/download", HIDDEN)
            for who in ("b", "c")
        ],
        ("GET", "/admin/resume-files/{token}"): [
            Attempt(who, "forges a download link", "GET", f"/admin/resume-files/{token}", HIDDEN)
            for who in ("b", "c")
            for token in ("x", _unsigned({"k": f"resumes/{w.a_id}/x"}))
        ],
    }  # fmt: skip


# Routes that reach nothing a user owns. Each says why.
EXEMPT = {
    ("GET", "/health"): "liveness probe; reads no table",
    ("POST", "/auth/register"): "creates the caller's own account; names no existing object",
    ("POST", "/auth/login"): "authenticates by email and password; names no object",
    ("GET", "/ingest/status"): "the ingest ledger and a count of open postings; board-wide",
    ("GET", "/stats"): "public counts of the shared board; takes no token, returns no user data",
}


def test_the_walk_found_the_routes():
    """Guards the guard: if route discovery breaks, everything below would
    be parametrized over nothing and pass."""
    assert len(ROUTES) >= 20
    for known in [
        ("GET", "/applications/{application_id}"),
        ("PUT", "/profile/resume/local/{key:path}"),
        ("DELETE", "/saved/{posting_id}"),
    ]:
        assert known in ROUTES


def test_no_case_or_exemption_is_stale(client, world):
    listed = set(cases(world)) | set(EXEMPT)
    assert listed <= set(ROUTES), f"no such route any more: {sorted(listed - set(ROUTES))}"
    assert not set(cases(world)) & set(EXEMPT)
    assert all(reason.strip() for reason in EXEMPT.values())


@pytest.mark.parametrize("route", sorted(ROUTES), ids=lambda r: f"{r[0]} {r[1]}")
def test_nobody_else_can_reach_what_is_as(route, client, world):
    if route in EXEMPT:
        return
    attempts = cases(world).get(route)
    assert attempts, (
        f"{route[0]} {route[1]} has no authorization case. Add one to cases() in "
        "tests/test_authorization.py showing that another user gets a 404 and changes "
        "nothing; or, if the route touches nothing a user owns, add it to EXEMPT with the reason."
    )

    for attempt in attempts:
        before = snapshot(world, client)
        r = client.request(
            attempt.method,
            attempt.path,
            json=attempt.json,
            content=attempt.content,
            headers={**getattr(world, attempt.who), **attempt.headers},
        )
        label = f"{attempt.who.upper()} {attempt.what}: {attempt.method} {attempt.path}"

        if attempt.expect == HIDDEN:
            assert r.status_code == 404, f"{label} -> {r.status_code} {r.text}"
            assert isinstance(r.json()["detail"], str)
        elif attempt.expect == OWN:
            assert r.status_code == 200, f"{label} -> {r.status_code} {r.text}"
        else:
            assert r.status_code == attempt.expect, f"{label} -> {r.status_code} {r.text}"

        for secret in world.secrets:
            # The presign response legitimately echoes the caller's own key.
            assert secret not in r.text, f"{label} leaked {secret!r}"
        if attempt.check is not None and r.status_code < 400:
            attempt.check(r, world, client)
        if attempt.expect == 403:
            assert r.json() == {"detail": "Password is incorrect."}
            for who in (world.a, world.b, world.c):
                assert client.get("/me", headers=who).status_code == 200

        assert snapshot(world, client) == before, f"{label} changed something of A's"


def test_a_missing_object_and_someone_elses_look_the_same(client, world):
    """If A's application answered differently from one that was never
    created, the difference would be the leak."""
    for method, template, payload in [
        ("GET", "/applications/{}", None),
        ("POST", "/applications/{}/events", {"kind": "note", "note": "x"}),
        ("POST", "/applications/{}/events", {"kind": "offer"}),
    ]:
        theirs = client.request(
            method, template.format(world.a_application), json=payload, headers=world.b
        )
        absent = client.request(method, template.format(999_999), json=payload, headers=world.b)
        assert (
            (theirs.status_code, theirs.json())
            == (absent.status_code, absent.json())
            == (
                404,
                {"detail": "That application doesn't exist."},
            )
        )

    never_issued = [
        f"resumes/{world.a_id}/{'0' * 32}.pdf",
        f"resumes/{world.b_id}/{'0' * 32}.pdf",  # in B's own namespace, but never issued
        f"resumes/{world.a_id}/0123456789ab-old-style-name.pdf",
        "not-a-key-at-all",
    ]
    for key in (world.a_resume_key, world.a_pending_key, *never_issued):
        put = client.put(
            f"/profile/resume/local/{key}", content=make_pdf(), headers={**world.b, **PDF}
        )
        commit = client.post(
            "/profile/resume/commit", json={"key": key, "filename": "x.pdf"}, headers=world.b
        )
        assert (put.status_code, put.json()) == (404, {"detail": "Unknown upload key."})
        assert (commit.status_code, commit.json()) == (404, {"detail": "Unknown upload key."})


def test_the_public_routes_are_exactly_these(client, world):
    """Every route that answers without a token, by name. A new one has to
    be added here on purpose."""
    public = set()
    fill = {"application_id": world.a_application, "posting_id": world.saved,
            "key": world.a_resume_key, "user_id": world.a_id,
            "token": "not-a-signed-link", "resume_id": world.a_saved_resume}  # fmt: skip
    for method, template in sorted(ROUTES):
        path = template.replace("{key:path}", "{key}").format(**fill)
        r = client.request(method, path, json={})
        if (method, template) in ADMIN_ONLY:
            assert (r.status_code, r.json()) == (404, {"detail": "Not found."}), template
        elif r.status_code != 401:
            public.add((method, template))
    assert public == {
        ("GET", "/health"),
        ("POST", "/auth/register"),
        ("POST", "/auth/login"),
        ("GET", "/stats"),
    }
    assert public <= set(EXEMPT)


def test_without_a_token_every_protected_route_is_401(client, world):
    fill = {"application_id": world.a_application, "posting_id": world.saved,
            "key": world.a_resume_key, "user_id": world.a_id,
            "token": "not-a-signed-link", "resume_id": world.a_saved_resume}  # fmt: skip
    # /ingest/status is exempt from the two-user cases because it shows
    # nothing of any user's. It still needs a token.
    # Admin routes are a 404 instead (test_the_public_routes_are_exactly_these).
    for method, template in sorted(
        set(ROUTES) - set(EXEMPT) - ADMIN_ONLY | {("GET", "/ingest/status")}
    ):
        path = template.replace("{key:path}", "{key}").format(**fill)
        r = client.request(method, path, json={})
        assert r.status_code == 401, f"{method} {path} -> {r.status_code}"
        assert r.json() == {"detail": "Not authenticated."}
