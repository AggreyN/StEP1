"""Applications and the event timeline over HTTP."""

import pytest

from tests.conftest import make_row, onboard, register, seed

DETAIL_KEYS = {
    "id", "posting", "status", "applied_at", "last_event_at", "events", "next_transitions",
}  # fmt: skip


@pytest.fixture()
def board(client):
    seed(
        [
            make_row("a", "Software Engineer Intern", "Palantir"),
            make_row("b", "Data Analyst Intern", "Stripe", category="AI/ML/Data"),
            make_row("c", "Software Engineer Intern - Infra", "Palantir"),
        ]
    )
    headers = register(client)
    onboard(client, headers)
    return headers


def apply(client, headers, posting="simplify:a", **extra):
    return client.post("/applications", json={"posting_id": posting, **extra}, headers=headers)


def event(client, headers, app_id, kind, **extra):
    return client.post(
        f"/applications/{app_id}/events", json={"kind": kind, **extra}, headers=headers
    )


def test_create_application(client, board):
    r = apply(client, board)
    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == DETAIL_KEYS
    assert body["status"] == "applied"
    assert body["applied_at"] == body["events"][0]["occurred_at"]
    assert [(e["kind"], e["source"], e["note"]) for e in body["events"]] == [
        ("applied", "manual", None)
    ]
    assert set(body["events"][0]) == {"id", "kind", "occurred_at", "note", "source"}
    assert body["next_transitions"] == [
        "acknowledged", "oa_sent", "interview_scheduled", "rejected", "withdrawn",
    ]  # fmt: skip
    assert body["posting"]["id"] == "simplify:a"
    assert body["posting"]["application"] == {"id": body["id"], "status": "applied"}


def test_applied_at_can_be_backdated_but_not_in_the_future(client, board):
    r = apply(client, board, applied_at="2026-09-01T12:00:00Z")
    assert r.status_code == 201
    assert r.json()["applied_at"] == "2026-09-01T12:00:00Z"
    future = apply(client, board, posting="simplify:b", applied_at="2031-01-01T00:00:00Z")
    assert future.status_code == 422
    assert "future" in future.json()["detail"]
    assert client.get("/applications", headers=board).json()["items"][0]["posting"]["id"] == (
        "simplify:a"
    )


def test_duplicate_application_is_409(client, board):
    assert apply(client, board).status_code == 201
    r = apply(client, board)
    assert r.status_code == 409
    assert isinstance(r.json()["detail"], str)


def test_unknown_posting_is_404(client, board):
    assert apply(client, board, posting="simplify:nope").status_code == 404


def test_timeline_walk(client, board):
    app_id = apply(client, board, applied_at="2026-09-01T12:00:00Z").json()["id"]
    steps = [
        ("acknowledged", "2026-09-03T12:00:00Z"),
        ("interview_scheduled", "2026-09-10T12:00:00Z"),
    ]
    for kind, when in steps:
        r = event(client, board, app_id, kind, occurred_at=when, note=f"{kind}!")
        assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "interview_scheduled"
    assert body["next_transitions"] == ["interviewed", "rejected", "withdrawn"]
    assert [e["kind"] for e in body["events"]] == [
        "applied", "acknowledged", "interview_scheduled",
    ]  # fmt: skip
    assert body["events"][-1]["note"] == "interview_scheduled!"
    assert body["last_event_at"] == "2026-09-10T12:00:00Z"
    assert client.get(f"/applications/{app_id}", headers=board).json() == body


def test_illegal_transition_is_422_and_readable(client, board):
    app_id = apply(client, board).json()["id"]
    r = event(client, board, app_id, "offer")
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "Can't record 'offer' while the application is applied" in detail
    assert "acknowledged" in detail
    # Nothing was written.
    assert len(client.get(f"/applications/{app_id}", headers=board).json()["events"]) == 1


def test_ghosted_is_never_user_settable(client, board):
    app_id = apply(client, board).json()["id"]
    r = event(client, board, app_id, "ghosted")
    assert r.status_code == 422
    assert "automatically" in r.json()["detail"]


def test_unknown_kind_is_422(client, board):
    app_id = apply(client, board).json()["id"]
    r = event(client, board, app_id, "promoted_to_ceo")
    assert r.status_code == 422
    assert "unknown event kind" in r.json()["detail"]


def test_notes_are_always_allowed_and_never_change_status(client, board):
    app_id = apply(client, board).json()["id"]
    assert event(client, board, app_id, "withdrawn").status_code == 201
    r = event(client, board, app_id, "note", note="Took another offer")
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "withdrawn" and body["next_transitions"] == []
    assert body["events"][-1]["kind"] == "note"
    assert event(client, board, app_id, "acknowledged").status_code == 422
    assert event(client, board, app_id, "note").status_code == 422  # a note needs text


def test_outreach_sent_does_not_change_status(client, board):
    from app.database import SessionLocal
    from app.models import Application
    from app.services import timeline

    app_id = apply(client, board).json()["id"]
    with SessionLocal() as db:
        application = db.get(Application, app_id)
        timeline._append(
            db, application, kind="outreach_sent", occurred_at=timeline.datetime.now(timeline.UTC),
            note=None, source="system",
        )  # fmt: skip
        db.commit()
    assert client.get(f"/applications/{app_id}", headers=board).json()["status"] == "applied"


def test_list_is_newest_activity_first(client, board):
    first = apply(client, board, "simplify:a", applied_at="2026-09-01T12:00:00Z").json()["id"]
    second = apply(client, board, "simplify:b", applied_at="2026-09-05T12:00:00Z").json()["id"]
    body = client.get("/applications", headers=board).json()
    assert set(body) == {"items"}
    assert [i["id"] for i in body["items"]] == [second, first]
    assert set(body["items"][0]) == {"id", "posting", "status", "applied_at", "last_event_at"}

    event(client, board, first, "acknowledged", occurred_at="2026-09-09T12:00:00Z")
    body = client.get("/applications", headers=board).json()
    assert [i["id"] for i in body["items"]] == [first, second]
    assert body["items"][0]["status"] == "acknowledged"


def test_applications_are_private(client, board):
    app_id = apply(client, board).json()["id"]
    mallory = register(client, email="mallory@umd.edu")
    assert client.get(f"/applications/{app_id}", headers=mallory).status_code == 404
    assert event(client, mallory, app_id, "note", note="hi").status_code == 404
    assert client.get("/applications", headers=mallory).json() == {"items": []}


def test_feed_reflects_application_and_company_signal(client, board):
    app_id = apply(client, board, "simplify:a").json()["id"]
    event(client, board, app_id, "acknowledged")
    items = {i["id"]: i for i in client.get("/feed", headers=board).json()["items"]}
    assert items["simplify:a"]["application"] == {"id": app_id, "status": "acknowledged"}
    assert items["simplify:b"]["application"] is None
    # The other Palantir role now carries the company signal.
    assert items["simplify:c"]["reasons"][-1] == {
        "code": "company", "label": "You applied here before", "detail": "Palantir",
    }  # fmt: skip
