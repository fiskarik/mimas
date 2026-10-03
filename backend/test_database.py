"""PostgreSQL-only runtime contract; legacy SQLite tests are archived in Git."""
import pytest
from backend.database import Database


def test_database_url_is_required_and_sqlite_is_rejected():
    with pytest.raises(RuntimeError, match='DATABASE_URL'):
        Database(None)
    with pytest.raises(RuntimeError, match='PostgreSQL only'):
        Database('sqlite:///mimas.sqlite3')
