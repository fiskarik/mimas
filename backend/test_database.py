"""Compatibility and transaction tests independent of the API fixture."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import select
from backend.database import Database, Interview, AnswerRecord, IntegrityEvent, RecordingChunk


def test_original_schema_and_data_remain_readable(tmp_path):
    path = tmp_path / 'legacy.sqlite3'
    with sqlite3.connect(path) as old:
        old.executescript("""
        CREATE TABLE interviews (
            id TEXT PRIMARY KEY, token TEXT NOT NULL, name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'invited', created REAL NOT NULL,
            started REAL, completed REAL, mode TEXT NOT NULL,
            expected_chunks INTEGER, recording_complete INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE answers (
            interview_id TEXT NOT NULL, question_id TEXT NOT NULL, text TEXT NOT NULL,
            created REAL NOT NULL, evaluation TEXT, next_question TEXT,
            PRIMARY KEY(interview_id, question_id));
        CREATE TABLE events (
            id TEXT NOT NULL, interview_id TEXT NOT NULL, kind TEXT NOT NULL,
            elapsed REAL NOT NULL, detail TEXT NOT NULL, created REAL NOT NULL,
            PRIMARY KEY(interview_id, id));
        CREATE TABLE chunks (
            interview_id TEXT NOT NULL, seq INTEGER NOT NULL, digest TEXT NOT NULL,
            size INTEGER NOT NULL, PRIMARY KEY(interview_id, seq));
        INSERT INTO interviews VALUES ('legacy','secret','Candidate','completed',1,2,3,'mock',1,1);
        INSERT INTO answers VALUES ('legacy','python','Original answer',2,NULL,NULL);
        INSERT INTO events VALUES ('event1','legacy','paste',0.5,'Original event',2);
        INSERT INTO chunks VALUES ('legacy',0,'original-digest',123);
        """)
    database = Database(path)
    try:
        with database.session() as db:
            assert db.get(Interview, 'legacy').recording_complete == 1
            assert db.get(AnswerRecord, ('legacy', 'python')).text == 'Original answer'
            assert db.get(IntegrityEvent, ('legacy', 'event1')).detail == 'Original event'
            assert db.get(RecordingChunk, ('legacy', 0)).digest == 'original-digest'
        with database.session(write=True) as db:
            db.add(Interview(id='new', token='new-secret', name='New', created=4, mode='mock'))
        with sqlite3.connect(path) as old:
            assert old.execute('SELECT count(*) FROM interviews').fetchone()[0] == 2
            assert old.execute("SELECT text FROM answers WHERE interview_id='legacy'").fetchone()[0] == 'Original answer'
    finally:
        database.engine.dispose()


def test_rollback_and_parallel_retries(tmp_path):
    database = Database(tmp_path / 'transactions.sqlite3')
    try:
        with database.session(write=True) as db:
            db.add(Interview(id='i', token='token', name='Candidate', created=1, mode='mock'))
        with pytest.raises(RuntimeError):
            with database.session(write=True) as db:
                db.get(Interview, 'i').name = 'Should roll back'
                db.flush()
                raise RuntimeError('Simulated failure')
        def retry(_):
            with database.session(write=True, interview_id='i') as db:
                if not db.get(RecordingChunk, ('i', 0)):
                    db.add(RecordingChunk(interview_id='i', seq=0, digest='same', size=10))
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(retry, range(8)))
        with database.session() as db:
            assert db.get(Interview, 'i').name == 'Candidate'
            assert database.count(db, RecordingChunk, 'i') == 1
    finally:
        database.engine.dispose()


def test_explicit_database_url(tmp_path):
    target = tmp_path / 'configured.sqlite3'
    database = Database(tmp_path / 'unused.sqlite3', f'sqlite+pysqlite:///{target.as_posix()}')
    try:
        assert target.exists()
        assert not (tmp_path / 'unused.sqlite3').exists()
    finally:
        database.engine.dispose()
