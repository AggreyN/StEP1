"""No SQL is built from strings, and no pattern or search term can carry
syntax of its own.

SQLAlchemy binds parameters, so injection needs someone to go around it:
an f-string in text(), a LIKE pattern that passes % through, a search term
handed to to_tsquery. The first half of this file makes each of those fail in
review, by reading the source. The second half throws hostile input at the
running API.
"""

import ast
import re
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models import Posting
from tests.conftest import make_row, onboard, register, seed

APP = Path(__file__).resolve().parent.parent / "app"
SOURCES = sorted(APP.rglob("*.py"))


def _calls(tree, *names):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", getattr(node.func, "id", None))
            if name in names:
                yield node


def _where(path, node) -> str:
    return f"{path.relative_to(APP.parent)}:{node.lineno}"


def test_the_source_walk_found_the_code():
    names = {p.name for p in SOURCES}
    assert {"feed.py", "matching.py", "backfill.py", "profile.py"} <= names
    assert sum(1 for p in SOURCES for _ in _calls(ast.parse(p.read_text()), "text")) >= 5


def test_raw_sql_is_always_a_literal():
    """text() takes a string constant and nothing else: no f-string, no +,
    no %, no .format(), no variable. Values go in as bound parameters."""
    offenders = []
    for path in SOURCES:
        for call in _calls(ast.parse(path.read_text()), "text"):
            if not call.args:
                continue
            arg = call.args[0]
            if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                offenders.append(f"{_where(path, call)} text({ast.unparse(arg)[:60]})")
    assert offenders == []


def test_nothing_is_executed_from_a_bare_string():
    offenders = []
    for path in SOURCES:
        for call in _calls(ast.parse(path.read_text()), "execute", "scalar", "scalars"):
            if call.args and isinstance(call.args[0], ast.JoinedStr | ast.BinOp | ast.Constant):
                offenders.append(f"{_where(path, call)} {ast.unparse(call.args[0])[:60]}")
    assert offenders == []


def test_every_like_pattern_declares_its_escape():
    """A LIKE without ESCAPE cannot have had its % and _ neutralised."""
    offenders, seen = [], 0
    for path in SOURCES:
        for call in _calls(ast.parse(path.read_text()), "like", "ilike", "notlike", "notilike"):
            seen += 1
            if not any(k.arg == "escape" for k in call.keywords):
                offenders.append(_where(path, call))
    assert seen >= 1 and offenders == []


def test_full_text_search_may_only_use_websearch_to_tsquery():
    """to_tsquery parses its argument as query syntax, so a stray & or :
    in a search box is a syntax error at best. websearch_to_tsquery accepts
    anything a person types. Nothing searches yet; when something does, this
    is the only way in."""
    offenders = []
    for path in SOURCES:
        for line_no, line in enumerate(path.read_text().splitlines(), 1):
            for found in re.findall(r"\w*to_tsquery", line):
                if found != "websearch_to_tsquery":
                    offenders.append(f"{path.relative_to(APP.parent)}:{line_no} {found}")
    assert offenders == []
    for path in SOURCES:
        for call in _calls(ast.parse(path.read_text()), "websearch_to_tsquery"):
            term = call.args[-1]
            assert not isinstance(term, ast.JoinedStr | ast.BinOp), _where(path, call)


# --------------------------------------------------------------------------- #
# Against the running API
# --------------------------------------------------------------------------- #

HOSTILE = [
    "'; DROP TABLE postings; --",
    "' OR '1'='1",
    "\\' OR 1=1 --",
    '" OR ""="',
    "1; SELECT pg_sleep(10)",
    "%' UNION SELECT password_hash FROM users --",
    "Robert'); DROP TABLE users;--",
    "\\x00",
    "%%%%",
    "____",
    "\\\\",
    "a' & 'b | !c:*",
]


@pytest.fixture()
def board(client, db):
    seed(
        [
            make_row("plain", locations=("Washington, DC",)),
            make_row("percent", locations=("100% Remote",)),
            make_row("underscore", locations=("Building_7, Austin, TX",)),
            make_row("backslash", locations=("Reston\\Herndon, VA",)),
        ]
    )
    headers = register(client)
    onboard(client, headers)
    return headers


def _ids(r):
    assert r.status_code == 200, r.text
    return sorted(i["id"].removeprefix("simplify:") for i in r.json()["items"])


@pytest.mark.parametrize(
    ("needle", "expected"),
    [
        ("%", ["percent"]),  # a literal percent sign, not "everything"
        ("_", ["underscore"]),  # a literal underscore, not "any one character"
        ("\\", ["backslash"]),
        ("100%", ["percent"]),
        ("g_7", ["underscore"]),
        ("%%", []),
        ("W_shington", []),  # would match with _ as a wildcard
        ("Wash%DC", []),  # would match with % as a wildcard
        ("washington", ["plain"]),
    ],
)
def test_location_filter_treats_wildcards_as_text(client, board, needle, expected):
    assert _ids(client.get("/feed", params={"location": needle}, headers=board)) == expected


@pytest.mark.parametrize("payload", HOSTILE)
def test_hostile_input_is_data_everywhere(client, board, db, payload):
    before = db.scalar(select(func.count()).select_from(Posting))

    for params in ({"location": payload}, {"term": payload}):
        r = client.get("/feed", params=params, headers=board)
        # Refused for its length, or searched for and not found. Never run.
        assert r.status_code in (200, 422), r.text
        assert r.status_code == 422 or r.json()["items"] == []
    assert client.get("/feed", params={"roles": payload}, headers=board).status_code == 422
    assert client.get(f"/postings/simplify:{payload}", headers=board).status_code in (404, 405)
    assert client.post("/saved/" + payload, headers=board).status_code in (404, 405)
    assert (
        client.post("/applications", json={"posting_id": payload}, headers=board).status_code == 404
    )
    assert client.post(
        "/auth/login", json={"email": "ada@umd.edu", "password": payload}
    ).status_code in (401, 422)

    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Posting)) == before
    assert client.get("/feed", headers=board).json()["total"] == 4


def test_hostile_text_is_stored_and_returned_verbatim(client, board):
    """Stored as the characters that were typed; nothing interprets them."""
    nasty = "O'Brien; DROP TABLE users; -- % _ \\"
    app_id = client.post(
        "/applications", json={"posting_id": "simplify:plain"}, headers=board
    ).json()["id"]
    r = client.post(
        f"/applications/{app_id}/events", json={"kind": "note", "note": nasty}, headers=board
    )
    assert r.status_code == 201
    assert r.json()["events"][-1]["note"] == nasty
    assert client.get("/me", headers=board).status_code == 200
