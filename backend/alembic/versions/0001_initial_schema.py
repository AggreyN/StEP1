"""initial schema

Every table, index and constraint in §3 of docs/ARCHITECTURE.md, plus the
columns the rest of the doc and the API contract require (see app/models.py
docstring). The role and event-kind CHECK lists are frozen here on purpose:
adding a role to roles.py is a schema change and gets its own revision.

Revision ID: 0001
Revises:
Create Date: 2026-09-28 12:33:41.980991
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Trigram matching for fuzzy company-name dedupe across sources (§3).
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table('companies',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('normalized_name', sa.String(length=300), nullable=False),
    sa.Column('url', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('normalized_name')
    )
    op.create_index('ix_companies_normalized_name_trgm', 'companies', ['normalized_name'], unique=False, postgresql_using='gin', postgresql_ops={'normalized_name': 'gin_trgm_ops'})
    op.create_table('ingest_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('fetched', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('upserted', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('deactivated', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ingest_runs_source_started', 'ingest_runs', ['source', sa.literal_column('started_at DESC')], unique=False)
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('cognito_sub', sa.String(length=64), nullable=True),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('password_hash', sa.String(length=128), nullable=True),
    sa.Column('display_name', sa.String(length=120), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('cognito_sub'),
    sa.UniqueConstraint('email')
    )
    op.create_table('integrations',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('provider', sa.String(length=16), nullable=False),
    sa.Column('external_id', sa.String(length=200), nullable=True),
    sa.Column('scopes', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('token_secret_arn', sa.Text(), nullable=True),
    sa.Column('connected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("provider IN ('gmail', 'github', 'linkedin')", name='ck_integrations_provider'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'provider')
    )
    op.create_table('postings',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('source_id', sa.String(length=128), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('company_name', sa.String(length=300), nullable=True),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('category', sa.String(length=80), nullable=True),
    sa.Column('roles', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('locations', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('is_remote', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('terms', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('degrees', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('date_posted', sa.DateTime(timezone=True), nullable=True),
    sa.Column('date_updated', sa.DateTime(timezone=True), nullable=True),
    sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('is_visible', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('salary_min', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('salary_max', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('salary_unit', sa.String(length=8), nullable=True),
    sa.Column('raw', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=True),
    sa.Column('search_tsv', postgresql.TSVECTOR(), sa.Computed("to_tsvector('english'::regconfig, title || ' ' || coalesce(company_name, ''))", persisted=True), nullable=False),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'source_id', name='uq_postings_source_source_id')
    )
    op.create_index('ix_postings_active_date_posted', 'postings', ['active', sa.literal_column('date_posted DESC')], unique=False)
    op.create_index('ix_postings_category_active', 'postings', ['category', 'active'], unique=False)
    op.create_index('ix_postings_company_id', 'postings', ['company_id'], unique=False)
    op.create_index('ix_postings_locations', 'postings', ['locations'], unique=False, postgresql_using='gin')
    op.create_index('ix_postings_roles', 'postings', ['roles'], unique=False, postgresql_using='gin')
    op.create_index('ix_postings_search_tsv', 'postings', ['search_tsv'], unique=False, postgresql_using='gin')
    op.create_table('profiles',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('school', sa.String(length=200), nullable=True),
    sa.Column('major', sa.String(length=200), nullable=True),
    sa.Column('minor', sa.String(length=200), nullable=True),
    sa.Column('degree_level', sa.String(length=40), nullable=True),
    sa.Column('grad_year', sa.SmallInteger(), nullable=True),
    sa.Column('gpa', sa.Numeric(precision=3, scale=2), nullable=True),
    sa.Column('target_terms', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('preferred_locations', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('remote_ok', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('work_auth', sa.String(length=80), nullable=True),
    sa.Column('resume_s3_key', sa.String(length=512), nullable=True),
    sa.Column('resume_filename', sa.String(length=255), nullable=True),
    sa.Column('resume_uploaded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resume_text', sa.Text(), nullable=True),
    sa.Column('resume_skills', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('resume_needs_ocr', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('onboarded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('profile_version', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('scores_version', sa.Integer(), nullable=True),
    sa.Column('scores_computed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_table('applications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('posting_id', sa.BigInteger(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_event_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['posting_id'], ['postings.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'posting_id', name='uq_applications_user_posting')
    )
    op.create_index('ix_applications_user_last_event', 'applications', ['user_id', sa.literal_column('last_event_at DESC')], unique=False)
    op.create_table('match_scores',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('posting_id', sa.BigInteger(), nullable=False),
    sa.Column('score', sa.SmallInteger(), nullable=False),
    sa.Column('reasons', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('profile_version', sa.Integer(), nullable=False),
    sa.Column('computed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['posting_id'], ['postings.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'posting_id')
    )
    op.create_index('ix_match_scores_user_score', 'match_scores', ['user_id', sa.literal_column('score DESC')], unique=False)
    op.create_table('profile_interests',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=40), nullable=False),
    sa.Column('rank', sa.SmallInteger(), nullable=False),
    sa.CheckConstraint("role IN ('software', 'ai_ml_data', 'data_analytics', 'hardware', 'quant', 'product_management', 'program_management', 'solutions_architecture', 'security', 'infra_devops', 'design_ux', 'it_support', 'tech_consulting', 'research')", name='ck_profile_interests_role'),
    sa.CheckConstraint('rank BETWEEN 1 AND 5', name='ck_profile_interests_rank'),
    sa.ForeignKeyConstraint(['user_id'], ['profiles.user_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'role'),
    sa.UniqueConstraint('user_id', 'rank', name='uq_profile_interests_user_rank')
    )
    op.create_table('saved_postings',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('posting_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['posting_id'], ['postings.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'posting_id')
    )
    op.create_table('application_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('application_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('source', sa.String(length=16), server_default=sa.text("'manual'"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('applied', 'acknowledged', 'oa_sent', 'oa_completed', 'interview_scheduled', 'interviewed', 'additional_round', 'offer', 'accepted', 'rejected', 'withdrawn', 'ghosted', 'note', 'outreach_sent')", name='ck_application_events_kind'),
    sa.CheckConstraint("source IN ('manual', 'gmail', 'system')", name='ck_application_events_source'),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_application_events_app_occurred', 'application_events', ['application_id', 'occurred_at'], unique=False)
    op.create_table('contacts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('application_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('role', sa.String(length=200), nullable=True),
    sa.Column('email', sa.String(length=320), nullable=True),
    sa.Column('linkedin_url', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('outreach_messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('application_id', sa.Integer(), nullable=False),
    sa.Column('contact_id', sa.Integer(), nullable=True),
    sa.Column('channel', sa.String(length=32), nullable=False),
    sa.Column('subject', sa.Text(), nullable=True),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('follow_up_due_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('outreach_messages')
    op.drop_table('contacts')
    op.drop_index('ix_application_events_app_occurred', table_name='application_events')
    op.drop_table('application_events')
    op.drop_table('saved_postings')
    op.drop_table('profile_interests')
    op.drop_index('ix_match_scores_user_score', table_name='match_scores')
    op.drop_table('match_scores')
    op.drop_index('ix_applications_user_last_event', table_name='applications')
    op.drop_table('applications')
    op.drop_table('profiles')
    op.drop_index('ix_postings_search_tsv', table_name='postings', postgresql_using='gin')
    op.drop_index('ix_postings_roles', table_name='postings', postgresql_using='gin')
    op.drop_index('ix_postings_locations', table_name='postings', postgresql_using='gin')
    op.drop_index('ix_postings_company_id', table_name='postings')
    op.drop_index('ix_postings_category_active', table_name='postings')
    op.drop_index('ix_postings_active_date_posted', table_name='postings')
    op.drop_table('postings')
    op.drop_table('integrations')
    op.drop_table('users')
    op.drop_index('ix_ingest_runs_source_started', table_name='ingest_runs')
    op.drop_table('ingest_runs')
    op.drop_index('ix_companies_normalized_name_trgm', table_name='companies', postgresql_using='gin', postgresql_ops={'normalized_name': 'gin_trgm_ops'})
    op.drop_table('companies')
    # pg_trgm is left installed: other database objects may depend on it,
    # and it is harmless.
