"""Every bound in app/limits.py: the largest allowed value is accepted, one
more is a 422 that names the field in plain words.

Both halves matter. A limit tested only from above can be off by one in the
strict direction and nobody finds out until a real user is refused.
"""

import copy

import pytest

from app import limits
from tests.conftest import PROFILE, make_row, onboard, register, seed


def profile(**over) -> dict:
    return copy.deepcopy(PROFILE) | over


# (field, value at the limit, value past it, words the error must contain)
PROFILE_BOUNDS = [
    ("gpa", 5.0, 5.01, "less than or equal to 5"),
    ("gpa", 0.0, -0.01, "greater than or equal to 0"),
    ("school", "s" * 120, "s" * 121, "at most 120 characters"),
    ("major", "m" * 120, "m" * 121, "at most 120 characters"),
    ("minor", "n" * 120, "n" * 121, "at most 120 characters"),
    ("degree_level", "d" * 40, "d" * 41, "at most 40 characters"),
    ("grad_year", 2100, 2101, "less than or equal to 2100"),
    ("grad_year", 2000, 1999, "greater than or equal to 2000"),
    (
        "preferred_locations",
        [f"City {n}, MD" for n in range(20)],
        [f"City {n}, MD" for n in range(21)],
        "at most 20 locations, not 21",
    ),
    (
        "preferred_locations",
        ["x" * 100],
        ["Washington, DC", "x" * 101],
        "entry 2 is longer than 100 characters",
    ),
    (
        "skills",
        [f"skill-{n}" for n in range(100)],
        [f"skill-{n}" for n in range(101)],
        "at most 100 skills, not 101",
    ),
    ("skills", ["k" * 50], ["k" * 51], "entry 1 is longer than 50 characters"),
    (
        "target_terms",
        ["Spring 2027", "Summer 2027", "Fall 2027", "Winter 2027",
         "Spring 2028", "Summer 2028", "Fall 2028", "Winter 2028"],
        ["Spring 2027", "Summer 2027", "Fall 2027", "Winter 2027", "Spring 2028",
         "Summer 2028", "Fall 2028", "Winter 2028", "Spring 2029"],
        "at most 8 terms, not 9",
    ),
]  # fmt: skip


@pytest.mark.parametrize(
    ("field", "allowed", "refused", "words"),
    PROFILE_BOUNDS,
    ids=[f"{f}: {w}" for f, _, _, w in PROFILE_BOUNDS],
)
def test_profile_bounds(client, auth, field, allowed, refused, words):
    ok = client.put("/profile", json=profile(**{field: allowed}), headers=auth)
    assert ok.status_code == 202, ok.text

    before = client.get("/profile", headers=auth).json()
    bad = client.put("/profile", json=profile(**{field: refused}), headers=auth)
    assert bad.status_code == 422, bad.text
    detail = bad.json()["detail"]
    assert isinstance(detail, str)
    assert detail.startswith(f"{field}: "), detail
    assert words in detail, detail
    assert client.get("/profile", headers=auth).json() == before  # nothing was saved


@pytest.mark.parametrize(
    "term",
    ["Sumer 2027", "Summer", "2027", "Summer 27", "Autumn 2027", "Summer 2027 2028",
     "Q3 2027", "Summer 1999", "Summer 2099", "'; DROP TABLE users; --"],
)  # fmt: skip
def test_target_terms_come_from_the_known_set(client, auth, term):
    r = client.put("/profile", json=profile(target_terms=[term]), headers=auth)
    assert r.status_code == 422
    assert r.json()["detail"].startswith("target_terms: ")
    assert "is not a term; use a season and a year, like 'Summer 2027'" in r.json()["detail"]


def test_target_terms_are_stored_in_one_spelling(client, auth):
    body = profile(target_terms=["summer 2027", "  FALL   2027 ", "Summer 2027", ""])
    assert client.put("/profile", json=body, headers=auth).status_code == 202
    saved = client.get("/profile", headers=auth).json()["target_terms"]
    assert saved == ["Summer 2027", "Fall 2027"]


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_gpa_must_be_a_number(client, auth, value):
    import json

    # json.dumps will not write NaN as a number, and a client library would
    # not send one; a hand-built request can. So the body is built by hand.
    raw = json.dumps(profile(gpa="__GPA__")).replace('"__GPA__"', value)
    r = client.put("/profile", content=raw, headers={**auth, "Content-Type": "application/json"})
    assert r.status_code == 422
    assert r.json()["detail"].startswith("gpa: ")


