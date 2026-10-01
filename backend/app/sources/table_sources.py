"""Lists published as README tables: jobright.ai, SpeedyApply, Zapply.

Each is a table whose columns differ a little from list to list. The parsing
of cells is readme_table's; what the columns mean is here, one class per
publisher, configured per repository.

Nothing here invents a field the list does not give. A list without a term
column gets the terms its titles name ("Summer 2027") or none, which exempts
the posting from the term filter rather than guessing. A list without dates
gets none.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import UTC, date, datetime

from app import config
from app.sources import readme_table as rt
from app.sources.base import NormalizedPosting, Source, is_remote, terms_in, url_key
from app.sources.github_list import fetch_text
from app.sources.roles import classify


def _id_for(url: str) -> str:
    """A stable id for a row whose list gives none: from its link."""
    return hashlib.sha256((url_key(url) or url).encode()).hexdigest()[:24]


def _posting(
    *,
    source: str,
    source_id: str,
    company: str,
    company_url: str | None,
    title: str,
    url: str,
    locations: list[str],
    remote: bool,
    date_posted: datetime | None,
    kind: str,
    category: str | None,
    active: bool = True,
    pay: tuple = (None, None, None),
    raw: dict | None = None,
) -> NormalizedPosting:
    return NormalizedPosting(
        source=source,
        source_id=source_id,
        company_name=company,
        company_url=company_url,
        title=title,
        category=category,
        roles=classify(title, category),
        locations=locations,
        is_remote=remote or is_remote(locations),
        terms=terms_in(title),
        degrees=[],
        url=url,
        date_posted=date_posted,
        date_updated=date_posted,
        active=active,
        is_visible=True,
        salary_min=pay[0],
        salary_max=pay[1],
        salary_unit=pay[2],
        kind=kind,
        raw=raw or {},
    )


def _raw(row: dict[str, rt.Cell]) -> dict:
    return {header: cell.raw for header, cell in row.items()}


# --------------------------------------------------------------------------- #
# jobright.ai: Company | Job Title | Location | Work Model | Date Posted
# --------------------------------------------------------------------------- #


def parse_jobright(
    markdown: str, *, source: str, category: str, today: date | None = None
) -> list[NormalizedPosting]:
    today = today or datetime.now(UTC).date()
    out: list[NormalizedPosting] = []
    company, company_url = None, None
    for table in rt.tables(markdown):
        for row in table:
            company_cell = rt.column(row, "company")
            title_cell = rt.column(row, "job title", "title", "role", "position")
            if company_cell is None or title_cell is None or not title_cell.links:
                continue
            if not rt.is_same_as_above(company_cell):
                company = rt.without_markers(company_cell.text) or None
                company_url = company_cell.links[0] if company_cell.links else None
            if not company:
                continue
            url = title_cell.links[0]
            # https://jobright.ai/jobs/info/<id>?utm_...: the id is the job's.
            path = url.split("?", 1)[0].rstrip("/")
            source_id = path.rsplit("/", 1)[-1] if "/jobs/info/" in path else _id_for(url)
            where = rt.column(row, "location")
            model = rt.column(row, "work model")
            posted = rt.column(row, "date posted", "posted", "date")
            out.append(
                _posting(
                    source=source,
                    source_id=source_id,
                    company=company,
                    company_url=company_url,
                    title=rt.without_markers(title_cell.text),
                    url=url,
                    locations=rt.split_locations(where.text) if where else [],
                    remote=bool(model and "remote" in model.text.lower()),
                    date_posted=rt.month_day_to_date(posted.text, today) if posted else None,
                    kind="internship",
                    category=category,
                    active=not rt.is_closed(row),
                    raw=_raw(row),
                )
            )
    return out


class _Jobright(Source):
    repo_setting: str
    category: str

    def fetch(self) -> Iterable[NormalizedPosting]:
        text = fetch_text(getattr(config, self.repo_setting), "README.md", config.JOBRIGHT_BRANCH)
        yield from parse_jobright(text, source=self.name, category=self.category)


class JobrightDataAnalysisSource(_Jobright):
    name = "jobright_data"
    repo_setting = "JOBRIGHT_DATA_ANALYSIS_REPO"
    category = "Data Analysis"


class JobrightBusinessAnalystSource(_Jobright):
    name = "jobright_business"
    repo_setting = "JOBRIGHT_BUSINESS_ANALYST_REPO"
    category = "Business Analyst"


class JobrightProductSource(_Jobright):
    name = "jobright_product"
    repo_setting = "JOBRIGHT_PRODUCT_REPO"
    category = "Product Management"


# --------------------------------------------------------------------------- #
# SpeedyApply: Company | Position | Location | [Salary] | Posting | Age
# One README per audience: interns in the USA, interns abroad, new grads in
# the USA, new grads abroad.
# --------------------------------------------------------------------------- #

SPEEDYAPPLY_FILES = {
    "README.md": "internship",
    "INTERN_INTL.md": "internship",
    "NEW_GRAD_USA.md": "new_grad",
    "NEW_GRAD_INTL.md": "new_grad",
}


def parse_speedyapply(
    markdown: str, *, source: str, kind: str, today: date | None = None
) -> list[NormalizedPosting]:
    today = today or datetime.now(UTC).date()
    out: list[NormalizedPosting] = []
    for table in rt.tables(markdown):
        for row in table:
            company_cell = rt.column(row, "company")
            title_cell = rt.column(row, "position", "role", "title")
            apply_cell = rt.column(row, "posting", "apply", "link")
            if company_cell is None or title_cell is None or apply_cell is None:
                continue
            if not apply_cell.links:
                continue
            company = rt.without_markers(company_cell.text)
            if not company:
                continue
            url = apply_cell.links[0]
            where = rt.column(row, "location")
            pay = rt.column(row, "salary")
            age = rt.column(row, "age", "posted")
            out.append(
                _posting(
                    source=source,
                    source_id=_id_for(url),
                    company=company,
                    company_url=company_cell.links[0] if company_cell.links else None,
                    title=rt.without_markers(title_cell.text),
                    url=url,
                    locations=rt.split_locations(where.text) if where else [],
                    remote=False,
                    date_posted=rt.age_to_date(age.text, today) if age else None,
                    kind=kind,
                    category="AI/ML/Data",
                    active=not rt.is_closed(row),
                    pay=rt.salary(pay.text) if pay else (None, None, None),
                    raw=_raw(row),
                )
            )
    return out


class SpeedyApplyAISource(Source):
    name = "speedyapply_ai"

    def fetch(self) -> Iterable[NormalizedPosting]:
        for path, kind in SPEEDYAPPLY_FILES.items():
            text = fetch_text(config.SPEEDYAPPLY_AI_REPO, path, config.SPEEDYAPPLY_BRANCH)
            yield from parse_speedyapply(text, source=self.name, kind=kind)


# --------------------------------------------------------------------------- #
# Zapply: Company | Role | Location | Posted | Visa | Apply
# Off unless ZAPPLY_ENABLED (its license: see config.py).
# --------------------------------------------------------------------------- #


def parse_zapply(markdown: str, *, source: str, today: date | None = None):
    today = today or datetime.now(UTC).date()
    out: list[NormalizedPosting] = []
    company = None
    for table in rt.tables(markdown):
        for row in table:
            company_cell = rt.column(row, "company")
            title_cell = rt.column(row, "role", "position", "title")
            apply_cell = rt.column(row, "apply")
            if company_cell is None or title_cell is None or apply_cell is None:
                continue
            if not apply_cell.links:
                continue
            if not rt.is_same_as_above(company_cell):
                company = rt.without_markers(company_cell.text) or None
            if not company:
                continue
            url = apply_cell.links[0]
            where = rt.column(row, "location")
            posted = rt.column(row, "posted", "age")
            out.append(
                _posting(
                    source=source,
                    source_id=_id_for(url),
                    company=company,
                    company_url=None,
                    title=rt.without_markers(title_cell.text),
                    url=url,
                    locations=rt.split_locations(where.text) if where else [],
                    remote=False,
                    date_posted=rt.age_to_date(posted.text, today) if posted else None,
                    kind="internship",
                    category=None,
                    active=not rt.is_closed(row),
                    raw=_raw(row),
                )
            )
    return out


class ZapplySource(Source):
    name = "zapply"

    def fetch(self) -> Iterable[NormalizedPosting]:
        text = fetch_text(config.ZAPPLY_REPO, "README.md", config.ZAPPLY_BRANCH)
        yield from parse_zapply(text, source=self.name)
