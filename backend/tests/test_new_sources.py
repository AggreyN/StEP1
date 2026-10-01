"""The lists published as README tables, and the New-Grad JSON list.

Each parser is run against a sample saved from the real list on 2026-10-01
(tests/fixtures/sources/), trimmed to a few rows, so a change in a list's
format shows up here rather than as an empty board in production.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.sources import readme_table as rt
from app.sources import table_sources as ts
from app.sources.base import url_key
from app.sources.simplify import normalize_row

FIXTURES = Path(__file__).parent / "fixtures" / "sources"
TODAY = date(2026, 10, 1)


def sample(name: str) -> str:
    return (FIXTURES / name).read_text()


# --------------------------------------------------------------------------- #
# jobright.ai
# --------------------------------------------------------------------------- #


def test_jobright_data_analysis():
    rows = ts.parse_jobright(
        sample("jobright_data_analysis.md"),
        source="jobright_data",
        category="Data Analysis",
        today=TODAY,
    )
    assert len(rows) == 12
    first, second = rows[0], rows[1]
    assert first.source == "jobright_data" and first.kind == "internship"
    assert first.source_id == "6abdbb30d9621c5b2838d8c7"  # the id in jobright's own URL
    assert first.company_name == "Southwest Airline Career Page"
    assert first.company_url == "http://www.southwest.com"
    assert first.title == "Summer 2027 Customer Experience & Analytics Data Science Internship"
    assert first.locations == ["Dallas, TX, United States"]
    assert first.terms == ["Summer 2027"]
    assert first.date_posted.date() == date(2026, 9, 30)
    assert first.url.startswith("https://jobright.ai/jobs/info/6abdbb30d9621c5b2838d8c7")
    assert first.roles == ["ai_ml_data", "data_analytics"]
    # "↳": the company of the row above.
    assert "↳" in second.raw["company"]
    assert second.company_name == "Southwest Airline Career Page"
    assert len({r.source_id for r in rows}) == len(rows)


def test_jobright_product():
    rows = ts.parse_jobright(
        sample("jobright_product.md"),
        source="jobright_product",
        category="Product Management",
        today=TODAY,
    )
    assert len(rows) == 12
    assert rows[1].company_name == "Schneider Electric"
    assert rows[1].title == "Graduate Product Management Intern"
    assert rows[1].terms == []
    assert all("product_management" in r.roles for r in rows[:4])


def test_jobright_category_is_the_classifier_fallback():
    markdown = (
        "| Company | Job Title | Location | Work Model | Date Posted |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| **[Acme](https://acme.com)** "
        "| **[Business Operations Intern](https://jobright.ai/jobs/info/abc)** "
        "| Remote, United States | Remote | Dec 30 |\n"
    )
    (row,) = ts.parse_jobright(
        markdown, source="jobright_business", category="Business Analyst", today=TODAY
    )
    assert row.roles == ["data_analytics"]  # nothing in the title; the list says the field
    assert row.is_remote is True
    # "Dec 30" with no year is the most recent one: last December.
    assert row.date_posted.date() == date(2025, 12, 30)


# --------------------------------------------------------------------------- #
# SpeedyApply
# --------------------------------------------------------------------------- #


def test_speedyapply_internships():
    rows = ts.parse_speedyapply(
        sample("speedyapply_readme.md"), source="speedyapply_ai", kind="internship", today=TODAY
    )
    assert len(rows) == 18  # three tables (FAANG+, Quant, Other), six rows each
    lyft = rows[0]
    assert lyft.company_name == "Lyft" and lyft.company_url == "https://www.lyft.com"
    assert lyft.title == "Applied Scientist Intern - Summer 2027"
    assert lyft.locations == ["San Francisco, CA"]
    assert (lyft.salary_min, lyft.salary_max, lyft.salary_unit) == (
        Decimal("58"),
        Decimal("58"),
        "hour",
    )
    # The apply link, not the company link and not the button image.
    assert lyft.url == "https://app.careerpuck.com/job-board/lyft/job/8843341002?gh_jid=8843341002"
    assert lyft.date_posted.date() == date(2026, 9, 30)  # "1d"
    assert lyft.kind == "internship" and lyft.terms == ["Summer 2027"]
    assert "ai_ml_data" in lyft.roles
    # A table without a Salary column parses too.
    assert any(r.salary_min is None for r in rows)


def test_speedyapply_new_grad():
    rows = ts.parse_speedyapply(
        sample("speedyapply_new_grad_usa.md"), source="speedyapply_ai", kind="new_grad", today=TODAY
    )
    assert len(rows) == 6 and all(r.kind == "new_grad" for r in rows)
    assert rows[0].salary_min == Decimal("172000") and rows[0].salary_unit == "year"


# --------------------------------------------------------------------------- #
# Zapply (off by default; parsed and tested regardless)
# --------------------------------------------------------------------------- #


def test_zapply():
    rows = ts.parse_zapply(sample("zapply_readme.md"), source="zapply", today=TODAY)
    assert len(rows) == 8
    first = rows[0]
    assert first.company_name == "Philips"
    assert first.locations == ["San Diego, California, United"]  # the list truncates
    assert first.url.startswith("https://zapply.jobs/l/d/")
    assert first.date_posted.date() == TODAY  # "18m"


def test_zapply_is_off_unless_enabled():
    from app.sources import backfill

    assert "zapply" not in backfill.SOURCES


# --------------------------------------------------------------------------- #
# Simplify New-Grad: the Simplify JSON, as new_grad
# --------------------------------------------------------------------------- #


def test_simplify_new_grad():
    rows = [
        normalize_row(r, source="simplify_newgrad", kind="new_grad")
        for r in json.loads(sample("simplify_new_grad.json"))
    ]
    assert len(rows) == 5 and all(r.kind == "new_grad" for r in rows)
    assert rows[0].source == "simplify_newgrad"
    assert rows[1].company_name == "Jain Global" and rows[1].roles == ["software"]
    assert rows[-1].active is False


# --------------------------------------------------------------------------- #
# The table reader itself
# --------------------------------------------------------------------------- #


def test_cells_closed_markers_html_tables_and_escaped_pipes():
    markdown = """
