"""Profile contract: GET/PUT /profile and the ranked interests rules."""

import pytest

from tests.conftest import register

SIX_ROLES = ["software", "quant", "security", "research", "hardware", "design_ux"]


def test_get_profile_is_404_before_onboarding(client, auth):
    r = client.get("/profile", headers=auth)
    assert r.status_code == 404
    assert isinstance(r.json()["detail"], str)


def test_put_profile_returns_202_with_retry_after(client, auth, profile_body):
    r = client.put("/profile", json=profile_body, headers=auth)
    assert r.status_code == 202, r.text
    assert r.headers["retry-after"] == "1"
    assert r.json() == {"profile_version": 1, "state": "building"}
    assert client.get("/me", headers=auth).json()["onboarded"] is True


def test_get_profile_matches_contract_shape(client, auth, profile_body):
    client.put("/profile", json=profile_body, headers=auth)
    body = client.get("/profile", headers=auth).json()
    assert body == {
        "school": "University of Maryland, College Park",
        "major": "Information Science",
        "minor": "Data Science",
        "degree_level": "Bachelor's",
        "grad_year": 2028,
        "gpa": 3.7,
        "target_terms": ["Summer 2027"],
        "preferred_locations": ["Washington, DC", "New York, NY"],
        "remote_ok": True,
        "looking_for": ["internship"],
        "interests": [
            {"role": "software", "label": "Software Engineering", "rank": 1},
            {"role": "ai_ml_data", "label": "AI / ML / Data Science", "rank": 2},
            {"role": "data_analytics", "label": "Data & Business Analytics", "rank": 3},
        ],
        "resume": None,
        "profile_version": 1,
    }


def test_every_save_bumps_profile_version(client, auth, profile_body):
    client.put("/profile", json=profile_body, headers=auth)
    # Swap ranks 1 and 2: must not trip UNIQUE(user_id, rank).
    profile_body["interests"] = [
        {"role": "ai_ml_data", "rank": 1},
        {"role": "software", "rank": 2},
        {"role": "security", "rank": 3},
        {"role": "quant", "rank": 4},
    ]
    r = client.put("/profile", json=profile_body, headers=auth)
    assert r.status_code == 202 and r.json()["profile_version"] == 2
    body = client.get("/profile", headers=auth).json()
    assert [i["role"] for i in body["interests"]] == ["ai_ml_data", "software", "security", "quant"]


def test_optional_fields_may_be_omitted(client, auth, profile_body):
    del profile_body["minor"], profile_body["gpa"]
    assert client.put("/profile", json=profile_body, headers=auth).status_code == 202
    body = client.get("/profile", headers=auth).json()
    assert body["minor"] is None and body["gpa"] is None


@pytest.mark.parametrize(
    ("interests", "fragment"),
    [
        ([{"role": "software", "rank": 1}, {"role": "quant", "rank": 2}], "between 3 and 5"),
        ([{"role": r, "rank": 1} for r in SIX_ROLES], "between 3 and 5"),
        ([{"role": "software", "rank": 1}, {"role": "quant", "rank": 2},
          {"role": "security", "rank": 4}], "ranks must be 1..3"),
        ([{"role": "software", "rank": 1}, {"role": "quant", "rank": 2},
          {"role": "security", "rank": 2}], "ranks must be 1..3"),
        ([{"role": "software", "rank": 1}, {"role": "software", "rank": 2},
          {"role": "security", "rank": 3}], "only once"),
        ([{"role": "software", "rank": 1}, {"role": "other", "rank": 2},
          {"role": "security", "rank": 3}], "unknown role"),
        ([{"role": "software", "rank": 1}, {"role": "astrology", "rank": 2},
          {"role": "security", "rank": 3}], "unknown role"),
    ],
)  # fmt: skip
def test_invalid_interests_are_422(client, auth, profile_body, interests, fragment):
    profile_body["interests"] = interests
    r = client.put("/profile", json=profile_body, headers=auth)
    assert r.status_code == 422
    assert fragment in r.json()["detail"]
    assert client.get("/profile", headers=auth).status_code == 404  # nothing was saved


def test_skills_in_put_replace_resume_skills(client, auth, profile_body):
    profile_body["skills"] = ["python", "SQL", "sql", "  ", "Underwater Basket Weaving"]
    client.put("/profile", json=profile_body, headers=auth)
    from app.database import SessionLocal
    from app.models import Profile

    with SessionLocal() as db:
        assert db.get(Profile, 1).resume_skills == ["Python", "SQL", "Underwater Basket Weaving"]


def test_profiles_are_per_user(client, auth, profile_body):
    client.put("/profile", json=profile_body, headers=auth)
    other = register(client, email="grace@umd.edu")
    assert client.get("/profile", headers=other).status_code == 404


def test_profile_requires_auth(client, profile_body):
    assert client.get("/profile").status_code == 401
    assert client.put("/profile", json=profile_body).status_code == 401
