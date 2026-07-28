"""Repository for post metadata and bodies."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from datetime import datetime

from reddit_reader.models import PostBody, PostMeta


def _row_to_meta(row: sqlite3.Row) -> PostMeta:
    return PostMeta(
        id=row["id"],
        subreddit=row["subreddit"],
        author=row["author"],
        title=row["title"],
        permalink=row["permalink"],
        created_utc=datetime.fromisoformat(row["created_utc"]),
        score=row["score"],
        crosspost_parent=row["crosspost_parent"],
        available=bool(row["available"]),
    )


class PostRepository:
    """Reads and writes `post_meta` and `post_body`."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert_meta(self, post: PostMeta) -> None:
        self.upsert_many([post])

    def upsert_many(self, posts: Iterable[PostMeta]) -> None:
        self.conn.executemany(
            """
            INSERT INTO post_meta
                (id, subreddit, author, title, permalink, created_utc, score,
                 crosspost_parent, available)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                title = excluded.title,
                score = excluded.score,
                crosspost_parent = excluded.crosspost_parent,
                available = excluded.available
            """,
            [
                (
                    p.id,
                    p.subreddit,
                    p.author,
                    p.title,
                    p.permalink,
                    p.created_utc.isoformat(),
                    p.score,
                    p.crosspost_parent,
                    int(p.available),
                )
                for p in posts
            ],
        )
        self.conn.commit()

    def get_meta(self, post_id: str) -> PostMeta | None:
        row = self.conn.execute("SELECT * FROM post_meta WHERE id = ?", (post_id,)).fetchone()
        return _row_to_meta(row) if row else None

    def get_many(self, post_ids: Sequence[str]) -> list[PostMeta]:
        if not post_ids:
            return []
        placeholders = ", ".join("?" * len(post_ids))
        rows = self.conn.execute(
            f"SELECT * FROM post_meta WHERE id IN ({placeholders})", tuple(post_ids)
        ).fetchall()
        return [_row_to_meta(row) for row in rows]

    def by_author(self, author: str) -> list[PostMeta]:
        rows = self.conn.execute(
            "SELECT * FROM post_meta WHERE author = ? ORDER BY created_utc", (author,)
        ).fetchall()
        return [_row_to_meta(row) for row in rows]

    def set_body(self, body: PostBody) -> None:
        self.conn.execute(
            """
            INSERT INTO post_body (post_id, selftext) VALUES (?, ?)
            ON CONFLICT (post_id) DO UPDATE SET selftext = excluded.selftext
            """,
            (body.post_id, body.selftext),
        )
        self.conn.commit()

    def get_body(self, post_id: str) -> PostBody | None:
        row = self.conn.execute("SELECT * FROM post_body WHERE post_id = ?", (post_id,)).fetchone()
        return PostBody(post_id=row["post_id"], selftext=row["selftext"]) if row else None

    def delete_bodies(self, post_ids: Sequence[str]) -> int:
        if not post_ids:
            return 0
        placeholders = ", ".join("?" * len(post_ids))
        cursor = self.conn.execute(
            f"DELETE FROM post_body WHERE post_id IN ({placeholders})", tuple(post_ids)
        )
        self.conn.commit()
        return cursor.rowcount

    def mark_unavailable(self, post_id: str) -> None:
        self.conn.execute("UPDATE post_meta SET available = 0 WHERE id = ?", (post_id,))
        self.conn.commit()

    def orphaned_ids(self) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT id FROM post_meta
            WHERE id NOT IN (SELECT post_id FROM story_part)
            ORDER BY id
            """
        ).fetchall()
        return [row["id"] for row in rows]

    def delete_meta(self, post_ids: Sequence[str]) -> int:
        if not post_ids:
            return 0
        placeholders = ", ".join("?" * len(post_ids))
        cursor = self.conn.execute(
            f"DELETE FROM post_meta WHERE id IN ({placeholders})", tuple(post_ids)
        )
        self.conn.commit()
        return cursor.rowcount

    def record_fetch(self, subreddit: str, when: datetime) -> None:
        """Stamp a subreddit's own `fetch_state` row so refreshing it doesn't
        disturb another subreddit's position."""
        self.conn.execute(
            """
            INSERT INTO fetch_state (subreddit, last_fetched) VALUES (?, ?)
            ON CONFLICT (subreddit) DO UPDATE SET last_fetched = excluded.last_fetched
            """,
            (subreddit, when.isoformat()),
        )
        self.conn.commit()

    def last_fetched(self, subreddit: str) -> datetime | None:
        row = self.conn.execute(
            "SELECT last_fetched FROM fetch_state WHERE subreddit = ?", (subreddit,)
        ).fetchone()
        if row is None or row["last_fetched"] is None:
            return None
        return datetime.fromisoformat(row["last_fetched"])
