"""No client can set a field the server owns.

Two defences, both tested. No route unpacks a request body into a model, so
an undeclared field has nowhere to go; and every request model refuses
undeclared fields outright, with a 422 that names the field.
"""

import ast
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.main import app
from app.schemas import RequestModel
from tests.conftest import PROFILE, api_routes, make_row, onboard, register, seed

APP = Path(__file__).resolve().parent.parent / "app"

# Fields the server decides. None may be accepted from a client, anywhere.
SERVER_OWNED = {
    "id": 999,
    "user_id": 1,
    "status": "offer",
    "source": "system",
    "score": 100,
    "reasons": [],
    "profile_version": 99,
    "scores_version": 99,
    "onboarded_at": "2020-01-01T00:00:00Z",
    "created_at": "2020-01-01T00:00:00Z",
    "last_event_at": "2020-01-01T00:00:00Z",
    "password_hash": "$2b$12$abcdefghijklmnopqrstuv",
    "cognito_sub": "someone-else",
    "resume_s3_key": "resumes/1/0123456789ab-x.pdf",
    "resume_text": "injected",
    "resume_needs_ocr": False,
    "is_admin": True,
}


@pytest.fixture()
def me(client):
    seed([make_row("a"), make_row("b")])
    headers = register(client)
    onboard(client, headers)
    app_id = client.post(
        "/applications", json={"posting_id": "simplify:a"}, headers=headers
    ).json()["id"]
    return headers, app_id


def _bodies(app_id: int) -> dict[tuple[str, str], tuple[str, dict]]:
    """A valid body for every route that takes one."""
    return {
        ("POST", "/auth/register"): (
            "/auth/register",
            {"email": "new@example.com", "password": "correct-horse"},
        ),
        ("POST", "/auth/login"): (
            "/auth/login",
            {"email": "ada@umd.edu", "password": "correct-horse"},
        ),
        ("PUT", "/profile"): ("/profile", dict(PROFILE)),
        ("POST", "/profile/resume/presign"): (
            "/profile/resume/presign",
            {"filename": "resume.pdf", "content_type": "application/pdf", "size": 4096},
        ),
        ("POST", "/profile/resume/commit"): (
            "/profile/resume/commit",
            {"key": f"resumes/1/{'0' * 32}.pdf", "filename": "resume.pdf"},
        ),
        ("POST", "/applications"): ("/applications", {"posting_id": "simplify:b"}),
        ("POST", "/applications/{application_id}/events"): (
            f"/applications/{app_id}/events",
            {"kind": "acknowledged"},
        ),
        ("DELETE", "/me"): ("/me", {"password": "correct-horse"}),
        ("POST", "/reviews"): ("/reviews", {"rating": 5, "body": "Useful."}),
    }


def _body_model(route) -> type[BaseModel] | None:
    """The model a route reads its JSON body into, looking through
    `Model | None` for a body that may be omitted."""
    if route.body_field is None:
        return None
    annotation = route.body_field.field_info.annotation
    for candidate in (annotation, *getattr(annotation, "__args__", ())):
        if isinstance(candidate, type) and issubclass(candidate, BaseModel):
            return candidate
    return None


def _routes_with_a_json_body() -> set[tuple[str, str]]:
    return {key for key, route in api_routes(app).items() if _body_model(route) is not None}


def test_every_route_with_a_body_is_covered():
    assert _routes_with_a_json_body() == set(_bodies(1)), (
        "A route takes a JSON body that tests/test_field_tampering.py does not know about. "
        "Add a valid body for it to _bodies()."
    )


def _models_reachable(model: type[BaseModel], seen: set | None = None) -> set[type[BaseModel]]:
    seen = set() if seen is None else seen
    if model in seen:
        return seen
    seen.add(model)
    for info in model.model_fields.values():
        stack = [info.annotation]
        while stack:
            t = stack.pop()
            if isinstance(t, type) and issubclass(t, BaseModel):
                _models_reachable(t, seen)
            stack.extend(getattr(t, "__args__", ()))
    return seen


