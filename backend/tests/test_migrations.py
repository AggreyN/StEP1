"""§3: `alembic upgrade head` from empty creates every table, index and
constraint the spec names (the session fixture ran the migration)."""

from sqlalchemy import inspect, text

from app.database import engine

SPEC_TABLES = {
    "users",
    "profiles",
    "profile_interests",
    "companies",
    "postings",
    "match_scores",
    "saved_postings",
    "applications",
    "application_events",
    "contacts",
    "outreach_messages",
    "integrations",
    "ingest_runs",
}


def test_every_spec_table_exists():
    assert SPEC_TABLES <= set(inspect(engine).get_table_names())


def test_spec_indexes_and_extension():
    with engine.connect() as conn:
        idx = {
            r.indexname: r.indexdef
            for r in conn.execute(text("SELECT indexname, indexdef FROM pg_indexes"))
        }
        ext = conn.execute(text("SELECT 1 FROM pg_extension WHERE extname='pg_trgm'")).scalar()
    assert ext == 1
    assert "USING gin (search_tsv)" in idx["ix_postings_search_tsv"]
    assert "USING gin (locations)" in idx["ix_postings_locations"]
    assert "USING gin (roles)" in idx["ix_postings_roles"]
    assert "date_posted DESC" in idx["ix_postings_active_date_posted"]
    assert "(category, active)" in idx["ix_postings_category_active"]
    assert "score DESC" in idx["ix_match_scores_user_score"]
    assert "(source, source_id)" in idx["uq_postings_source_source_id"]
    assert "(user_id, rank)" in idx["uq_profile_interests_user_rank"]


def test_search_tsv_is_generated():
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO postings (source, source_id, company_name, title, url, raw) "
                "VALUES ('t', '1', 'Palantir', 'Software Engineering Intern', 'u', '{}')"
            )
        )
        tsv = conn.execute(text("SELECT search_tsv::text FROM postings")).scalar()
        generated = conn.execute(
            text(
                "SELECT is_generated FROM information_schema.columns "
                "WHERE table_name='postings' AND column_name='search_tsv'"
            )
        ).scalar()
    assert generated == "ALWAYS"
    assert "'palantir'" in tsv and "'softwar'" in tsv and "'intern'" in tsv
