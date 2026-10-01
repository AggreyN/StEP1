"""GET /feed, /feed/status, /postings/{id}, and /saved over HTTP."""

from urllib.parse import quote

import pytest

from app.services import feed_state
from tests.conftest import make_row, onboard, register, seed

POSTING_KEYS = {
    "id", "title", "company", "roles", "role_labels", "locations", "is_remote", "terms",
    "degrees", "url", "date_posted", "salary", "source", "score", "reasons", "saved",
    "application", "kind",
}  # fmt: skip

BOARD = [
    make_row("dc-swe", "Software Engineer Intern", "Palantir", days_ago=2),
    make_row("dc-py", "Python Software Engineer Intern", "Leidos", days_ago=5,
             locations=("Arlington, VA",)),
    make_row("nyc-ml", "Machine Learning Intern", "Two Sigma", days_ago=10,
             locations=("NYC",), category="AI/ML/Data"),
    make_row("remote-data", "Data Analyst Intern", "Stripe", days_ago=1,
             locations=("Remote in USA",), category="AI/ML/Data"),
    make_row("tx-hw", "Hardware Engineering Intern", "Dell", days_ago=4,
             locations=("Austin, TX",), category="Hardware"),
    make_row("fall-swe", "Software Engineer Intern", "Palantir", days_ago=6,
             terms=("Fall 2027",)),
    make_row("old-term", "Software Engineer Intern", "Oldco", terms=("Summer 2026",)),
    make_row("grad-only", "Research Scientist Intern", "Labs", degrees=("PhD",)),
    make_row("closed", "Software Engineer Intern", "Closedco", active=False),
    make_row("hidden", "Software Engineer Intern", "Hiddenco", is_visible=False),
    make_row("ancient", "Software Engineer Intern", "Ancientco", days_ago=200),
]  # fmt: skip
IN_FEED = {"dc-swe", "dc-py", "nyc-ml", "remote-data", "tx-hw", "fall-swe"}


@pytest.fixture()
def board(client):
    seed(BOARD)
    headers = register(client)
    onboard(client, headers)
    return headers


def ids(body):
    return [item["id"].removeprefix("simplify:") for item in body["items"]]


def test_feed_requires_onboarding(client, auth):
    for path in ("/feed", "/feed/status"):
        r = client.get(path, headers=auth)
        assert r.status_code == 409
        assert r.json() == {"detail": "Complete onboarding first"}
    assert client.get("/feed").status_code == 401


def test_status_is_ready_after_the_build(client, board):
    r = client.get("/feed/status", headers=board)
    assert r.status_code == 200
    assert r.json() == {"state": "ready", "pct": 100, "step": "Ranking your matches"}


def test_status_reports_a_build_in_flight(client, board):
    feed_state._set(1, 40, feed_state.step_scan(4139))
    try:
        r = client.get("/feed/status", headers=board)
        assert r.json() == {
            "state": "building", "pct": 40, "step": "Scanning 4,139 open internships",
        }  # fmt: skip
    finally:
        feed_state._clear(1)


def test_status_recovers_when_the_background_build_was_lost(client, monkeypatch):
    """A restarted process loses its in-memory progress and its task. The
    next poll must notice the stale cache and build it, not spin forever."""
    seed(BOARD)
    headers = register(client)
    monkeypatch.setattr(feed_state, "run_build", lambda user_id: feed_state._clear(user_id))
    onboard(client, headers)
    assert client.get("/feed/status", headers=headers).json()["state"] == "ready"
    assert client.get("/feed", headers=headers).json()["total"] == len(IN_FEED)


def test_feed_shape_and_hard_filters(client, board):
    body = client.get("/feed", headers=board).json()
    assert set(body) == {"items", "page", "total", "has_more"}
    assert (body["page"], body["total"], body["has_more"]) == (1, len(IN_FEED), False)
    assert set(ids(body)) == IN_FEED  # closed, hidden, ancient, wrong term, PhD-only are gone
    for item in body["items"]:
        assert set(item) == POSTING_KEYS
        assert set(item["company"]) == {"name", "url"}
        assert isinstance(item["score"], int) and 0 <= item["score"] <= 100
        assert item["reasons"], item["id"]
        assert all(set(r) == {"code", "label", "detail"} for r in item["reasons"])
        assert item["salary"] is None and item["saved"] is False and item["application"] is None
        assert item["date_posted"].endswith("Z")
        assert len(item["roles"]) == len(item["role_labels"])


