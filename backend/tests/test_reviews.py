"""Reviews: POST /reviews, GET /admin/reviews, and the email to the owner.

The email goes through SNS. Here SNS is FakeSns: nothing reaches the network
or AWS, and every publish is recorded.
"""

from __future__ import annotations

import logging
import re

import pytest
from sqlalchemy import text

from app import config
from app.database import SessionLocal
from app.ratelimit import limiter
from app.routes.reviews import TOO_MANY
from app.services import cognito, notify
from tests.conftest import register

OWNER = "owner@example.com"
TOPIC = "arn:aws:sns:us-east-1:000000000000:test-owner-notifications"
NOT_FOUND = {"detail": "Not found."}
Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class FakeSns:
    """Stands in for boto3's SNS client. `fail` makes publish raise."""

    def __init__(self):
        self.published: list[dict] = []
        self.fail: Exception | None = None

    def publish(self, **kw):
        if self.fail is not None:
            raise self.fail
        self.published.append(kw)
        return {"MessageId": "m-1"}


@pytest.fixture(autouse=True)
def notify_logs(monkeypatch):
    # alembic's logging setup, run by the test session, disables loggers that
    # already exist. These tests read this one.
    monkeypatch.setattr(notify.log, "disabled", False)


@pytest.fixture()
def sns(monkeypatch):
    fake = FakeSns()
    monkeypatch.setattr(notify, "_sns", lambda: fake)
    monkeypatch.setattr(config, "NOTIFY_TOPIC_ARN", TOPIC)
    return fake


@pytest.fixture()
def owner(client, monkeypatch) -> dict:
    monkeypatch.setattr(config, "ADMIN_EMAILS", frozenset({OWNER}))
    return register(client, email=OWNER, name="The Owner")


@pytest.fixture()
def limited(monkeypatch):
    limiter.reset()
    monkeypatch.setattr(limiter, "enabled", True)
    yield
    limiter.reset()


def review(client, headers, rating=5, body="Found three internships in a week."):
    return client.post("/reviews", json={"rating": rating, "body": body}, headers=headers)


# --------------------------------------------------------------------------- #
# Writing one
# --------------------------------------------------------------------------- #


def test_a_review_is_stored_and_returned(client, auth, sns):
    r = review(client, auth, 4, "  Useful, and fast.  \n")
    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == {"id", "rating", "body", "created_at"}
    assert body["rating"] == 4 and body["body"] == "Useful, and fast."
    assert Z.match(body["created_at"])
    with SessionLocal() as db:
        row = db.execute(text("SELECT rating, body FROM reviews")).one()
    assert tuple(row) == (4, "Useful, and fast.")


def test_signed_out_is_401(client):
    r = client.post("/reviews", json={"rating": 5, "body": "x"})
    assert (r.status_code, r.json()) == (401, {"detail": "Not authenticated."})


@pytest.mark.parametrize(
    "payload, field",
    [
        ({"rating": 0, "body": "x"}, "rating"),
        ({"rating": 6, "body": "x"}, "rating"),
        ({"rating": "5", "body": "x"}, "rating"),
        ({"rating": 4.5, "body": "x"}, "rating"),
        ({"rating": True, "body": "x"}, "rating"),
        ({"rating": None, "body": "x"}, "rating"),
        ({"body": "x"}, "rating"),
        ({"rating": 5}, "body"),
        ({"rating": 5, "body": ""}, "body"),
        ({"rating": 5, "body": " \n\t "}, "body"),
        ({"rating": 5, "body": "x" * 2001}, "body"),
        ({"rating": 5, "body": "a\x00b"}, "body"),
        ({"rating": 5, "body": 42}, "body"),
        ({"rating": 5, "body": "x", "user_id": 2}, "user_id"),
        ({"rating": 5, "body": "x", "created_at": "2020-01-01T00:00:00Z"}, "created_at"),
    ],
)
def test_what_is_refused_names_the_field(client, auth, sns, payload, field):
    r = client.post("/reviews", json=payload, headers=auth)
    assert r.status_code == 422, r.text
    assert isinstance(r.json()["detail"], str) and r.json()["detail"].startswith(f"{field}:")
    with SessionLocal() as db:
        assert db.execute(text("SELECT count(*) FROM reviews")).scalar() == 0
    assert sns.published == []


