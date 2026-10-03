"""Legacy SQLAlchemy schema, before tenant isolation.

Revision ID: 0001_legacy
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = '0001_legacy'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('interviews',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('token', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False, server_default='invited'),
        sa.Column('created', sa.Float(), nullable=False),
        sa.Column('started', sa.Float()),
        sa.Column('completed', sa.Float()),
        sa.Column('mode', sa.Text(), nullable=False),
        sa.Column('expected_chunks', sa.Integer()),
        sa.Column('recording_complete', sa.Integer(), nullable=False, server_default='0'))
    op.create_table('answers',
        sa.Column('interview_id', sa.Text(), primary_key=True),
        sa.Column('question_id', sa.Text(), primary_key=True),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('created', sa.Float(), nullable=False),
        sa.Column('evaluation', sa.Text()),
        sa.Column('next_question', sa.Text()))
    op.create_table('events',
        sa.Column('interview_id', sa.Text(), primary_key=True),
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('elapsed', sa.Float(), nullable=False),
        sa.Column('detail', sa.Text(), nullable=False),
        sa.Column('created', sa.Float(), nullable=False))
    op.create_table('chunks',
        sa.Column('interview_id', sa.Text(), primary_key=True),
        sa.Column('seq', sa.Integer(), primary_key=True),
        sa.Column('digest', sa.Text(), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False))
    op.create_table('ai_sessions',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('token_hash', sa.Text(), nullable=False),
        sa.Column('model', sa.Text(), nullable=False),
        sa.Column('started', sa.Float(), nullable=False),
        sa.Column('state', sa.Text(), nullable=False),
        sa.Column('trace', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('pending', sa.Text()))
    op.create_table('candidate_profiles',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('token_hash', sa.Text(), nullable=False, unique=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('level', sa.Text(), nullable=False),
        sa.Column('stack', sa.Text(), nullable=False),
        sa.Column('years_experience', sa.Float(), nullable=False),
        sa.Column('github_url', sa.Text()),
        sa.Column('desired_salary_rub', sa.Integer()),
        sa.Column('discoverable', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created', sa.Float(), nullable=False))
    op.create_table('opportunities',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('company_name', sa.Text(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('level', sa.Text(), nullable=False),
        sa.Column('stack', sa.Text(), nullable=False),
        sa.Column('salary_min_rub', sa.Integer()),
        sa.Column('salary_max_rub', sa.Integer()),
        sa.Column('employment_type', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False, server_default='open'),
        sa.Column('created', sa.Float(), nullable=False))
    op.create_table('candidate_interests',
        sa.Column('candidate_id', sa.Text(), sa.ForeignKey('candidate_profiles.id'), primary_key=True),
        sa.Column('opportunity_id', sa.Text(), sa.ForeignKey('opportunities.id'), primary_key=True),
        sa.Column('created', sa.Float(), nullable=False))
    op.create_table('candidate_assessments',
        sa.Column('candidate_id', sa.Text(), sa.ForeignKey('candidate_profiles.id'), primary_key=True),
        sa.Column('session_id', sa.Text(), sa.ForeignKey('ai_sessions.id'), nullable=False, unique=True),
        sa.Column('created', sa.Float(), nullable=False))


def downgrade():
    for name in ('candidate_assessments', 'candidate_interests', 'opportunities',
                 'candidate_profiles', 'ai_sessions', 'chunks', 'events', 'answers', 'interviews'):
        op.drop_table(name)
