"""base resumes and saved (tailored) resumes

base_resumes: one per person, the resume as data they confirmed, which
tailoring draws from. tailored_resumes: the resumes they saved, by name.
Both belong to their owner and go with the account (ON DELETE CASCADE).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-01 03:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "base_resumes",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("doc", postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "tailored_resumes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("doc", postgresql.JSONB(), nullable=False),
        sa.Column("posting_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 80", name="ck_tailored_resumes_name"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["posting_id"], ["postings.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tailored_resumes_user_updated",
        "tailored_resumes",
        ["user_id", sa.text("updated_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_tailored_resumes_user_updated", table_name="tailored_resumes")
    op.drop_table("tailored_resumes")
    op.drop_table("base_resumes")
