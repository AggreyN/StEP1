"""Scoring every open posting for one student: one query, one pass, well
under a second at the real board's size."""

import itertools
import time

from sqlalchemy import event, func, select

from app.database import SessionLocal, engine
from app.models import MatchScore, Profile
from app.services import matching
from tests.conftest import make_row, onboard, register, seed

N = 4_500  # the live board is ~4,800 open postings

TITLES = [
    "Software Engineer Intern", "Python Backend Engineer Intern", "Machine Learning Intern",
    "Data Analyst Intern (SQL, Tableau)", "Embedded Firmware Intern", "Security Engineer Intern",
    "Product Manager Intern", "Quantitative Research Intern", "DevOps Engineer Intern - AWS",
    "Full Stack Developer Intern - React", "Solutions Engineer Intern", "Research Intern",
]  # fmt: skip
PLACES = [
    ("Washington, DC",), ("Arlington, VA",), ("NYC",), ("SF",), ("Austin, TX", "Remote in USA"),
    ("Seattle, WA",), ("Bethesda, MD",), ("Remote in USA",), (), ("Toronto, ON, Canada",),
]  # fmt: skip
TERMS = [("Summer 2027",), ("Fall 2027",), ("Spring 2027",), (), ("Summer 2027", "Fall 2027")]


def test_scoring_the_whole_board_takes_under_a_second(client):
    combos = itertools.cycle(itertools.product(TITLES, PLACES, TERMS))
    seed(
        [
            make_row(f"p{i}", title, f"Company {i % 900}", locations=places, terms=terms,
                     days_ago=i % 110)
            for i, (title, places, terms) in zip(range(N), combos, strict=False)
        ]
    )  # fmt: skip
    headers = register(client)
    onboard(client, headers, skills=["Python", "SQL", "React", "AWS", "Machine Learning"])

    statements: list[str] = []

    def count(conn, cursor, statement, *_):
        statements.append(statement)

    with SessionLocal() as db:
        profile = db.get(Profile, 1)
        _ = profile.interests  # loaded by the caller, not part of scoring
        matching.title_skills.cache_clear()  # cold: no help from an earlier run

        event.listen(engine, "before_cursor_execute", count)
        try:
            start = time.perf_counter()
            scored = matching.score_all(db, profile)
            scoring = time.perf_counter() - start
        finally:
            event.remove(engine, "before_cursor_execute", count)

        assert len(statements) == 1, statements  # one query, not one per posting
        assert len(scored) == N
        assert scoring < 1.0, f"scoring took {scoring:.3f}s"

        start = time.perf_counter()
        written = matching.rescore(db, 1)
        total = time.perf_counter() - start
        assert written == N
        assert db.scalar(select(func.count()).select_from(MatchScore)) == N
        # Scoring plus replacing the cached rows; generous, to catch a
        # regression to row-at-a-time writes rather than to time the disk.
        assert total < 3.0, f"rescore took {total:.3f}s"
    print(
        f"\nscored {N} postings in {scoring * 1000:.0f} ms; rescore+persist {total * 1000:.0f} ms"
    )
