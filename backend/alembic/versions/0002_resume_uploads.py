"""resume upload slots

Adds `resume_uploads`: one row per upload slot issued by
POST /profile/resume/presign, recording the owner, the declared size and the
expiry, so that an upload can be held to what was promised and used once.

Nothing existing changes. Resumes stored before this revision have no row
here and do not need one: `profiles.resume_s3_key` still points at them, and
they are still deleted when replaced.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-28 23:40:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resume_uploads",
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("size > 0", name="ck_resume_uploads_size"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index("ix_resume_uploads_user_id", "resume_uploads", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_resume_uploads_user_id", table_name="resume_uploads")
    op.drop_table("resume_uploads")
