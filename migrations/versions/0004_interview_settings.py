"""Versioned company interview settings.

Revision ID: 0004_interview_settings
Revises: 0003_monitor
"""
from alembic import op
import sqlalchemy as sa

revision = '0004_interview_settings'
down_revision = '0003_monitor'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('vacancy_templates', sa.Column(
        'settings_json', sa.Text(), nullable=False,
        server_default='{"max_questions":8,"max_follow_ups":1,"duration_minutes":20}'))


def downgrade():
    op.drop_column('vacancy_templates', 'settings_json')
