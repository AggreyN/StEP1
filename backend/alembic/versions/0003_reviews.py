"""reviews of the app

Adds `reviews`: one row per review a signed-in person writes. Each belongs
to its author and goes with their account (ON DELETE CASCADE).

Nothing existing changes.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-30 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_reviews_rating"),
        sa.CheckConstraint("char_length(body) BETWEEN 1 AND 2000", name="ck_reviews_body"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reviews_user_id", "reviews", ["user_id"], unique=False)
    op.create_index("ix_reviews_created_at", "reviews", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_reviews_created_at", table_name="reviews")
    op.drop_index("ix_reviews_user_id", table_name="reviews")
    op.drop_table("reviews")
