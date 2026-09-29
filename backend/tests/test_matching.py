"""The scorer's component weights, normalization, and hard filters (§4)."""

import math
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services import locations, matching
from app.services.matching import StudentView, passes_filters, score_posting, term_ordinal

NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)


def student(**over) -> StudentView:
    profile = SimpleNamespace(
        interests=[
            SimpleNamespace(role=r, rank=i + 1)
            for i, r in enumerate(["software", "ai_ml_data", "security", "quant", "hardware"])
        ],
        resume_skills=["Python", "SQL"],
        preferred_locations=["Washington, DC"],
        remote_ok=False,
        target_terms=["Summer 2027"],
        degree_level="Bachelor's",
    )
    for key, value in over.items():
        setattr(profile, key, value)
    return StudentView.from_profile(profile)


def posting(**over):
    row = dict(
        id=1,
        title="Software Engineer Intern",
        company_name="Acme",
        roles=["software"],
        locations=["Washington, DC"],
        is_remote=False,
        terms=["Summer 2027"],
        degrees=["Bachelor's"],
        date_posted=NOW,
        applied_here=False,
        saved_here=False,
    )
    return SimpleNamespace(**(row | over))


def points(scored, code):
    return scored.breakdown[code][0]


def test_weights_sum_to_100():
    weights = (
        matching.W_ROLE, matching.W_SKILLS, matching.W_LOCATION,
        matching.W_TERM, matching.W_FRESH, matching.W_COMPANY,
    )  # fmt: skip
    assert weights == (30, 20, 15, 15, 10, 10) and sum(weights) == 100


def test_perfect_posting_scores_100_with_every_reason():
    s = score_posting(
        posting(title="Python Software Engineer Intern", saved_here=True), student(), NOW
    )
    assert s.score == 100
    assert {k: v for k, v in s.breakdown.items()} == {
        "role_rank": (30, 30), "skills": (20.0, 20), "location": (15, 15),
        "term": (15, 15), "fresh": (10.0, 10), "company": (10, 10),
    }  # fmt: skip
    assert [r["code"] for r in s.reasons] == [
        "role_rank", "skills", "location", "term", "fresh", "company",
    ]  # fmt: skip
    assert s.reasons[0] == {
        "code": "role_rank", "label": "Matches your #1 field", "detail": "Software Engineering",
    }  # fmt: skip
    assert s.reasons[1] == {"code": "skills", "label": "1 of your skills", "detail": "Python"}
    assert s.reasons[4] == {"code": "fresh", "label": "Posted today", "detail": None}
    assert all(set(r) == {"code", "label", "detail"} for r in s.reasons)


@pytest.mark.parametrize(
    ("role", "expected"),
    [("software", 30), ("ai_ml_data", 24), ("security", 20), ("quant", 16), ("hardware", 12),
     ("design_ux", 0), ("other", 0)],
)  # fmt: skip
def test_field_match_points_by_rank(role, expected):
    s = score_posting(posting(roles=[role]), student(), NOW)
    assert s.breakdown["role_rank"] == (expected, 30)
    assert any(r["code"] == "role_rank" for r in s.reasons) == (expected > 0)


def test_field_match_takes_the_best_ranked_of_the_postings_roles():
    s = score_posting(posting(roles=["security", "software"]), student(), NOW)
    assert points(s, "role_rank") == 30
    assert s.reasons[0]["label"] == "Matches your #1 field"


def test_skills_is_the_share_of_asked_skills_you_have():
    s = score_posting(posting(title="Data Analyst Intern (SQL, Tableau)"), student(), NOW)
    assert s.breakdown["skills"] == (10.0, 20)  # has SQL, lacks Tableau
    assert {"code": "skills", "label": "1 of your skills", "detail": "SQL"} in s.reasons

    both = score_posting(posting(title="Python and SQL Developer Intern"), student(), NOW)
    assert both.breakdown["skills"] == (20.0, 20)
    assert {"code": "skills", "label": "2 of your skills", "detail": "Python, SQL"} in both.reasons

    none = score_posting(posting(title="Rust Engineer Intern"), student(), NOW)
    assert none.breakdown["skills"] == (0.0, 20)
    assert not any(r["code"] == "skills" for r in none.reasons)


def test_skills_cannot_be_earned_when_the_title_names_none():
    assert "skills" not in score_posting(posting(), student(), NOW).breakdown
    no_resume = score_posting(posting(title="Python Intern"), student(resume_skills=[]), NOW)
    assert "skills" not in no_resume.breakdown


@pytest.mark.parametrize(
    ("locs", "is_remote", "remote_ok", "expected", "label"),
    [
        (["Washington, DC"], False, False, 15, "In one of your locations"),
        (["Arlington, VA"], False, False, 15, "In one of your locations"),  # same metro
        (["Bethesda, MD", "Austin, TX"], False, False, 15, "In one of your locations"),
        (["Austin, TX"], False, False, 0, None),
        (["Remote in USA"], True, True, 15, "Remote friendly"),
        (["Remote in USA"], True, False, 0, None),
        (["NYC"], False, False, 0, None),
    ],
)
def test_location_points(locs, is_remote, remote_ok, expected, label):
    s = score_posting(
        posting(locations=locs, is_remote=is_remote), student(remote_ok=remote_ok), NOW
    )
    assert s.breakdown["location"] == (expected, 15)
    found = next((r for r in s.reasons if r["code"] == "location"), None)
    assert (found["label"] if found else None) == label