<table>
<tr><th>Company</th><th>Role</th><th>Location</th><th>Application</th><th>Age</th></tr>
<tr><td><strong><a href="https://a.com">A&amp;B Co</a></strong></td><td>SWE Intern 🛂</td>
<td>NYC, NY</br>Boston, MA</td><td><a href="https://jobs.a.com/1?utm_source=x">
<img src="https://i.imgur.com/apply.png" alt="Apply"></a></td><td>2d</td></tr>
<tr><td>↳</td><td>Data \\| ML Intern</td><td>Remote</td><td>🔒</td><td>3w</td></tr>
</table>
"""
    (table,) = rt.tables(markdown)
    assert len(table) == 2
    first, second = table
    assert first["company"].text == "A&B Co" and first["company"].links == ["https://a.com"]
    assert rt.without_markers(first["role"].text) == "SWE Intern"
    assert first["application"].links == ["https://jobs.a.com/1?utm_source=x"]
    assert rt.split_locations(first["location"].raw.replace("</br>", ";")) == [
        "NYC, NY",
        "Boston, MA",
    ]
    assert rt.is_same_as_above(second["company"]) and rt.is_closed(second)
    assert not rt.is_closed(first)
    assert rt.age_to_date("3w", TODAY).date() == date(2026, 9, 10)
    assert rt.age_to_date("2mo", TODAY).date() == date(2026, 8, 2)
    assert rt.age_to_date("soon", TODAY) is None


@pytest.mark.parametrize(
    "a, b, same",
    [
        (
            "https://boards.greenhouse.io/x/jobs/1?gh_src=abc",
            "https://boards.greenhouse.io/x/jobs/1",
            True,
        ),
        (
            "https://WWW.example.com/job/2/?utm_source=simplify&ref=gh",
            "http://example.com/job/2",
            True,
        ),
        ("https://example.com/job?id=1", "https://example.com/job?id=2", False),
        ("https://example.com/job#apply", "https://example.com/job", True),
    ],
)
def test_url_key(a, b, same):
    assert (url_key(a) == url_key(b)) is same


def test_salary_and_locations():
    assert rt.salary("$45/hr") == (Decimal("45"), Decimal("45"), "hour")
    assert rt.salary("$1,234 per hour")[2] == "hour"
    assert rt.salary("competitive") == (None, None, None)
    assert rt.split_locations("San Francisco, CA +3") == ["San Francisco, CA"]
