"""Safely copy the local legacy demo into a distinct, migrated dev PostgreSQL DB.

Never points at the production DATABASE_URL. The destination must be empty
apart from the legacy company created by Alembic. All row inserts and checksum
checks are one transaction. Optional video transfer is resumable with
--media-only and uses a different S3 bucket.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

from sqlalchemy import MetaData, Table, create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[1]
SOURCE_TABLES = (
    'candidate_profiles', 'opportunities', 'interviews', 'ai_sessions',
    'answers', 'events', 'chunks', 'candidate_interests', 'candidate_assessments',
)
DESTINATION = {'candidate_assessments': 'legacy_candidate_assessments'}
EMPTY_TABLES = tuple(DESTINATION.get(name, name) for name in SOURCE_TABLES) + (
    'vacancy_templates', 'candidate_assessments', 'video_recordings',
    'yandex_budget_months', 'yandex_cost_entries',
)
LEGACY_COLUMNS = {
    'interviews': {'id', 'token', 'name', 'status', 'created', 'started',
                   'completed', 'mode', 'expected_chunks', 'recording_complete'},
    'answers': {'interview_id', 'question_id', 'text', 'created', 'evaluation', 'next_question'},
    'events': {'interview_id', 'id', 'kind', 'elapsed', 'detail', 'created'},
    'chunks': {'interview_id', 'seq', 'digest', 'size'},
    'ai_sessions': {'id', 'token_hash', 'model', 'started', 'state', 'trace', 'pending'},
    'candidate_profiles': {'id', 'token_hash', 'name', 'level', 'stack',
                           'years_experience', 'github_url', 'desired_salary_rub',
                           'discoverable', 'created'},
    'opportunities': {'id', 'company_name', 'title', 'description', 'level', 'stack',
                      'salary_min_rub', 'salary_max_rub', 'employment_type',
                      'status', 'created'},
    'candidate_interests': {'candidate_id', 'opportunity_id', 'created'},
    'candidate_assessments': {'candidate_id', 'session_id', 'created'},
}


class ImportConflict(RuntimeError):
    pass


def _normal_url(raw: str):
    raw = 'postgresql://' + raw[len('postgres://'):] if raw.startswith('postgres://') else raw
    url = make_url(raw)
    if url.get_backend_name() != 'postgresql':
        raise ImportConflict('MIMAS_DEV_DATABASE_URL must use PostgreSQL')
    return url


def _identity(url):
    # A second database user does not make the same host/database safe.
    return (url.host.lower() if url.host else '', url.port or 5432,
            url.database or '')


def validate_target_url(raw: str | None, production_raw: str | None,
                        environment: str, confirm_name: str | None):
    if environment.lower() == 'production':
        raise ImportConflict('Import is disabled when MIMAS_ENV=production')
    if not raw:
        raise ImportConflict('Set explicit MIMAS_DEV_DATABASE_URL for the separate dev database')
    target = _normal_url(raw)
    if production_raw and _identity(target) == _identity(_normal_url(production_raw)):
        raise ImportConflict('Dev PostgreSQL target matches DATABASE_URL')
    if not confirm_name or confirm_name != target.database:
        raise ImportConflict('Pass --confirm-db with the exact dev database name')
    return target


def _source_rows(path: Path):
    if not path.is_file():
        raise ImportConflict('Legacy SQLite source file does not exist')
    source = sqlite3.connect(f'file:{path.resolve().as_posix()}?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    source.execute('BEGIN')
    actual_tables = {row['name'] for row in source.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if actual_tables != set(LEGACY_COLUMNS):
        source.close()
        raise ImportConflict('SQLite source is not the expected legacy demo schema')
    for name, expected in LEGACY_COLUMNS.items():
        fields = {row['name'] for row in source.execute(f'PRAGMA table_info("{name}")')}
        if fields != expected:
            source.close()
            raise ImportConflict(f'SQLite table {name} differs from legacy schema')
    return source


def _transformed(name: str, records: list[dict]) -> list[dict]:
    result = []
    for record in records:
        item = dict(record)
        if name in ('opportunities', 'interviews'):
            item['company_id'] = 'legacy'
        if name == 'opportunities' and item['status'] == 'open':
            item['status'] = 'draft'
        if name == 'ai_sessions':
            item.update(candidate_id=None, opportunity_id=None, archived=1)
        result.append(item)
    return result


def _snapshot(source) -> dict[str, list[dict]]:
    return {name: _transformed(name, [dict(row) for row in source.execute(f'SELECT * FROM "{name}"')])
            for name in SOURCE_TABLES}


def checksum(rows: list[dict]) -> str:
    digest = hashlib.sha256()
    encoded = [json.dumps(row, sort_keys=True, ensure_ascii=False,
                          separators=(',', ':'), default=str).encode('utf-8')
               for row in rows]
    for record in sorted(encoded):
        digest.update(len(record).to_bytes(8, 'big'))
        digest.update(record)
    return digest.hexdigest()


def _reflected(connection):
    missing = set(EMPTY_TABLES) - set(inspect(connection).get_table_names())
    if missing:
        raise ImportConflict('Dev PostgreSQL schema is incomplete; apply Alembic migrations first')
    metadata = MetaData()
    return {name: Table(name, metadata, autoload_with=connection) for name in set(EMPTY_TABLES)}


def preflight_target(connection, tables) -> None:
    inspector = inspect(connection)
    existing = set(inspector.get_table_names())
    needed = set(EMPTY_TABLES) | {'companies', 'alembic_version'}
    if not needed <= existing:
        raise ImportConflict('Dev PostgreSQL schema is incomplete; apply Alembic migrations first')
    revision = connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one_or_none()
    if revision != '0002_tenants_ai':
        raise ImportConflict('Dev PostgreSQL must be at Alembic revision 0002_tenants_ai')
    legacy = connection.execute(text("SELECT COUNT(*) FROM companies WHERE id = 'legacy'")).scalar_one()
    other_companies = connection.execute(text("SELECT COUNT(*) FROM companies WHERE id <> 'legacy'")).scalar_one()
    if legacy != 1 or other_companies:
        raise ImportConflict('Dev PostgreSQL must contain only the migrated legacy company')
    occupied = {name: connection.scalar(select(func.count()).select_from(tables[name]))
                for name in EMPTY_TABLES}
    occupied = {name: count for name, count in occupied.items() if count}
    if occupied:
        raise ImportConflict('Dev PostgreSQL is not empty: ' +
                             ', '.join(f'{name}={count}' for name, count in sorted(occupied.items())))


def verify_import(connection, tables, expected: dict[str, list[dict]]) -> dict[str, dict]:
    result = {}
    for source_name in SOURCE_TABLES:
        name = DESTINATION.get(source_name, source_name)
        fields = list(expected[source_name][0]) if expected[source_name] else list(LEGACY_COLUMNS[source_name])
        if source_name in ('interviews', 'opportunities'):
            fields = list(fields) + ([] if 'company_id' in fields else ['company_id'])
        if source_name == 'ai_sessions':
            fields = list(fields) + [field for field in ('candidate_id', 'opportunity_id', 'archived')
                                     if field not in fields]
        table = tables[name]
        actual = [dict(row) for row in connection.execute(
            select(*(table.c[field] for field in fields))).mappings()]
        expected_rows = expected[source_name]
        if len(actual) != len(expected_rows) or checksum(actual) != checksum(expected_rows):
            raise ImportConflict(f'Checksum mismatch after importing {name}; transaction rolled back')
        result[name] = {'rows': len(actual), 'sha256': checksum(actual)}
    return result


def _media_files(source, recording_root: Path) -> list[dict]:
    root = recording_root.resolve()
    interviews = {row['id']: dict(row) for row in source.execute(
        'SELECT id, recording_complete FROM interviews')}
    found = []
    for row in source.execute('SELECT interview_id, seq, digest, size FROM chunks'):
        iid, seq = row['interview_id'], int(row['seq'])
        if iid not in interviews or seq < 0 or seq >= 1440:
            raise ImportConflict('Invalid recording metadata in legacy SQLite')
        folder = (root / iid).resolve()
        if not folder.is_relative_to(root):
            raise ImportConflict('Unsafe recording path in legacy SQLite')
        path = folder / f'{seq:05d}.webm'
        if not path.is_file():
            raise ImportConflict(f'Missing video chunk for interview {iid}')
        if path.stat().st_size != row['size'] or hashlib.sha256(path.read_bytes()).hexdigest() != row['digest']:
            raise ImportConflict(f'Video chunk checksum mismatch for interview {iid}')
        found.append({'path': path, 'key': f'legacy-recordings/{iid}/{path.name}',
                      'size': path.stat().st_size, 'sha256': row['digest']})
    for iid, interview in interviews.items():
        folder = (root / iid).resolve()
        if not folder.is_relative_to(root):
            raise ImportConflict('Unsafe recording path in legacy SQLite')
        path = folder / 'interview.webm'
        if interview['recording_complete'] and not path.is_file():
            raise ImportConflict(f'Missing completed video for interview {iid}')
        if path.is_file():
            found.append({'path': path, 'key': f'legacy-recordings/{iid}/interview.webm',
                          'size': path.stat().st_size,
                          'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    return found


def _s3_client(args):
    bucket = os.getenv('MIMAS_DEV_S3_BUCKET')
    if not bucket or args.confirm_bucket != bucket:
        raise ImportConflict('Set MIMAS_DEV_S3_BUCKET and matching --confirm-bucket')
    if bucket == os.getenv('MIMAS_S3_BUCKET'):
        raise ImportConflict('Dev S3 bucket must differ from the application production bucket')
    access = os.getenv('MIMAS_DEV_S3_ACCESS_KEY')
    secret = os.getenv('MIMAS_DEV_S3_SECRET_KEY')
    if not access or not secret:
        raise ImportConflict('Set separate development S3 credentials')
    try:
        import boto3
    except ImportError:
        raise ImportConflict('Install boto3 before copying media') from None
    client = boto3.client(
        's3', endpoint_url=os.getenv('MIMAS_DEV_S3_ENDPOINT', 'https://storage.yandexcloud.net'),
        region_name=os.getenv('MIMAS_DEV_S3_REGION', 'ru-central1'),
        aws_access_key_id=access, aws_secret_access_key=secret)
    return client, bucket


def _copy_media(files: list[dict], args) -> dict:
    client, bucket = _s3_client(args)
    copied = skipped = 0
    for item in files:
        try:
            remote = client.head_object(Bucket=bucket, Key=item['key'])
        except Exception as exc:
            status = getattr(getattr(exc, 'response', {}), 'get', lambda *_: {})('ResponseMetadata', {}).get('HTTPStatusCode')
            if status != 404:
                raise ImportConflict(f'Could not inspect dev S3 object {item["key"]}') from None
            remote = None
        if remote:
            if (remote.get('ContentLength') != item['size'] or
                    remote.get('Metadata', {}).get('sha256') != item['sha256']):
                raise ImportConflict(f'Dev S3 object conflicts with local video: {item["key"]}')
            skipped += 1
            continue
        client.upload_file(str(item['path']), bucket, item['key'],
                           ExtraArgs={'Metadata': {'sha256': item['sha256']}})
        remote = client.head_object(Bucket=bucket, Key=item['key'])
        if (remote.get('ContentLength') != item['size'] or
                remote.get('Metadata', {}).get('sha256') != item['sha256']):
            raise ImportConflict(f'Dev S3 verification failed for {item["key"]}')
        copied += 1
    return {'copied': copied, 'already_present': skipped}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'data' / 'demo.sqlite3')
    parser.add_argument('--recordings', type=Path, default=ROOT / 'data' / 'recordings')
    parser.add_argument('--confirm-db', required=True, help='Exact development PostgreSQL database name')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--copy-media', action='store_true')
    parser.add_argument('--media-only', action='store_true',
                        help='Resume S3 copy after a verified successful DB import')
    parser.add_argument('--confirm-bucket', help='Exact separate development S3 bucket name')
    args = parser.parse_args(argv)
    if args.media_only and not args.copy_media:
        parser.error('--media-only requires --copy-media')
    url = validate_target_url(os.getenv('MIMAS_DEV_DATABASE_URL'), os.getenv('DATABASE_URL'),
                              os.getenv('MIMAS_ENV', ''), args.confirm_db)
    source = _source_rows(args.source)
    try:
        expected = _snapshot(source)
        media = _media_files(source, args.recordings) if args.copy_media else []
        engine = create_engine(url, pool_pre_ping=True)
        try:
            with engine.connect().execution_options(isolation_level='SERIALIZABLE') as connection:
                with connection.begin():
                    connection.execute(text('SELECT pg_advisory_xact_lock(62714622)'))
                    tables = _reflected(connection)
                    if args.media_only:
                        report = verify_import(connection, tables, expected)
                    else:
                        preflight_target(connection, tables)
                        if args.dry_run:
                            report = {DESTINATION.get(name, name): {
                                'rows': len(expected[name]), 'sha256': checksum(expected[name])
                            } for name in SOURCE_TABLES}
                        else:
                            for source_name in SOURCE_TABLES:
                                records = expected[source_name]
                                if records:
                                    connection.execute(tables[DESTINATION.get(source_name, source_name)].insert(),
                                                       records)
                            report = verify_import(connection, tables, expected)
                # Commit has succeeded before any remote video transfer.
            if args.copy_media and not args.dry_run:
                media_result = _copy_media(media, args)
            else:
                media_result = {'planned_files': len(media),
                                'planned_bytes': sum(item['size'] for item in media)}
            print(json.dumps({'database': args.confirm_db, 'dry_run': args.dry_run,
                              'media_only': args.media_only, 'tables': report,
                              'media': media_result}, ensure_ascii=False, indent=2))
        finally:
            engine.dispose()
    finally:
        source.close()


if __name__ == '__main__':
    try:
        main()
    except (ImportConflict, SQLAlchemyError) as exc:
        # Do not print raw SQLAlchemy connection errors, which can contain
        # hostnames or credentials.
        message = str(exc) if isinstance(exc, ImportConflict) else 'Dev PostgreSQL operation failed'
        print(message, file=sys.stderr)
        raise SystemExit(1) from None