def test_lists_are_cleaned_not_just_counted(client, auth):
    body = profile(
        preferred_locations=["  Washington,   DC ", "Washington, DC", "", "   "],
        skills=["python", "Python", " SQL "],
    )
    assert client.put("/profile", json=body, headers=auth).status_code == 202
    saved = client.get("/profile", headers=auth).json()
    assert saved["preferred_locations"] == ["Washington, DC"]


# --------------------------------------------------------------------------- #
# Account
# --------------------------------------------------------------------------- #


def _email(length: int) -> str:
    # 64-character local part, the rest in the domain, labels of 63 at most.
    domain_room = length - 65 - len(".example.com")
    labels = []
    while domain_room > 0:
        take = min(63, domain_room)
        labels.append("d" * take)
        domain_room -= take + 1
    return "l" * 64 + "@" + ".".join(labels) + ".example.com"


def test_email_bound(client):
    good = _email(254)
    assert len(good) <= 254
    ok = client.post("/auth/register", json={"email": good, "password": "correct-horse"})
    assert ok.status_code == 200, ok.text

    for path in ("/auth/register", "/auth/login"):
        r = client.post(path, json={"email": "a" * 250 + "@example.com", "password": "x" * 12})
        assert r.status_code == 422
        assert r.json() == {"detail": "email: must be at most 254 characters"}


def test_password_bounds(client):
    ok = client.post("/auth/register", json={"email": "long@example.com", "password": "p" * 128})
    assert ok.status_code == 200
    assert (
        client.post(
            "/auth/login", json={"email": "long@example.com", "password": "p" * 128}
        ).status_code
        == 200
    )
    for path in ("/auth/register", "/auth/login"):
        r = client.post(path, json={"email": "other@example.com", "password": "p" * 129})
        assert r.status_code == 422
        assert r.json() == {"detail": "password: must be at most 128 characters"}


def test_display_name_bound(client):
    ok = client.post(
        "/auth/register",
        json={"email": "a@example.com", "password": "correct-horse", "display_name": "n" * 80},
    )
    assert ok.status_code == 200
    r = client.post(
        "/auth/register",
        json={"email": "b@example.com", "password": "correct-horse", "display_name": "n" * 81},
    )
    assert r.status_code == 422
    assert r.json() == {"detail": "display_name: String should have at most 80 characters"}


# --------------------------------------------------------------------------- #
# Applications, uploads, feed filters
# --------------------------------------------------------------------------- #


@pytest.fixture()
def board(client):
    seed([make_row("a"), make_row("b")])
    headers = register(client)
    onboard(client, headers)
    return headers


def test_note_bound(client, board):
    app_id = client.post("/applications", json={"posting_id": "simplify:a"}, headers=board).json()[
        "id"
    ]
    ok = client.post(
        f"/applications/{app_id}/events", json={"kind": "note", "note": "n" * 2000}, headers=board
    )
    assert ok.status_code == 201
    r = client.post(
        f"/applications/{app_id}/events", json={"kind": "note", "note": "n" * 2001}, headers=board
    )
    assert r.status_code == 422
    assert r.json() == {"detail": "note: String should have at most 2000 characters"}
    assert len(client.get(f"/applications/{app_id}", headers=board).json()["events"]) == 2


def test_filename_bound(client, board):
    body = {"content_type": "application/pdf", "size": 4096}
    ok = client.post(
        "/profile/resume/presign", json={**body, "filename": "r" * 251 + ".pdf"}, headers=board
    )
    assert ok.status_code == 200
    r = client.post(
        "/profile/resume/presign", json={**body, "filename": "r" * 252 + ".pdf"}, headers=board
    )
    assert r.status_code == 422
    assert r.json() == {"detail": "filename: String should have at most 255 characters"}


