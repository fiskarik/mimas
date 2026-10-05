"""Opt-in interview helper monitoring, product catalog and retained summaries.

Revision ID: 0003_monitor
Revises: 0002_tenants_ai
"""
from alembic import op
import sqlalchemy as sa


revision = '0003_monitor'
down_revision = '0002_tenants_ai'
branch_labels = None
depends_on = None


SEED_PRODUCTS = (
    ('finalroundai', 'Final Round AI', 'https://docs.finalroundai.com/docs/live-copilot/using-copilot', 'finalroundai.com'),
    ('interviewcoder', 'InterviewCoder', 'https://www.interviewcoder.co/', 'interviewcoder.co'),
    ('lockedinai', 'LockedIn AI', 'https://www.lockedinai.com/desktop-app', 'lockedinai.com'),
    ('parakeetai', 'ParakeetAI', 'https://www.parakeet-ai.com/', 'parakeet-ai.com'),
    ('cluely', 'Cluely', 'https://cluely.com/', 'cluely.com'),
    ('senseiai', 'Sensei AI', 'https://www.senseicopilot.com/', 'senseicopilot.com'),
    ('anyqai', 'AnyQ', 'https://www.anyqai.com/', 'anyqai.com'),
    ('talkbuoy', 'TalkBuoy', 'https://www.talkbuoy.com/', 'talkbuoy.com'),
)


def upgrade():
    op.create_table(
        'monitor_products',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('source_url', sa.Text(), nullable=False),
        sa.Column('category', sa.Text(), nullable=False),
        sa.Column('enabled', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('verified_at', sa.Float(), nullable=False),
        sa.Column('updated_at', sa.Float(), nullable=False),
    )
    op.create_table(
        'monitor_signatures',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('product_id', sa.Text(), sa.ForeignKey('monitor_products.id'), nullable=False),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('source_url', sa.Text(), nullable=False),
        sa.Column('verified_at', sa.Float(), nullable=False),
        sa.Column('enabled', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('updated_at', sa.Float(), nullable=False),
        sa.UniqueConstraint('product_id', 'kind', 'value', name='uq_monitor_signature'),
    )
    op.create_index('ix_monitor_signatures_product', 'monitor_signatures', ['product_id'])
    op.create_table(
        'monitor_sessions',
        sa.Column('session_id', sa.Text(), sa.ForeignKey('ai_sessions.id'), primary_key=True),
        sa.Column('platform', sa.Text(), nullable=False),
        sa.Column('consented_at', sa.Float(), nullable=False),
    )
    op.create_table(
        'monitor_pair_codes',
        sa.Column('code_hash', sa.Text(), primary_key=True),
        sa.Column('session_id', sa.Text(), sa.ForeignKey('ai_sessions.id'), nullable=False),
        sa.Column('component', sa.Text(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('expires_at', sa.Float(), nullable=False),
        sa.Column('claimed_at', sa.Float()),
    )
    op.create_index('ix_monitor_pair_codes_session', 'monitor_pair_codes', ['session_id'])
    op.create_table(
        'monitor_clients',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('session_id', sa.Text(), sa.ForeignKey('ai_sessions.id'), nullable=False),
        sa.Column('component', sa.Text(), nullable=False),
        sa.Column('token_hash', sa.Text(), nullable=False, unique=True),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('expires_at', sa.Float(), nullable=False),
        sa.Column('last_seen', sa.Float(), nullable=False),
        sa.Column('revoked', sa.Integer(), nullable=False, server_default='0'),
    )
    op.create_index('ix_monitor_clients_session', 'monitor_clients', ['session_id'])
    op.create_table(
        'monitor_observations',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('session_id', sa.Text(), sa.ForeignKey('ai_sessions.id'), nullable=False),
        sa.Column('client_id', sa.Text(), sa.ForeignKey('monitor_clients.id')),
        sa.Column('event_id', sa.Text()),
        sa.Column('product_id', sa.Text(), sa.ForeignKey('monitor_products.id')),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('state', sa.Text(), nullable=False),
        sa.Column('observed_at', sa.Float(), nullable=False),
        sa.UniqueConstraint('client_id', 'event_id', name='uq_monitor_client_event'),
    )
    op.create_index('ix_monitor_observations_session_time', 'monitor_observations',
                    ['session_id', 'observed_at'])
    op.create_table(
        'monitor_summaries',
        sa.Column('session_id', sa.Text(), sa.ForeignKey('ai_sessions.id'), primary_key=True),
        sa.Column('product_id', sa.Text(), primary_key=True),
        sa.Column('kind', sa.Text(), primary_key=True),
        sa.Column('detected_count', sa.Integer(), nullable=False, server_default='0'),
    )
    # Only official web domains are known at seed time. Executable/window
    # signatures remain disabled until verified against installed software.
    from datetime import datetime, timezone
    verified = datetime(2026, 10, 5, tzinfo=timezone.utc).timestamp()
    products = sa.table('monitor_products', *[
        sa.column(name, kind) for name, kind in (
            ('id', sa.Text()), ('name', sa.Text()), ('source_url', sa.Text()),
            ('category', sa.Text()), ('enabled', sa.Integer()),
            ('verified_at', sa.Float()), ('updated_at', sa.Float()))])
    signatures = sa.table('monitor_signatures', *[
        sa.column(name, kind) for name, kind in (
            ('id', sa.Text()), ('product_id', sa.Text()), ('kind', sa.Text()),
            ('value', sa.Text()), ('source_url', sa.Text()),
            ('verified_at', sa.Float()), ('enabled', sa.Integer()),
            ('updated_at', sa.Float()))])
    op.bulk_insert(products, [dict(id=pid, name=name, source_url=url,
                                   category='live_answer_copilot', enabled=1,
                                   verified_at=verified, updated_at=verified)
                              for pid, name, url, _ in SEED_PRODUCTS])
    op.bulk_insert(signatures, [dict(id=f'{pid}-domain', product_id=pid,
                                     kind='domain', value=domain, source_url=url,
                                     verified_at=verified, enabled=1,
                                     updated_at=verified)
                                for pid, _, url, domain in SEED_PRODUCTS])


def downgrade():
    raise RuntimeError('Monitoring consent and observations require a backup for rollback.')