def test_2000_characters_after_trimming_is_the_limit(client, auth, sns):
    assert review(client, auth, body="  " + "x" * 2000 + "  ").status_code == 201


# --------------------------------------------------------------------------- #
# Rate limit: per person and per address
# --------------------------------------------------------------------------- #


def test_five_a_day_per_person(client, auth, sns, limited):
    for _ in range(5):
        assert review(client, auth).status_code == 201
    r = review(client, auth)
    assert r.status_code == 429
    assert r.json() == {"detail": TOO_MANY}
    assert r.json()["detail"] == "You've sent a lot of reviews today. Try again tomorrow."
    assert 0 < int(r.headers["Retry-After"]) <= 86_400
    assert "Retry-After" in r.headers.get("access-control-expose-headers", "Retry-After")
    with SessionLocal() as db:
        assert db.execute(text("SELECT count(*) FROM reviews")).scalar() == 5
    assert len(sns.published) == 5


def test_the_address_is_limited_too(client, sns, limited):
    """Five accounts from one address do not get five reviews each."""
    written = 0
    for n in range(3):
        headers = register(client, email=f"person{n}@example.com")
        for _ in range(2):
            written += review(client, headers).status_code == 201
    assert written == 5


def test_a_refused_form_does_not_use_up_the_day(client, auth, sns, limited):
    for _ in range(10):
        assert client.post("/reviews", json={"rating": 9}, headers=auth).status_code == 422
    assert review(client, auth).status_code == 201


def test_the_limit_is_configurable(client, auth, sns, limited, monkeypatch):
    monkeypatch.setattr(config, "REVIEW_RATE_LIMIT", "1/day")
    assert review(client, auth).status_code == 201
    assert review(client, auth).status_code == 429


# --------------------------------------------------------------------------- #
# The email
# --------------------------------------------------------------------------- #


def test_the_owner_is_emailed(client, sns, monkeypatch):
    monkeypatch.setattr(config, "SITE_URL", "https://step1careers.com")
    headers = register(client, email="ada@umd.edu", name="Ada Lovelace")
    r = review(client, headers, 4, "Line one.\nLine two.")
    assert r.status_code == 201
    assert len(sns.published) == 1
    sent = sns.published[0]
    assert sent["TopicArn"] == TOPIC
    assert sent["Subject"] == "StEP1 review: 4/5 from Ada Lovelace"
    message = sent["Message"]
    assert "Rating: 4/5" in message
    assert "> Line one.\n> Line two." in message
    assert "ada@umd.edu" in message
    assert "https://step1careers.com/admin" in message
    assert re.search(r"When: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC", message)


def test_without_a_name_the_subject_uses_the_email(client, sns):
    headers = register(client, email="noname@example.com", name="")
    review(client, headers, 3)
    assert sns.published[0]["Subject"] == "StEP1 review: 3/5 from noname@example.com"


def test_nothing_is_sent_without_a_topic(client, auth, monkeypatch, caplog):
    def must_not_be_called():
        raise AssertionError("SNS was reached with no topic configured")

    monkeypatch.setattr(notify, "_sns", must_not_be_called)
    monkeypatch.setattr(config, "NOTIFY_TOPIC_ARN", "")
    with caplog.at_level(logging.INFO, logger="app.services.notify"):
        assert review(client, auth).status_code == 201
    assert "NOTIFY_TOPIC_ARN is empty" in caplog.text


@pytest.mark.parametrize(
    "error",
    [
        ConnectionError("no route to host"),
        TimeoutError("read timed out"),
        RuntimeError("AuthorizationError: not allowed to publish"),
    ],
)
def test_a_failed_email_is_logged_and_the_review_kept(client, auth, sns, caplog, error):
    sns.fail = error
    with caplog.at_level(logging.ERROR, logger="app.services.notify"):
        r = review(client, auth)
    assert r.status_code == 201
    assert "could not publish to SNS" in caplog.text
    with SessionLocal() as db:
        assert db.execute(text("SELECT count(*) FROM reviews")).scalar() == 1


def test_botocore_errors_are_caught_too(client, auth, sns):
    from botocore.exceptions import ClientError, EndpointConnectionError

    sns.fail = ClientError({"Error": {"Code": "AuthorizationError"}}, "Publish")
    assert review(client, auth).status_code == 201
    sns.fail = EndpointConnectionError(endpoint_url="https://sns.us-east-1.amazonaws.com")
    assert review(client, auth).status_code == 201