def test_every_request_model_refuses_unknown_fields():
    checked = set()
    for key in _routes_with_a_json_body():
        top = _body_model(api_routes(app)[key])
        for model in _models_reachable(top):
            assert issubclass(model, RequestModel), f"{model.__name__} (via {key})"
            assert model.model_config.get("extra") == "forbid", model.__name__
            checked.add(model.__name__)
    assert {"ProfileIn", "InterestIn", "EventIn", "RegisterIn", "DeleteAccountIn"} <= checked


@pytest.mark.parametrize("field", sorted(SERVER_OWNED))
@pytest.mark.parametrize("route", sorted(_bodies(1)), ids=lambda r: f"{r[0]} {r[1]}")
def test_server_owned_fields_are_refused(client, me, route, field):
    headers, app_id = me
    path, body = _bodies(app_id)[route]
    if field in body:
        pytest.skip(f"{field} is a declared field of this body")

    before = _everything(client, headers, app_id)
    r = client.request(route[0], path, json={**body, field: SERVER_OWNED[field]}, headers=headers)
    assert r.status_code == 422, f"{r.status_code} {r.text}"
    assert r.json() == {"detail": f"{field}: this field can't be set"}
    # Refused means refused: the valid part of the body was not applied either.
    assert _everything(client, headers, app_id) == before


def test_nested_objects_refuse_unknown_fields_too(client, me):
    headers, _ = me
    body = dict(PROFILE)
    body["interests"] = [
        {"role": "software", "rank": 1, "user_id": 1},
        {"role": "quant", "rank": 2},
        {"role": "security", "rank": 3},
    ]
    r = client.put("/profile", json=body, headers=headers)
    assert r.status_code == 422
    assert r.json() == {"detail": "interests[0].user_id: this field can't be set"}


def test_several_unknown_fields_are_all_named(client, me):
    headers, app_id = me
    r = client.post(
        f"/applications/{app_id}/events",
        json={"kind": "acknowledged", "source": "system", "status": "offer"},
        headers=headers,
    )
    assert r.status_code == 422
    assert r.json() == {
        "detail": "source: this field can't be set; status: this field can't be set"
    }


def test_what_the_server_decides_stays_decided(client, me):
    """The values themselves, after a legitimate request: the caller, the
    derived status, and 'manual' as the source of a user's own event."""
    headers, app_id = me
    detail = client.post(
        f"/applications/{app_id}/events",
        json={"kind": "acknowledged", "note": "they wrote back"},
        headers=headers,
    ).json()
    assert detail["status"] == "acknowledged"
    assert {e["source"] for e in detail["events"]} == {"manual"}
    assert client.get("/profile", headers=headers).json()["profile_version"] == 1


def _everything(client, headers, app_id) -> tuple:
    return (
        client.get("/me", headers=headers).json(),
        client.get("/profile", headers=headers).json(),
        client.get("/applications", headers=headers).json(),
        client.get(f"/applications/{app_id}", headers=headers).json(),
        client.post(
            "/auth/login", json={"email": "new@example.com", "password": "correct-horse"}
        ).status_code,
    )


# --------------------------------------------------------------------------- #
# The first defence, checked in the source
# --------------------------------------------------------------------------- #


def test_no_request_body_is_unpacked_into_anything():
    """`Model(**body.model_dump())` is how a field nobody declared ends up in
    a column. Nothing in a route or service may unpack a mapping into a call,
    or copy attributes by name from a loop."""
    offenders = []
    for path in sorted([*(APP / "routes").glob("*.py"), *(APP / "services").glob("*.py")]):
        for node in ast.walk(ast.parse(path.read_text())):
            where = f"{path.relative_to(APP.parent)}:{getattr(node, 'lineno', '?')}"
            if isinstance(node, ast.Call):
                if any(k.arg is None for k in node.keywords):
                    offenders.append(f"{where} unpacks ** into a call")
                name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                if name in {"model_dump", "dict", "setattr"}:
                    offenders.append(f"{where} calls {name}()")
    assert offenders == []
