"""Apply MIMAS migrations without silently stamping an unknown live schema."""
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
LEGACY_TABLES = {
    'interviews': {'id', 'token', 'name', 'status', 'created', 'started', 'completed', 'mode',
                   'expected_chunks', 'recording_complete'},
    'answers': {'interview_id', 'question_id', 'text', 'created', 'evaluation', 'next_question'},
    'events': {'interview_id', 'id', 'kind', 'elapsed', 'detail', 'created'},
    'chunks': {'interview_id', 'seq', 'digest', 'size'},
    'ai_sessions': {'id', 'token_hash', 'model', 'started', 'state', 'trace', 'pending'},
    'candidate_profiles': {'id', 'token_hash', 'name', 'level', 'stack', 'years_experience',
                           'github_url', 'desired_salary_rub', 'discoverable', 'created'},
    'opportunities': {'id', 'company_name', 'title', 'description', 'level', 'stack',
                      'salary_min_rub', 'salary_max_rub', 'employment_type', 'status', 'created'},
    'candidate_interests': {'candidate_id', 'opportunity_id', 'created'},
    'candidate_assessments': {'candidate_id', 'session_id', 'created'},
}


def main():
    url = os.getenv('DATABASE_URL')
    if not url:
        raise SystemExit('DATABASE_URL must point to PostgreSQL')
    url = 'postgresql://' + url[len('postgres://'):] if url.startswith('postgres://') else url
    if make_url(url).get_backend_name() != 'postgresql':
        raise SystemExit('SQLite is no longer a MIMAS runtime database')
    config = Config(str(ROOT / 'alembic.ini'))
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            unversioned = 'alembic_version' not in tables
            if unversioned and tables:
                if tables != set(LEGACY_TABLES):
                    raise SystemExit('Unversioned database has an unknown table set; migration refused')
                for table, columns in LEGACY_TABLES.items():
                    actual = {column['name'] for column in inspector.get_columns(table)}
                    if actual != columns:
                        raise SystemExit(f'Unversioned table {table} does not match legacy schema')
                if (os.getenv('MIMAS_ENV', '').lower() == 'production' and
                        os.getenv('MIMAS_MIGRATION_BACKUP_CONFIRMED') != '1'):
                    raise SystemExit('Back up production PostgreSQL, then set MIMAS_MIGRATION_BACKUP_CONFIRMED=1')
                command.stamp(config, '0001_legacy')
        command.upgrade(config, 'head')
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
