"""postings: kind and duplicates across lists; profiles: what they look for

postings.kind is 'internship' or 'new_grad'. Every existing row is from an
internship list, so the default is right for all of them.

postings.dedupe_key, title_key and canonical_id find the same job in several
lists and pick one to show. They are filled by the next ingest (every row's
content hash changes with this revision, so every row is rewritten) and by
services/dedupe.py after it. Until then canonical_id is NULL, which counts
as "show it": nothing disappears in between.

profiles.looking_for defaults to internships only, which is what everyone
was offered before.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-01 01:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "postings",
        sa.Column("kind", sa.String(16), server_default=sa.text("'internship'"), nullable=False),
    )
    op.create_check_constraint("ck_postings_kind", "postings", "kind IN ('internship', 'new_grad')")
    op.add_column("postings", sa.Column("dedupe_key", sa.Text(), nullable=True))
    op.add_column("postings", sa.Column("title_key", sa.Text(), nullable=True))
    op.add_column("postings", sa.Column("canonical_id", sa.BigInteger(), nullable=True))
    op.create_index("ix_postings_dedupe_key", "postings", ["dedupe_key"])
    op.create_index("ix_postings_title_key", "postings", ["title_key"])
    op.add_column(
        "profiles",
        sa.Column(
            "looking_for",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{internship}'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("profiles", "looking_for")
    op.drop_index("ix_postings_title_key", table_name="postings")
    op.drop_index("ix_postings_dedupe_key", table_name="postings")
    op.drop_column("postings", "canonical_id")
    op.drop_column("postings", "title_key")
    op.drop_column("postings", "dedupe_key")
    op.drop_constraint("ck_postings_kind", "postings", type_="check")
    op.drop_column("postings", "kind")