def test_posting_id_bound(client, board):
    long_id = "simplify:" + "x" * 200
    assert client.get(f"/postings/{long_id}", headers=board).status_code == 404
    r = client.post("/applications", json={"posting_id": long_id}, headers=board)
    assert r.status_code == 422
    assert r.json()["detail"].startswith("posting_id: ")


def test_feed_filter_bounds(client, board):
    assert client.get("/feed", params={"location": "x" * 100}, headers=board).status_code == 200
    r = client.get("/feed", params={"location": "x" * 101}, headers=board)
    assert r.status_code == 422
    assert r.json() == {"detail": "location: String should have at most 100 characters"}

    fifteen = ",".join(["software"] * 15)
    assert client.get("/feed", params={"roles": fifteen}, headers=board).status_code == 200
    r = client.get("/feed", params={"roles": fifteen + ",software"}, headers=board)
    assert r.status_code == 422
    assert r.json() == {"detail": "roles: at most 15 roles, not 16"}

    r = client.get("/feed", params={"term": "t" * 41}, headers=board)
    assert r.status_code == 422 and r.json()["detail"].startswith("term: ")


def test_errors_do_not_repeat_back_what_they_were_sent(client, board):
    """An error that quotes its input in full is an echo service. Rejected
    values are shortened to a few dozen characters."""
    huge = "z" * 5000
    body = profile()
    body["interests"][0]["role"] = huge
    for r in (
        client.put("/profile", json=body, headers=board),
        client.put("/profile", json=profile(target_terms=[huge]), headers=board),
        client.post("/applications/1/events", json={"kind": huge}, headers=board),
        client.get("/feed", params={"roles": "r" * 500}, headers=board),
    ):
        assert r.status_code == 422, r.text
        assert len(r.json()["detail"]) < 400, len(r.json()["detail"])
        assert "z" * 41 not in r.json()["detail"] and "r" * 41 not in r.json()["detail"]


# --------------------------------------------------------------------------- #
# The whole request
# --------------------------------------------------------------------------- #


def test_a_body_over_the_limit_is_refused_unread(client, auth):
    padding = "p" * limits.JSON_BODY_MAX_BYTES
    r = client.put("/profile", json=profile(school=padding), headers=auth)
    assert r.status_code == 413
    assert r.json() == {"detail": "That request is too large."}
    assert client.get("/profile", headers=auth).status_code == 404


def test_a_body_that_lies_about_its_length_is_cut_off(client, auth):
    """Chunked, so there is no Content-Length to check up front; the limit
    has to hold against the bytes themselves."""

    def chunks():
        yield b'{"school": "'
        for _ in range(limits.JSON_BODY_MAX_BYTES // 1024 + 8):
            yield b"x" * 1024
        yield b'"}'

    r = client.put(
        "/profile", content=chunks(), headers={**auth, "Content-Type": "application/json"}
    )
    assert r.status_code == 413
    assert r.json() == {"detail": "That request is too large."}


def test_a_full_profile_fits_comfortably(client, auth):
    """Every list at its maximum, every string at its longest: the largest
    body the API will accept is a small fraction of the limit."""
    import json

    body = profile(
        school="s" * 120, major="m" * 120, minor="n" * 120,
        preferred_locations=[f"{n:02d}" + "l" * 98 for n in range(20)],
        skills=[f"{n:03d}" + "k" * 47 for n in range(100)],
        target_terms=["Spring 2027", "Summer 2027", "Fall 2027", "Winter 2027",
                      "Spring 2028", "Summer 2028", "Fall 2028", "Winter 2028"],
    )  # fmt: skip
    size = len(json.dumps(body))
    assert size < limits.JSON_BODY_MAX_BYTES / 4, size
    assert client.put("/profile", json=body, headers=auth).status_code == 202


def test_the_limit_does_not_apply_to_reads_or_uploads(client, auth):
    assert client.get("/me", headers=auth).status_code == 200
    # The upload route is exempt from the JSON limit: an unknown key is a 404
    # from the route itself, not a 413 from the middleware.
    r = client.put(
        f"/profile/resume/local/resumes/1/{'0' * 32}.pdf",
        content=b"%PDF-" + b"0" * (limits.JSON_BODY_MAX_BYTES + 10),
        headers={**auth, "Content-Type": "application/pdf"},
    )
    assert r.status_code != 413
