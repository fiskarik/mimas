"""Shared profession plans and separately consented general assessments.

Revision ID: 0005_general_interviews
Revises: 0004_interview_settings
"""
from alembic import op
import sqlalchemy as sa

revision = '0005_general_interviews'
down_revision = '0004_interview_settings'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'professions',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('name', sa.Text(), nullable=False, unique=True),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('plan_json', sa.Text(), nullable=False),
        sa.Column('settings_json', sa.Text(), nullable=False),
        sa.Column('approved_at', sa.Float(), nullable=False),
    )
    op.create_table(
        'general_assessments',
        sa.Column('candidate_id', sa.Text(), sa.ForeignKey('candidate_profiles.id'), primary_key=True),
        sa.Column('profession_id', sa.Text(), sa.ForeignKey('professions.id'), primary_key=True),
        sa.Column('session_id', sa.Text(), sa.ForeignKey('ai_sessions.id'), nullable=False, unique=True),
        sa.Column('share_with_companies', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('consent_at', sa.Float(), nullable=False),
        sa.Column('created', sa.Float(), nullable=False),
    )
    op.create_index('ix_general_assessments_profession', 'general_assessments', ['profession_id'])


def downgrade():
    op.drop_index('ix_general_assessments_profession', table_name='general_assessments')
    op.drop_table('general_assessments')
    op.drop_table('professions')