def test_what_the_reviewer_typed_never_reaches_the_subject(client, sns):
    """The name is theirs to choose, and so is the review. The subject gets
    a cleaned, shortened name and a number; the review goes only in the body."""
    name = "Évil\r\nBcc: victim@example.com\x07 " + "ñ" * 30
    headers = register(client, email="evil@example.com", name=name)
    review(client, headers, 1, "SUBJECT-INJECTION\r\nBcc: someone@example.com")
    subject = sns.published[0]["Subject"]
    assert subject.isascii() and subject.isprintable()
    assert "\n" not in subject and "\r" not in subject
    assert len(subject) < 100
    assert subject.startswith("StEP1 review: 1/5 from Evil Bcc: victim@example.com")
    assert "SUBJECT-INJECTION" not in subject
    # In the body, quoted line by line, so it cannot pass for the email's own text.
    assert "> SUBJECT-INJECTION\n> Bcc: someone@example.com" in sns.published[0]["Message"]


def test_subject_and_body_helpers_directly():
    assert notify.ascii_line("  Zoë\tO'Brien \n", 60) == "Zoe O'Brien"
    assert notify.ascii_line("日本語", 60) == ""
    assert (
        notify.review_subject(5, "日本語", "x@example.com")
        == "StEP1 review: 5/5 from x@example.com"
    )
    assert notify.review_subject(5, None, "") == "StEP1 review: 5/5 from someone"
    long = notify.review_subject(2, "A" * 500, "a@example.com")
    assert len(long) <= notify.SUBJECT_MAX


# --------------------------------------------------------------------------- #
# The admin list
# --------------------------------------------------------------------------- #


def test_me_says_who_is_admin(client, owner, auth):
    assert client.get("/me", headers=owner).json()["is_admin"] is True
    assert client.get("/me", headers=auth).json()["is_admin"] is False


