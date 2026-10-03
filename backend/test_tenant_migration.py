"""Offline PostgreSQL DDL protects the legacy association during upgrade."""
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_tenant_migration_preserves_legacy_rows_in_offline_sql():
    env = {**os.environ, 'DATABASE_URL': 'postgresql://mimas:test@localhost/mimas'}
    result = subprocess.run(
        [sys.executable, '-m', 'alembic', 'upgrade', 'head', '--sql'],
        cwd=ROOT, env=env, text=True, capture_output=True, check=True)
    sql = result.stdout
    assert 'CREATE TABLE companies' in sql
    assert 'CREATE TABLE vacancy_templates' in sql
    assert 'CREATE TABLE video_recordings' in sql
    assert 'CREATE TABLE yandex_budget_months' in sql
    assert "UPDATE opportunities SET company_id = 'legacy'" in sql
    assert "UPDATE interviews SET company_id = 'legacy'" in sql
    assert 'UPDATE ai_sessions SET archived = 1' in sql
    copied = sql.index('INSERT INTO legacy_candidate_assessments')
    dropped = sql.index('DROP TABLE candidate_assessments', copied)
    recreated = sql.index('CREATE TABLE candidate_assessments', dropped)
    assert copied < dropped < recreated
    assert 'DROP TABLE ai_sessions' not in sql
