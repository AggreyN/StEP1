"""Classifier against real titles, and the two normalizers against real rows."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.sources import simplify, vanshb03
from app.sources.base import normalize_company
from app.sources.roles import ROLE_LABELS, classify

FIXTURES = Path(__file__).parent / "fixtures"
TITLES = json.loads((FIXTURES / "titles.json").read_text())


@pytest.mark.parametrize("case", TITLES, ids=[c["title"][:40] for c in TITLES])
def test_classifier_on_real_titles(case):
    roles = classify(case["title"], case["category"])
    assert roles == case["roles"]
    assert 1 <= len(roles) <= 3
    assert all(r in ROLE_LABELS for r in roles)


def test_classifier_fallbacks():
    assert classify("Intern", "Software Engineering") == ["software"]
    assert classify("Intern", "Data Science, AI & Machine Learning") == ["ai_ml_data"]
    assert classify("Summer Analyst", None) == ["other"]


def test_simplify_normalizer_on_real_rows():
    rows = json.loads((FIXTURES / "simplify_sample.json").read_text())
    out = [simplify.normalize_row(r) for r in rows]
    assert all(p is not None for p in out)
    remote = next(p for p in out if p.is_remote)
    assert any("Remote" in loc for loc in remote.locations)
    multi = next(p for p, r in zip(out, rows, strict=True) if len(r["terms"]) > 1)
    assert len(multi.terms) > 1
    na = next(p for p, r in zip(out, rows, strict=True) if r["terms"] == ["N/A"])
    assert na.terms == []  # "N/A" means "declares no term", not a term
    inactive = next(p for p, r in zip(out, rows, strict=True) if not r["active"])
    assert inactive.active is False
    for p, r in zip(out, rows, strict=True):
        assert p.source == "simplify" and p.source_id == r["id"]
        assert p.category == r["category"]
        assert p.roles and p.roles[0] != "other"
        assert p.date_posted == datetime.fromtimestamp(r["date_posted"], tz=UTC)
        assert p.raw is r


def test_simplify_skips_unusable_rows():
    assert simplify.normalize_row({"id": "x", "title": "", "url": "u"}) is None
    assert simplify.normalize_row({"id": "", "title": "t", "url": "u"}) is None


def test_vanshb03_normalizer_on_real_rows():
    rows = json.loads((FIXTURES / "vanshb03_sample.json").read_text())
    out = [vanshb03.normalize_row(r) for r in rows]
    for p in out:
        assert p.source == "vanshb03" and p.category is None and p.degrees == []
        assert p.roles
        assert len(p.terms) >= 1
    both = next(p for p, r in zip(out, rows, strict=True) if r["season"] == "Spring/Summer")
    assert both.terms == ["Spring 2027", "Summer 2027"]  # posted 2026-08


@pytest.mark.parametrize(
    ("season", "posted", "expected"),
    [
        ("Summer", "2026-08-15", ["Summer 2027"]),
        ("Summer", "2026-04-20", ["Summer 2026"]),
        ("Fall", "2026-07-01", ["Fall 2026"]),
        ("Winter", "2025-08-10", ["Winter 2025"]),
        ("Spring", "2026-05-01", ["Spring 2027"]),
        ("Autumn", "2026-02-01", ["Fall 2026"]),
        (None, "2026-02-01", []),
        ("", "2026-02-01", []),
    ],
)
def test_season_to_terms(season, posted, expected):
    dt = datetime.fromisoformat(posted).replace(tzinfo=UTC)
    assert vanshb03.season_to_terms(season, dt) == expected


def test_content_hash_ignores_raw_but_tracks_content():
    rows = json.loads((FIXTURES / "simplify_sample.json").read_text())
    a = simplify.normalize_row(rows[0])
    b = simplify.normalize_row({**rows[0], "sponsorship": "Offers Sponsorship"})
    assert a.content_hash == b.content_hash  # sponsorship isn't used, so no write
    c = simplify.normalize_row({**rows[0], "title": rows[0]["title"] + " (Fall)"})
    assert a.content_hash != c.content_hash


def test_normalize_company():
    assert normalize_company("Palantir Technologies, Inc.") == "palantir technologies"
    assert normalize_company("palantir technologies") == "palantir technologies"
    assert normalize_company("Procter & Gamble") == "procter and gamble"
    assert normalize_company("Inc.") == "inc."
