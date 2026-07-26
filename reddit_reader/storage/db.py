"""SQLite connection management."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from reddit_reader.storage.schema import apply_schema


def connect(path: Path) -> sqlite3.Connection:
    """Open (creating if needed) the database at `path` with the schema applied."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_schema(conn)
    return conn
