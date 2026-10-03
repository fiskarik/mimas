"""Tenant isolation, approved vacancy templates and Yandex service accounting.

Revision ID: 0002_tenants_ai
Revises: 0001_legacy

The old candidate-assessment relation did not identify a vacancy. It is copied
into a read-only archive instead of guessing ownership or consent.
"""
from alembic import op
import sqlalchemy as sa


revision = '0002_tenants_ai'
down_revision = '0001_legacy'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'companies',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('contact_email', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False, server_default='pending'),
        sa.Column('key_hash', sa.Text(), unique=True),
        sa.Column('claim_hash', sa.Text(), unique=True),
        sa.Column('claim_expires', sa.Float()),
        sa.Column('created', sa.Float(), nullable=False),
        sa.Column('approved', sa.Float()),
    )
    # Existing data belonged to the single legacy company. Its key digest is
    # filled by ensure_legacy_company() after the migration; the secret never
    # appears in a migration file or SQL log.
    op.execute("""
        INSERT INTO companies
            (id, name, contact_email, status, key_hash, claim_hash,
             claim_expires, created, approved)
        VALUES ('legacy', 'MIMAS Legacy', '', 'approved', NULL, NULL, NULL,
                EXTRACT(EPOCH FROM NOW()), EXTRACT(EPOCH FROM NOW()))
    """)

    op.add_column('interviews', sa.Column('company_id', sa.Text(), nullable=True))
    op.execute("UPDATE interviews SET company_id = 'legacy'")
    op.alter_column('interviews', 'company_id', nullable=False)
    op.create_foreign_key('fk_interviews_company_id', 'interviews', 'companies',
                          ['company_id'], ['id'])

    op.add_column('opportunities', sa.Column('company_id', sa.Text(), nullable=True))
    op.execute("UPDATE opportunities SET company_id = 'legacy'")
    op.alter_column('opportunities', 'company_id', nullable=False)
    op.create_foreign_key('fk_opportunities_company_id', 'opportunities', 'companies',
                          ['company_id'], ['id'])
    # Prior open listings cannot become visible until their owners approve a
    # vacancy-specific assessment template.
    op.execute("UPDATE opportunities SET status = 'draft' WHERE status = 'open'")

    op.create_table(
        'vacancy_templates',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('opportunity_id', sa.Text(), sa.ForeignKey('opportunities.id'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False, server_default='draft'),
        sa.Column('plan_json', sa.Text(), nullable=False),
        sa.Column('created', sa.Float(), nullable=False),
        sa.Column('approved', sa.Float()),
        sa.UniqueConstraint('opportunity_id', 'version', name='uq_vacancy_template_version'),
    )

    op.add_column('ai_sessions', sa.Column('candidate_id', sa.Text()))
    op.add_column('ai_sessions', sa.Column('opportunity_id', sa.Text()))
    op.add_column('ai_sessions', sa.Column('archived', sa.Integer(), nullable=False,
                                           server_default='0'))
    # Completed legacy states remain in ai_sessions and their reports are
    # reconstructed from the untouched state. Incomplete ones cannot resume
    # against the removed Groq/Gemini provider.
    op.execute("UPDATE ai_sessions SET archived = 1")

    op.create_table(
        'legacy_candidate_assessments',
        sa.Column('candidate_id', sa.Text(), sa.ForeignKey('candidate_profiles.id'),
                  primary_key=True),
        sa.Column('session_id', sa.Text(), sa.ForeignKey('ai_sessions.id'),
                  nullable=False, unique=True),
        sa.Column('created', sa.Float(), nullable=False),
    )
    op.execute("""
        INSERT INTO legacy_candidate_assessments (candidate_id, session_id, created)
        SELECT candidate_id, session_id, created FROM candidate_assessments
    """)
    op.drop_table('candidate_assessments')
    op.create_table(
        'candidate_assessments',
        sa.Column('candidate_id', sa.Text(), sa.ForeignKey('candidate_profiles.id'),
                  primary_key=True),
        sa.Column('opportunity_id', sa.Text(), sa.ForeignKey('opportunities.id'),
                  primary_key=True),
        sa.Column('session_id', sa.Text(), sa.ForeignKey('ai_sessions.id'),
                  nullable=False, unique=True),
        sa.Column('consent_at', sa.Float(), nullable=False),
        sa.Column('created', sa.Float(), nullable=False),
    )

    op.create_table(
        'video_recordings',
        sa.Column('session_id', sa.Text(), sa.ForeignKey('ai_sessions.id'), primary_key=True),
        sa.Column('object_key', sa.Text(), nullable=False, unique=True),
        sa.Column('upload_id', sa.Text()),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('created', sa.Float(), nullable=False),
        sa.Column('completed', sa.Float()),
        sa.Column('expires_at', sa.Float()),
        sa.Column('part_count', sa.Integer(), nullable=False),
        sa.Column('interrupted', sa.Integer(), nullable=False, server_default='0'),
    )

    op.create_table(
        'yandex_budget_months',
        sa.Column('month', sa.String(length=7), primary_key=True),
        sa.Column('spent_rub', sa.Numeric(14, 4), nullable=False),
        sa.Column('reserved_rub', sa.Numeric(14, 4), nullable=False),
    )
    op.create_table(
        'yandex_cost_entries',
        sa.Column('id', sa.String(length=32), primary_key=True),
        sa.Column('month', sa.String(length=7), sa.ForeignKey('yandex_budget_months.month'),
                  nullable=False),
        sa.Column('service', sa.String(length=40), nullable=False),
        sa.Column('operation', sa.String(length=80), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('reserved_rub', sa.Numeric(14, 4), nullable=False),
        sa.Column('charged_rub', sa.Numeric(14, 4)),
        sa.Column('usage_json', sa.Text()),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('expires_at', sa.Float(), nullable=False),
    )
    op.create_index('ix_yandex_cost_entries_month', 'yandex_cost_entries', ['month'])
    op.create_index('ix_yandex_cost_entries_status', 'yandex_cost_entries', ['status'])


def downgrade():
    raise RuntimeError(
        '0002_tenants_ai cannot be downgraded without losing per-vacancy '
        'assessments and consent records. Restore a PostgreSQL backup instead.'
    )