def test_admin_emails_are_compared_lowercased(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_EMAILS", frozenset({OWNER}))
    headers = register(client, email="Owner@Example.COM")
    assert client.get("/me", headers=headers).json()["is_admin"] is True
    assert client.get("/admin/reviews", headers=headers).status_code == 200


def test_nobody_is_admin_by_default(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_EMAILS", frozenset())
    headers = register(client, email=OWNER)
    assert client.get("/me", headers=headers).json()["is_admin"] is False
    assert client.get("/admin/reviews", headers=headers).json() == NOT_FOUND


def test_the_admin_sees_every_review_newest_first(client, owner, sns):
    ada = register(client, email="ada@umd.edu", name="Ada")
    bob = register(client, email="bob@umd.edu", name=None)
    review(client, ada, 5, "first")
    review(client, bob, 2, "second")
    review(client, ada, 4, "third")

    r = client.get("/admin/reviews", headers=owner)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"items", "page", "total", "has_more", "average_rating"}
    assert [i["body"] for i in body["items"]] == ["third", "second", "first"]
    assert body["items"][0]["user"] == {"email": "ada@umd.edu", "display_name": "Ada"}
    assert body["items"][1]["user"] == {"email": "bob@umd.edu", "display_name": None}
    assert set(body["items"][0]) == {"id", "rating", "body", "created_at", "user"}
    assert all(Z.match(i["created_at"]) for i in body["items"])
    assert (body["page"], body["total"], body["has_more"]) == (1, 3, False)
    assert body["average_rating"] == 3.7  # 11 / 3, to one decimal


def test_pages(client, owner, sns):
    ada = register(client, email="ada@umd.edu")
    for n in range(5):
        review(client, ada, 3, f"review {n}")
    first = client.get("/admin/reviews?page=1&page_size=2", headers=owner).json()
    last = client.get("/admin/reviews?page=3&page_size=2", headers=owner).json()
    past = client.get("/admin/reviews?page=4&page_size=2", headers=owner).json()
    assert [i["body"] for i in first["items"]] == ["review 4", "review 3"]
    assert first["has_more"] is True and first["total"] == 5
    assert [i["body"] for i in last["items"]] == ["review 0"] and last["has_more"] is False
    assert past["items"] == [] and past["total"] == 5
    for bad in ("page=0", "page_size=0", "page_size=101", "page=x"):
        assert client.get(f"/admin/reviews?{bad}", headers=owner).status_code == 422


def test_no_reviews_yet(client, owner):
    body = client.get("/admin/reviews", headers=owner).json()
    assert body == {"items": [], "page": 1, "total": 0, "has_more": False, "average_rating": None}


def test_to_anyone_else_the_admin_route_is_not_there(client, owner, auth):
    """A non-admin, a signed-out caller and a bad token all get exactly what
    a path that does not exist gets, whatever method or query they try."""
    nowhere = client.get("/admin/nothing-here")
    assert (nowhere.status_code, nowhere.json()) == (404, NOT_FOUND)
    attempts = [
        ("GET", "/admin/reviews", auth),
        ("GET", "/admin/reviews?page=nonsense&page_size=-1", auth),
        ("GET", "/admin/reviews", {}),
        ("GET", "/admin/reviews", {"Authorization": "Bearer not-a-token"}),
        ("POST", "/admin/reviews", auth),
        ("DELETE", "/admin/reviews", owner),
        ("PUT", "/admin/reviews", {}),
    ]
    for method, path, headers in attempts:
        r = client.request(method, path, headers=headers)
        label = f"{method} {path} {'signed in' if headers else 'signed out'}"
        assert (r.status_code, r.json()) == (404, NOT_FOUND), label
        assert "allow" not in {k.lower() for k in r.headers}, label


def test_deleting_an_account_deletes_its_reviews(client, owner, sns):
    ada = register(client, email="ada@umd.edu", password="correct-horse")
    bob = register(client, email="bob@umd.edu")
    review(client, ada, 1, "ada's")
    review(client, bob, 5, "bob's")
    gone = client.request("DELETE", "/me", json={"password": "correct-horse"}, headers=ada)
    assert gone.status_code == 204
    body = client.get("/admin/reviews", headers=owner).json()
    assert [i["body"] for i in body["items"]] == ["bob's"]
    assert body["total"] == 1 and body["average_rating"] == 5.0


# --------------------------------------------------------------------------- #
# Cognito: the address must be the token's, and verified
# --------------------------------------------------------------------------- #


@pytest.fixture()
def cognito_pool(monkeypatch):
    from tests import test_cognito as tc

    stub = tc.Pool()
    monkeypatch.setattr(config, "AUTH_MODE", "cognito")
    monkeypatch.setattr(config, "AWS_REGION", tc.REGION)
    monkeypatch.setattr(config, "COGNITO_USER_POOL_ID", tc.POOL)
    monkeypatch.setattr(config, "COGNITO_APP_CLIENT_ID", tc.CLIENT)
    monkeypatch.setattr(config, "COGNITO_ISSUER", tc.ISSUER)
    monkeypatch.setattr(config, "COGNITO_JWKS_URL", stub.url)
    monkeypatch.setattr(config, "COGNITO_JWKS_PATH", "")
    monkeypatch.setattr(config, "ADMIN_EMAILS", frozenset({OWNER}))
    cognito.forget_keys()
    yield tc
    stub.stop()
    cognito.forget_keys()


def test_cognito_admin_needs_a_verified_address(client, cognito_pool):
    tc = cognito_pool
    verified = tc.bearer(tc.token(sub="sub-owner", email=OWNER))
    unverified = tc.bearer(tc.token(sub="sub-other", email="OWNER@example.com",
                                    email_verified=False))  # fmt: skip
    as_string = tc.bearer(tc.token(sub="sub-owner", email=OWNER, email_verified="true"))

    assert client.get("/me", headers=verified).json()["is_admin"] is True
    assert client.get("/admin/reviews", headers=verified).status_code == 200
    assert client.get("/me", headers=as_string).json()["is_admin"] is True

    # Not verified: not an admin, and the admin route is not there for them.
    assert client.get("/me", headers=unverified).status_code in (200, 409)
    r = client.get("/admin/reviews", headers=unverified)
    assert (r.status_code, r.json()) == (404, NOT_FOUND)


def test_cognito_reviewer_is_emailed_about(client, cognito_pool, sns):
    tc = cognito_pool
    headers = tc.bearer(tc.token(sub="sub-ada", email="ada@umd.edu"))
    r = review(client, headers, 5, "Great.")
    assert r.status_code == 201
    assert sns.published[0]["Subject"] == "StEP1 review: 5/5 from Ada Lovelace"
    assert "ada@umd.edu" in sns.published[0]["Message"]
