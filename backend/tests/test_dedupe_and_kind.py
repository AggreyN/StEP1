"""One job shown once across lists; internships and new-grad roles kept apart
by what each student is looking for."""

from __future__ import annotations

from dataclasses import replace

from app.database import SessionLocal
from app.models import Posting
from app.sources import simplify
from app.sources.backfill import ingest
from app.sources.base import NormalizedPosting, Source
from tests.conftest import make_row, onboard, register


class Fixed(Source):
    def __init__(self, name: str, rows: list[NormalizedPosting]):
        self.name = name
        self.rows = rows

    def fetch(self):
        return self.rows


def posting(
    source: str, source_id: str, url: str, title="Software Engineer Intern", kind="internship"
):
    row = simplify.normalize_row(make_row(source_id, title, "Acme"))
    return replace(row, source=source, url=url, kind=kind)


def load(source: str, *rows: NormalizedPosting) -> None:
    with SessionLocal() as db:
        result = ingest(db, Fixed(source, list(rows)), postings=list(rows))
    assert result.error is None, result.error


def feed_ids(client, headers) -> list[str]:
    return sorted(
        i["id"] for i in client.get("/feed?page_size=100", headers=headers).json()["items"]
    )


def test_the_same_url_is_one_job_and_the_structured_list_wins(client):
    load("speedyapply_ai", posting("speedyapply_ai", "x1", "https://jobs.acme.com/1?utm_source=sa"))
    load("simplify", posting("simplify", "s1", "https://www.jobs.acme.com/1/"))
    headers = register(client)
    onboard(client, headers)
    assert feed_ids(client, headers) == ["simplify:s1"]
    assert client.get("/stats").json()["active_postings"] == 1
    # The other copy is still kept, and still reachable by its own id.
    assert client.get("/postings/speedyapply_ai:x1", headers=headers).status_code == 200


def test_the_same_title_across_lists_is_one_job(client):
    load("simplify", posting("simplify", "s1", "https://jobs.acme.com/1"))
    load("jobright_data", posting("jobright_data", "j1", "https://jobright.ai/jobs/info/j1"))
    headers = register(client)
    onboard(client, headers)
    assert feed_ids(client, headers) == ["simplify:s1"]


def test_the_same_title_within_one_list_is_two_jobs(client):
    load(
        "simplify",
        posting("simplify", "s1", "https://jobs.acme.com/1"),
        posting("simplify", "s2", "https://jobs.acme.com/2"),
    )
    headers = register(client)
    onboard(client, headers)
    assert feed_ids(client, headers) == ["simplify:s1", "simplify:s2"]


def test_when_the_shown_copy_closes_another_takes_its_place(client):
    load("speedyapply_ai", posting("speedyapply_ai", "x1", "https://jobs.acme.com/1"))
    load("simplify", posting("simplify", "s1", "https://jobs.acme.com/1"))
    load("simplify", replace(posting("simplify", "s1", "https://jobs.acme.com/1"), active=False))
    headers = register(client)
    onboard(client, headers)
    assert feed_ids(client, headers) == ["speedyapply_ai:x1"]
    with SessionLocal() as db:
        shown = db.query(Posting).filter(Posting.source_id == "x1").one()
        assert shown.canonical_id == shown.id


def test_saving_two_copies_saves_one_job(client):
    load("speedyapply_ai", posting("speedyapply_ai", "x1", "https://jobs.acme.com/1"))
    load("simplify", posting("simplify", "s1", "https://jobs.acme.com/1"))
    headers = register(client)
    onboard(client, headers)
    client.post("/saved/speedyapply_ai:x1", headers=headers)
    client.post("/saved/simplify:s1", headers=headers)
    body = client.get("/saved", headers=headers).json()
    assert body["total"] == 1 and [i["id"] for i in body["items"]] == ["simplify:s1"]


# --------------------------------------------------------------------------- #
# Internship or new grad
# --------------------------------------------------------------------------- #


def board():
    load(
        "simplify",
        posting("simplify", "intern", "https://jobs.acme.com/intern"),
        posting("simplify", "grad", "https://jobs.acme.com/grad", title="Software Engineer I",
                kind="new_grad"),
    )  # fmt: skip


def test_looking_for_defaults_to_internships(client):
    board()
    headers = register(client)
    onboard(client, headers)
    assert client.get("/profile", headers=headers).json()["looking_for"] == ["internship"]
    assert feed_ids(client, headers) == ["simplify:intern"]
    item = client.get("/feed", headers=headers).json()["items"][0]
    assert item["kind"] == "internship" and item["reasons"]


def test_new_grads_see_new_grad_roles(client):
    board()
    headers = register(client)
    onboard(client, headers, looking_for=["new_grad"])
    assert feed_ids(client, headers) == ["simplify:grad"]
    assert client.get("/feed", headers=headers).json()["items"][0]["kind"] == "new_grad"

    onboard(client, headers, looking_for=["new_grad", "internship", "new_grad"])
    assert client.get("/profile", headers=headers).json()["looking_for"] == [
        "internship",
        "new_grad",
    ]
    assert feed_ids(client, headers) == ["simplify:grad", "simplify:intern"]


def test_leaving_looking_for_out_keeps_it(client):
    board()
    headers = register(client)
    onboard(client, headers, looking_for=["new_grad"])
    body = client.get("/profile", headers=headers).json()
    from tests.conftest import PROFILE

    assert client.put("/profile", json=PROFILE, headers=headers).status_code == 202
    assert client.get("/profile", headers=headers).json()["looking_for"] == body["looking_for"]


def test_looking_for_must_name_a_kind(client, profile_body):
    headers = register(client)
    for bad in ([], ["contract"], "internship", [None]):
        r = client.put("/profile", json=profile_body | {"looking_for": bad}, headers=headers)
        assert r.status_code == 422, bad
        assert r.json()["detail"].startswith("looking_for"), r.json()


def test_the_feed_narrows_by_kind_within_looking_for(client):
    board()
    headers = register(client)
    onboard(client, headers, looking_for=["internship", "new_grad"])

    def ids(query):
        r = client.get(f"/feed?page_size=100&{query}", headers=headers)
        assert r.status_code == 200, r.text
        return sorted(i["id"] for i in r.json()["items"])

    assert ids("kind=new_grad") == ["simplify:grad"]
    assert ids("kind=internship") == ["simplify:intern"]
    assert client.get("/feed?kind=contract", headers=headers).status_code == 422
    # Narrowing never widens: someone looking only for internships asking for
    # new-grad roles gets none.
    onboard(client, headers, looking_for=["internship"])
    assert ids("kind=new_grad") == []
