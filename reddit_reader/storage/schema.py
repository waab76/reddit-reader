"""SQLite DDL and schema versioning."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 1

DDL = """
CREATE TABLE IF NOT EXISTS post_meta (
    id               TEXT PRIMARY KEY,
    subreddit        TEXT NOT NULL,
    author           TEXT NOT NULL,
    title            TEXT NOT NULL,
    permalink        TEXT NOT NULL,
    created_utc      TEXT NOT NULL,
    score            INTEGER NOT NULL,
    crosspost_parent TEXT,
    available        INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_post_meta_author ON post_meta (author);
CREATE INDEX IF NOT EXISTS idx_post_meta_subreddit ON post_meta (subreddit);

CREATE TABLE IF NOT EXISTS post_body (
    post_id  TEXT PRIMARY KEY REFERENCES post_meta (id) ON DELETE CASCADE,
    selftext TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS story (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    series_key             TEXT NOT NULL,
    title                  TEXT NOT NULL,
    author                 TEXT NOT NULL,
    volume                 INTEGER,
    tracked                INTEGER NOT NULL DEFAULT 0,
    last_read_part         TEXT,
    last_read_offset       REAL NOT NULL DEFAULT 0.0,
    exported_markdown_path TEXT,
    exported_at            TEXT,
    last_updated_at        TEXT
);

CREATE INDEX IF NOT EXISTS idx_story_series_key ON story (series_key);

CREATE TABLE IF NOT EXISTS story_part (
    post_id             TEXT NOT NULL REFERENCES post_meta (id) ON DELETE CASCADE,
    story_id            INTEGER NOT NULL REFERENCES story (id) ON DELETE CASCADE,
    part_number         TEXT,
    part_label          TEXT,
    segment             INTEGER,
    segment_count       INTEGER,
    sort_key            TEXT,
    alternate_post_ids  TEXT NOT NULL DEFAULT '',
    newly_filled        INTEGER NOT NULL DEFAULT 0,
    match_confidence    REAL NOT NULL DEFAULT 0.0,
    PRIMARY KEY (story_id, post_id)
);

CREATE TABLE IF NOT EXISTS unavailable_part (
    story_id    INTEGER NOT NULL REFERENCES story (id) ON DELETE CASCADE,
    part_number TEXT NOT NULL,
    auto_marked INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (story_id, part_number)
);

CREATE TABLE IF NOT EXISTS cleaning_rule (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id       INTEGER NOT NULL REFERENCES story (id) ON DELETE CASCADE,
    position       TEXT NOT NULL,
    block          TEXT NOT NULL,
    seen_in_parts  INTEGER NOT NULL,
    approved       INTEGER
);

CREATE TABLE IF NOT EXISTS fetch_state (
    subreddit    TEXT PRIMARY KEY,
    last_fetched TEXT,
    newest_seen  TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS post_search USING fts5 (
    post_id UNINDEXED,
    title,
    body
);
"""


def apply_schema(conn: sqlite3.Connection) -> None:
    """Create every table if absent and stamp the schema version."""
    conn.executescript(DDL)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