def test_same_state_is_10():
    who = student(preferred_locations=["Baltimore, MD"])
    s = score_posting(posting(locations=["Bethesda, MD"]), who, NOW)
    assert s.breakdown["location"] == (10, 15)
    assert s.reasons[1]["label"] == "Same state as one of your locations"
    # A student who asked for the whole state gets full marks anywhere in it.
    whole = score_posting(
        posting(locations=["Bethesda, MD"]), student(preferred_locations=["MD"]), NOW
    )
    assert whole.breakdown["location"] == (15, 15)


def test_location_cannot_be_earned_without_locations_or_a_preference():
    assert "location" not in score_posting(posting(locations=[]), student(), NOW).breakdown
    no_pref = student(preferred_locations=[], remote_ok=False)
    assert "location" not in score_posting(posting(), no_pref, NOW).breakdown


@pytest.mark.parametrize(
    ("terms", "expected", "label"),
    [
        (["Summer 2027"], 15, "Matches your target term"),
        (["Fall 2026", "Summer 2027"], 15, "Matches your target term"),
        (["Fall 2027"], 8, "Close to your target term"),
        (["Spring 2027"], 8, "Close to your target term"),
        (["Summer 2026"], 0, None),
    ],
)
def test_term_points(terms, expected, label):
    s = score_posting(posting(terms=terms), student(), NOW)
    assert s.breakdown["term"] == (expected, 15)
    found = next((r for r in s.reasons if r["code"] == "term"), None)
    assert (found["label"] if found else None) == label


def test_term_cannot_be_earned_when_the_posting_declares_none():
    assert "term" not in score_posting(posting(terms=[]), student(), NOW).breakdown
    assert "term" not in score_posting(posting(), student(target_terms=[]), NOW).breakdown


@pytest.mark.parametrize("days", [0, 3, 30, 90])
def test_freshness_decays_exponentially(days):
    s = score_posting(posting(date_posted=NOW - timedelta(days=days)), student(), NOW)
    assert points(s, "fresh") == pytest.approx(10 * math.exp(-days / 30))
    chip = next((r for r in s.reasons if r["code"] == "fresh"), None)
    assert (chip is not None) == (days <= 30)
    if days == 3:
        assert chip == {"code": "fresh", "label": "Posted 3 days ago", "detail": None}


def test_undated_postings_are_not_charged_for_freshness():
    assert "fresh" not in score_posting(posting(date_posted=None), student(), NOW).breakdown


def test_company_signal():
    applied = score_posting(posting(applied_here=True, saved_here=True), student(), NOW)
    assert applied.breakdown["company"] == (10, 10)
    assert applied.reasons[-1] == {
        "code": "company", "label": "You applied here before", "detail": "Acme",
    }  # fmt: skip
    saved = score_posting(posting(saved_here=True), student(), NOW)
    assert saved.reasons[-1]["label"] == "You saved another role here"
    assert score_posting(posting(), student(), NOW).breakdown["company"] == (0.0, 10)


def test_score_is_out_of_what_the_posting_could_earn():
    """No terms, no locations, no skills in the title: those 50 points are not
    held against it. 30 (field) + 10 (fresh) of 30 + 10 + 10 earnable."""
    bare = score_posting(posting(terms=[], locations=[]), student(), NOW)
    assert set(bare.breakdown) == {"role_rank", "fresh", "company"}
    assert bare.score == 80
    # The same posting with everything declared and matched scores 70 of 80.
    full = score_posting(posting(), student(), NOW)
    assert full.score == round(100 * 70 / 80)
    # ...and declared-but-unmatched costs points, as it should.
    wrong_city = score_posting(posting(locations=["Austin, TX"]), student(), NOW)
    assert wrong_city.score == round(100 * 55 / 80) < full.score


def test_term_ordinals_are_adjacent_in_calendar_order():
    order = ["Spring 2027", "Summer 2027", "Fall 2027", "Winter 2027", "Spring 2028"]
    ordinals = [term_ordinal(t) for t in order]
    assert ordinals == list(range(ordinals[0], ordinals[0] + 5))
    assert term_ordinal("N/A") is None and term_ordinal("Summer") is None


@pytest.mark.parametrize(
    ("over", "kept"),
    [
        ({}, True),
        ({"degrees": ["Master's", "PhD"]}, False),
        ({"degrees": ["Bachelor's", "Master's"]}, True),
        ({"degrees": []}, True),  # declares none -> not filtered
        ({"degrees": ["Bootcamp"]}, True),  # unrecognised label is not evidence
        ({"terms": ["Summer 2026"]}, False),
        ({"terms": ["Fall 2027"]}, True),  # adjacent survives, to score 8
        ({"terms": []}, True),
    ],
)
def test_hard_filters(over, kept):
    assert passes_filters(posting(**over), student()) is kept


def test_degree_synonyms():
    assert passes_filters(posting(), student(degree_level="Undergraduate")) is True
    assert passes_filters(posting(degrees=["Master's"]), student(degree_level="MS")) is True
    # A level we can't place is not used to exclude anything.
    assert passes_filters(posting(degrees=["PhD"]), student(degree_level="Certificate")) is True


def test_location_parsing():
    assert locations.parse("NYC") == locations.parse("New York, NY")
    assert locations.parse("SF").metro == locations.parse("Palo Alto, CA").metro
    assert locations.parse("College Park, MD").metro == "Washington, DC area"
    assert locations.parse("Toronto, ON, Canada").region == "ON"
    assert locations.parse("Remote in USA").remote is True
    assert locations.parse("United States") == locations.Place(None, None)
    assert locations.parse("Maryland") == locations.Place(None, "MD")