def test_sort_score_is_best_match_first_then_newest(client, board):
    items = client.get("/feed?sort=score", headers=board).json()["items"]
    keys = [(-i["score"], i["date_posted"]) for i in items]
    assert [k[0] for k in keys] == sorted(k[0] for k in keys)
    for a, b in zip(items, items[1:], strict=False):
        if a["score"] == b["score"]:
            assert a["date_posted"] >= b["date_posted"]
    # No resume on file, so skills can't be earned by anything; between the
    # two DC software roles the fresher one wins.
    top = items[0]
    assert top["id"] == "simplify:dc-swe"
    assert [r["code"] for r in top["reasons"]] == ["role_rank", "location", "term", "fresh"]
    assert top["reasons"][0]["label"] == "Matches your #1 field"
    assert top["reasons"][3]["label"] == "Posted 2 days ago"


def test_top_posting_has_skill_reason_when_resume_has_the_skill(client, board, profile_body):
    profile_body["skills"] = ["Python", "SQL"]
    client.put("/profile", json=profile_body, headers=board)
    top = client.get("/feed?sort=score", headers=board).json()["items"][0]
    assert top["id"] == "simplify:dc-py"
    assert {"code": "skills", "label": "1 of your skills", "detail": "Python"} in top["reasons"]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("roles=hardware", {"tx-hw"}),
        ("roles=hardware,data_analytics", {"tx-hw", "remote-data"}),
        ("location=arlington", {"dc-py"}),
        ("location=VA", {"dc-py"}),
        ("location=%25", set()),  # a literal %, not a wildcard
        ("term=Fall 2027", {"fall-swe"}),
        ("remote=true", {"remote-data"}),
        ("remote=false", IN_FEED),
        ("roles=software&location=washington", {"dc-swe", "fall-swe"}),
        ("min_score=101", None),
    ],
)
def test_feed_filters(client, board, query, expected):
    r = client.get(f"/feed?{query}", headers=board)
    if expected is None:
        assert r.status_code == 422
        return
    assert r.status_code == 200, r.text
    assert set(ids(r.json())) == expected
    assert r.json()["total"] == len(expected)


def test_min_score_filter(client, board):
    items = client.get("/feed", headers=board).json()["items"]
    cut = items[2]["score"]
    body = client.get(f"/feed?min_score={cut}", headers=board).json()
    assert all(i["score"] >= cut for i in body["items"])
    assert body["total"] == sum(1 for i in items if i["score"] >= cut)


def test_pagination(client, board):
    everything = ids(client.get("/feed", headers=board).json())
    seen = []
    for page in (1, 2, 3):
        body = client.get(f"/feed?page={page}&page_size=2", headers=board).json()
        assert body["page"] == page and body["total"] == 6
        assert body["has_more"] == (page < 3)
        seen += ids(body)
    assert seen == everything
    assert client.get("/feed?page=9&page_size=2", headers=board).json()["items"] == []


@pytest.mark.parametrize("query", ["page=0", "page_size=0", "page_size=101", "roles=astrology"])
def test_bad_query_params_are_422_with_flat_detail(client, board, query):
    r = client.get(f"/feed?{query}", headers=board)
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str)


# --------------------------------------------------------------------------- #
# Ordering
# --------------------------------------------------------------------------- #

# By age in days: remote-data 1, dc-swe 2, tx-hw 4, dc-py 5, fall-swe 6, nyc-ml 10.
NEWEST_FIRST = ["remote-data", "dc-swe", "tx-hw", "dc-py", "fall-swe", "nyc-ml"]


def test_default_order_is_newest_first(client, board):
    default = client.get("/feed", headers=board).json()
    assert ids(default) == NEWEST_FIRST
    dates = [i["date_posted"] for i in default["items"]]
    assert dates == sorted(dates, reverse=True)
    assert client.get("/feed?sort=recent", headers=board).json() == default
    # Still scored: the order changed, not what each card carries.
    assert all(isinstance(i["score"], int) and i["reasons"] for i in default["items"])


def test_the_two_orders_differ_only_in_order(client, board):
    recent = client.get("/feed?sort=recent", headers=board).json()
    score = client.get("/feed?sort=score", headers=board).json()
    assert ids(recent) != ids(score)
    assert sorted(ids(recent)) == sorted(ids(score))
    assert (recent["total"], recent["has_more"]) == (score["total"], score["has_more"])
    by_id = {i["id"]: i for i in score["items"]}
    assert all(by_id[i["id"]] == i for i in recent["items"])


