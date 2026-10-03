"""Safety checks for the explicit legacy SQLite -> development PostgreSQL importer."""
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

import pytest
from sqlalchemy import create_engine, text

from scripts.import_legacy_demo import (
    EMPTY_TABLES, ImportConflict, _identity, _media_files, _normal_url,
    _reflected, _transformed, checksum, preflight_target, validate_target_url,
    verify_import, SOURCE_TABLES,
)


def test_dev_url_must_be_explicit_distinct_and_confirmed():
    dev = 'postgresql://dev:secret@db.example/mimas_dev'
    prod_same_db = 'postgresql://prod:other@db.example/mimas_dev'
    assert validate_target_url(dev, None, '', 'mimas_dev').database == 'mimas_dev'
    assert _identity(_normal_url(dev)) == _identity(_normal_url(prod_same_db))
    with pytest.raises(ImportConflict):
        validate_target_url(dev, prod_same_db, '', 'mimas_dev')
    with pytest.raises(ImportConflict):
        validate_target_url(None, None, '', 'mimas_dev')
    with pytest.raises(ImportConflict):
        validate_target_url(dev, dev, '', 'mimas_dev')
    with pytest.raises(ImportConflict):
        validate_target_url(dev, None, 'production', 'mimas_dev')
    with pytest.raises(ImportConflict):
        validate_target_url(dev, None, '', 'not_my_database')


def test_transforms_legacy_rows_without_changing_original():
    old = [{'id': 'vacancy', 'status': 'open', 'company_name': 'Старая'}]
    imported = _transformed('opportunities', old)
    assert old[0] == {'id': 'vacancy', 'status': 'open', 'company_name': 'Старая'}
    assert imported[0]['status'] == 'draft'
    assert imported[0]['company_id'] == 'legacy'
    assert checksum(imported) != checksum(old)
    assert checksum(imported) == checksum(list(reversed(imported)))


def test_preflight_rejects_nonempty_dev_and_verifier_catches_mismatch():
    # Disposable SQLite checks control flow only. Runtime importer insists on
    # a real PostgreSQL URL and SERIALIZABLE transaction.
    engine = create_engine('sqlite://')
    with engine.begin() as db:
        db.execute(text('CREATE TABLE companies (id TEXT PRIMARY KEY)'))
        db.execute(text('INSERT INTO companies (id) VALUES ("legacy")'))
        db.execute(text('CREATE TABLE alembic_version (version_num TEXT)'))
        db.execute(text('INSERT INTO alembic_version VALUES ("0002_tenants_ai")'))
        for name in EMPTY_TABLES:
            fields = {'candidate_id', 'session_id', 'opportunity_id', 'company_id',
                      'archived'} if name in ('legacy_candidate_assessments', 'candidate_assessments') else {'id'}
            columns = ', '.join(f'{field} TEXT' for field in sorted(fields))
            db.execute(text(f'CREATE TABLE {name} ({columns})'))
        tables = _reflected(db)
        preflight_target(db, tables)
        db.execute(text('INSERT INTO candidate_profiles (id) VALUES ("candidate")'))
        with pytest.raises(ImportConflict, match='not empty'):
            preflight_target(db, tables)
    engine.dispose()


def test_media_manifest_rejects_bad_chunk():
    source = sqlite3.connect(':memory:')
    source.row_factory = sqlite3.Row
    source.execute('CREATE TABLE interviews (id TEXT, recording_complete INTEGER)')
    source.execute('CREATE TABLE chunks (interview_id TEXT, seq INTEGER, digest TEXT, size INTEGER)')
    iid = 'a' * 32
    source.execute('INSERT INTO interviews VALUES (?, 0)', (iid,))
    source.execute('INSERT INTO chunks VALUES (?, 0, ?, 4)', (iid, '0' * 64))
    with TemporaryDirectory(prefix='mimas-import-', dir=Path(__file__).resolve().parents[1]) as tempdir:
        root = Path(tempdir)
        folder = root / iid
        folder.mkdir()
        (folder / '00000.webm').write_bytes(b'test')
        with pytest.raises(ImportConflict, match='checksum mismatch'):
            _media_files(source, root)
    source.close()



def test_verifier_rejects_count_or_checksum_drift():
    import backend.ai_web
    import backend.companies
    import backend.marketplace
    import backend.media
    import backend.yandex_budget
    from backend.database import Base
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with engine.begin() as db:
        tables = _reflected(db)
        expected = {name: [] for name in SOURCE_TABLES}
        expected['candidate_profiles'] = [{'id': 'missing-candidate'}]
        with pytest.raises(ImportConflict, match='Checksum mismatch'):
            verify_import(db, tables, expected)
    engine.dispose()
