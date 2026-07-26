from pathlib import Path

from reddit_reader.storage.db import connect
from reddit_reader.storage.schema import SCHEMA_VERSION


def test_connect_creates_all_tables(tmp_path: Path) -> None:
    conn = connect(tmp_path / "test.db")
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    names = {row["name"] for row in rows}
    assert {
        "post_meta",
        "post_body",
        "story",
        "story_part",
        "unavailable_part",
        "cleaning_rule",
        "fetch_state",
    } <= names


def test_connect_records_schema_version(tmp_path: Path) -> None:
    conn = connect(tmp_path / "test.db")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == SCHEMA_VERSION


def test_connect_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    connect(path).close()
    conn = connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_foreign_keys_are_enforced(tmp_path: Path) -> None:
    conn = connect(tmp_path / "test.db")
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_rows_are_accessible_by_name(tmp_path: Path) -> None:
    conn = connect(tmp_path / "test.db")
    row = conn.execute("SELECT 1 AS answer").fetchone()
    assert row["answer"] == 1