@pytest.mark.parametrize(
    "query",
    ["roles=software", "location=washington", "remote=true", "term=Fall 2027", "min_score=60",
     "roles=software,hardware&min_score=50", "page_size=2", "page=2&page_size=4"],
)  # fmt: skip
def test_filters_and_paging_agree_under_both_orders(client, board, query):
    recent = client.get(f"/feed?{query}&sort=recent", headers=board).json()
    score = client.get(f"/feed?{query}&sort=score", headers=board).json()
    for key in ("page", "total", "has_more"):
        assert recent[key] == score[key], key
    assert len(recent["items"]) == len(score["items"])
    if "page" not in query:  # a filter alone selects the same set either way
        assert sorted(ids(recent)) == sorted(ids(score))
    dates = [i["date_posted"] for i in recent["items"]]
    assert dates == sorted(dates, reverse=True)
    scores = [i["score"] for i in score["items"]]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.parametrize("bad", ["newest", "SCORE", "date_posted", "", "recent,score"])
def test_unknown_sort_is_422(client, board, bad):
    r = client.get(f"/feed?sort={bad}", headers=board)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, str)
    assert detail.startswith("sort:") and "'recent'" in detail and "'score'" in detail


def test_undated_postings_sort_last_when_newest_first(client):
    seed(
        [
            make_row("old", days_ago=40),
            make_row("undated-a", days_ago=None),
            make_row("new", days_ago=1),
            make_row("undated-b", days_ago=None),
        ]
    )
    headers = register(client)
    onboard(client, headers)
    body = client.get("/feed", headers=headers).json()
    assert ids(body)[:2] == ["new", "old"]
    assert sorted(ids(body)[2:]) == ["undated-a", "undated-b"]
    assert [i["date_posted"] for i in body["items"]] == [
        body["items"][0]["date_posted"], body["items"][1]["date_posted"], None, None,
    ]  # fmt: skip

    # Best match first: an undated posting is not charged for freshness, so it
    # can outrank a dated one. Among equal scores the dated ones come first.
    by_score = client.get("/feed?sort=score", headers=headers).json()["items"]
    keys = [(-i["score"], i["date_posted"] is None) for i in by_score]
    assert keys == sorted(keys)


@pytest.mark.parametrize("sort", ["recent", "score"])
def test_paging_is_stable_when_everything_ties(client, sort):
    """23 postings with the same second of posting and the same score. Only
    the final id key separates them; without it Postgres is free to order ties
    differently on each page, repeating some postings and dropping others."""
    import time

    same_second = int(time.time()) - 3 * 86_400
    seed([make_row(f"tie-{n:02d}", posted=same_second) for n in range(23)])
    headers = register(client)
    onboard(client, headers)

    whole = client.get(f"/feed?sort={sort}&page_size=100", headers=headers).json()
    assert whole["total"] == 23
    assert len({i["score"] for i in whole["items"]}) == 1
    assert len({i["date_posted"] for i in whole["items"]}) == 1

    paged = []
    for page in range(1, 6):
        body = client.get(f"/feed?sort={sort}&page={page}&page_size=5", headers=headers).json()
        assert (body["page"], body["total"], body["has_more"]) == (page, 23, page < 5)
        paged += ids(body)
    assert len(paged) == len(set(paged)) == 23
    assert paged == ids(whole)
    # And the same again on a second pass.
    again = client.get(f"/feed?sort={sort}&page=3&page_size=5", headers=headers).json()
    assert ids(again) == paged[10:15]


def test_profile_change_rescores(client, board, profile_body):
    before = client.get("/feed?sort=score", headers=board).json()
    profile_body["interests"] = [
        {"role": "hardware", "rank": 1},
        {"role": "data_analytics", "rank": 2},
        {"role": "quant", "rank": 3},
    ]
    profile_body["preferred_locations"] = ["Austin, TX"]
    client.put("/profile", json=profile_body, headers=board)
    after = client.get("/feed?sort=score", headers=board).json()
    assert before["items"][0]["id"] != after["items"][0]["id"]
    assert after["items"][0]["id"] == "simplify:tx-hw"


def test_new_postings_appear_after_the_next_ingest(client, board):
    assert client.get("/feed", headers=board).json()["total"] == 6
    seed([*BOARD, make_row("brand-new", "Software Engineer Intern", "Newco", days_ago=0)])
    body = client.get("/feed", headers=board).json()
    assert body["total"] == 7 and "brand-new" in ids(body)


