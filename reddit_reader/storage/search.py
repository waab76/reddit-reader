"""FTS5 full-text index over post titles and (for tracked stories) bodies."""

from __future__ import annotations

import re
import sqlite3

from reddit_reader.models import PostMeta

_FTS_SPECIAL = re.compile(r"[^\w\s]")


def _sanitize(query: str) -> str:
    """Strip FTS5 operators so user input can never be a malformed MATCH expression."""
    cleaned = _FTS_SPECIAL.sub(" ", query).strip()
    terms = [t for t in cleaned.split() if t]
    return " ".join(f'"{t}"' for t in terms)


class SearchIndex:
    """Maintains and queries the `post_search` FTS5 table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def _current_body(self, post_id: str) -> str:
        row = self.conn.execute(
            "SELECT body FROM post_search WHERE post_id = ?", (post_id,)
        ).fetchone()
        return row["body"] if row else ""

    def _write(self, post_id: str, title: str, body: str) -> None:
        self.conn.execute("DELETE FROM post_search WHERE post_id = ?", (post_id,))
        self.conn.execute(
            "INSERT INTO post_search (post_id, title, body) VALUES (?, ?, ?)",
            (post_id, title, body),
        )
        self.conn.commit()

    def _current_title(self, post_id: str) -> str:
        row = self.conn.execute(
            "SELECT title FROM post_search WHERE post_id = ?", (post_id,)
        ).fetchone()
        return row["title"] if row else ""

    def index_title(self, post: PostMeta) -> None:
        self._write(post.id, post.title, self._current_body(post.id))

    def index_body(self, post_id: str, selftext: str) -> None:
        self._write(post_id, self._current_title(post_id), selftext)

    def remove_body(self, post_id: str) -> None:
        self._write(post_id, self._current_title(post_id), "")

    def remove(self, post_id: str) -> None:
        self.conn.execute("DELETE FROM post_search WHERE post_id = ?", (post_id,))
        self.conn.commit()

    def search(self, query: str, limit: int = 50) -> list[str]:
        match = _sanitize(query)
        if not match:
            return []
        rows = self.conn.execute(
            """
            SELECT post_id FROM post_search
            WHERE post_search MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (match, limit),
        ).fetchall()
        return [row["post_id"] for row in rows]
