"""Alembic configuration; DATABASE_URL is the single database source of truth."""
import os

from alembic import context
from sqlalchemy import create_engine, pool

from backend.database import Base
import backend.ai_web  # noqa: F401
import backend.marketplace  # noqa: F401
import backend.companies  # noqa: F401
import backend.media  # noqa: F401
import backend.yandex_budget  # noqa: F401

config = context.config
target_metadata = Base.metadata
url = os.getenv('DATABASE_URL')
if not url:
    raise RuntimeError('DATABASE_URL is required for migrations')
if url.startswith('postgres://'):
    url = 'postgresql://' + url[len('postgres://'):]
if not url.startswith('postgresql://') and not url.startswith('postgresql+'):
    raise RuntimeError('Migrations support PostgreSQL only')


def run_migrations_offline():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={'paramstyle': 'named'})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