def test_a_posting_that_closes_leaves_the_feed(client, board):
    seed([r for r in BOARD if r["id"] != "dc-swe"])  # dropped upstream -> deactivated
    assert "dc-swe" not in ids(client.get("/feed", headers=board).json())


# --------------------------------------------------------------------------- #
# /postings/{id}
# --------------------------------------------------------------------------- #


def test_get_posting(client, board):
    r = client.get("/postings/simplify:dc-swe", headers=board)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == POSTING_KEYS
    assert body["company"] == {"name": "Palantir", "url": "https://simplify.jobs/c/Palantir"}
    assert body["roles"] == ["software"] and body["role_labels"] == ["Software Engineering"]
    assert isinstance(body["score"], int) and body["reasons"]
    # The frontend URL-encodes the id.
    encoded = client.get(f"/postings/{quote('simplify:dc-swe', safe='')}", headers=board)
    assert encoded.json() == body


def test_posting_outside_the_feed_has_no_score(client, board):
    body = client.get("/postings/simplify:closed", headers=board).json()
    assert body["score"] is None and body["reasons"] == []


@pytest.mark.parametrize("bad", ["simplify:nope", "nocolon", "unknown:dc-swe", ":"])
def test_unknown_posting_is_404(client, board, bad):
    r = client.get(f"/postings/{bad}", headers=board)
    assert r.status_code == 404
    assert isinstance(r.json()["detail"], str)


# --------------------------------------------------------------------------- #
# /saved
# --------------------------------------------------------------------------- #


def test_save_and_unsave_are_idempotent(client, board):
    for _ in range(2):
        r = client.post("/saved/simplify:nyc-ml", headers=board)
        assert r.status_code == 204 and r.content == b""
    client.post("/saved/simplify:tx-hw", headers=board)

    body = client.get("/saved", headers=board).json()
    assert set(body) == {"items", "page", "total", "has_more"}
    assert ids(body) == ["tx-hw", "nyc-ml"]  # newest saved first
    assert all(i["saved"] for i in body["items"])
    assert all(set(i) == POSTING_KEYS for i in body["items"])

    feed = {i["id"]: i["saved"] for i in client.get("/feed", headers=board).json()["items"]}
    assert feed["simplify:nyc-ml"] is True and feed["simplify:dc-swe"] is False

    for _ in range(2):
        assert client.delete("/saved/simplify:nyc-ml", headers=board).status_code == 204
    assert ids(client.get("/saved", headers=board).json()) == ["tx-hw"]
    assert client.post("/saved/simplify:nope", headers=board).status_code == 404


def test_saved_is_per_user(client, board):
    client.post("/saved/simplify:nyc-ml", headers=board)
    other = register(client, email="grace@umd.edu")
    assert client.get("/saved", headers=other).json()["total"] == 0


def test_saving_raises_the_companys_other_postings(client, board):
    def palantir():
        items = client.get("/feed", headers=board).json()["items"]
        return {i["id"].removeprefix("simplify:"): i for i in items if "swe" in i["id"]}

    before = palantir()
    client.post("/saved/simplify:dc-swe", headers=board)
    after = palantir()
    # The sibling role gains the company signal; the saved role itself doesn't.
    assert after["fall-swe"]["score"] > before["fall-swe"]["score"]
    assert after["fall-swe"]["reasons"][-1] == {
        "code": "company", "label": "You saved another role here", "detail": "Palantir",
    }  # fmt: skip
    assert after["dc-swe"]["score"] == before["dc-swe"]["score"]

    client.delete("/saved/simplify:dc-swe", headers=board)
    assert palantir()["fall-swe"]["score"] == before["fall-swe"]["score"]


def test_a_reader_that_waited_on_a_build_does_not_repeat_it(client, board, db):
    """GET /feed arriving mid-build waits on the lock; once it has it, the
    scores are current and must not be computed a second time."""
    from app.models import Profile
    from app.services import matching

    profile = db.get(Profile, 1)
    stamp = profile.scores_computed_at
    assert matching.rescore(db, 1, unless=lambda p: feed_state.is_current(db, p)) == 0
    db.refresh(profile)
    assert profile.scores_computed_at == stamp
    assert matching.rescore(db, 1) == len(IN_FEED)  # unconditional still works
