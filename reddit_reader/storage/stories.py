"""Repository for stories, their parts, and per-story annotations."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal

from reddit_reader.models import (
    CleaningPosition,
    CleaningRule,
    Story,
    StoryPart,
    UnavailablePart,
)


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _row_to_story(row: sqlite3.Row) -> Story:
    return Story(
        id=row["id"],
        series_key=row["series_key"],
        title=row["title"],
        author=row["author"],
        volume=row["volume"],
        tracked=bool(row["tracked"]),
        last_read_part=row["last_read_part"],
        last_read_offset=row["last_read_offset"],
        exported_markdown_path=row["exported_markdown_path"],
        exported_at=_dt(row["exported_at"]),
        last_updated_at=_dt(row["last_updated_at"]),
    )


def _row_to_part(row: sqlite3.Row) -> StoryPart:
    raw_alternates = row["alternate_post_ids"]
    return StoryPart(
        post_id=row["post_id"],
        story_id=row["story_id"],
        part_number=Decimal(row["part_number"]) if row["part_number"] is not None else None,
        part_label=row["part_label"],
        segment=row["segment"],
        segment_count=row["segment_count"],
        sort_key=row["sort_key"],
        alternate_post_ids=raw_alternates.split(",") if raw_alternates else [],
        newly_filled=bool(row["newly_filled"]),
        match_confidence=row["match_confidence"],
    )


class StoryRepository:
    """Reads and writes `story`, `story_part`, `unavailable_part`, `cleaning_rule`."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(self, story: Story) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO story
                (series_key, title, author, volume, tracked, last_read_part,
                 last_read_offset, exported_markdown_path, exported_at, last_updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                story.series_key,
                story.title,
                story.author,
                story.volume,
                int(story.tracked),
                story.last_read_part,
                story.last_read_offset,
                story.exported_markdown_path,
                story.exported_at.isoformat() if story.exported_at else None,
                story.last_updated_at.isoformat() if story.last_updated_at else None,
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid or 0)

    def get(self, story_id: int) -> Story | None:
        row = self.conn.execute("SELECT * FROM story WHERE id = ?", (story_id,)).fetchone()
        return _row_to_story(row) if row else None

    def all_stories(self) -> list[Story]:
        rows = self.conn.execute("SELECT * FROM story ORDER BY series_key, volume").fetchall()
        return [_row_to_story(row) for row in rows]

    def by_series_key(self, key: str) -> list[Story]:
        rows = self.conn.execute(
            "SELECT * FROM story WHERE series_key = ? ORDER BY volume", (key,)
        ).fetchall()
        return [_row_to_story(row) for row in rows]

    def find_committed(self, series_key: str, volume: int | None) -> Story | None:
        if volume is None:
            row = self.conn.execute(
                "SELECT * FROM story WHERE series_key = ? AND volume IS NULL", (series_key,)
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT * FROM story WHERE series_key = ? AND volume = ?", (series_key, volume)
            ).fetchone()
        return _row_to_story(row) if row else None

    def update(self, story: Story) -> None:
        self.conn.execute(
            """
            UPDATE story SET
                series_key = ?, title = ?, author = ?, volume = ?, tracked = ?,
                last_read_part = ?, last_read_offset = ?, exported_markdown_path = ?,
                exported_at = ?, last_updated_at = ?
            WHERE id = ?
            """,
            (
                story.series_key,
                story.title,
                story.author,
                story.volume,
                int(story.tracked),
                story.last_read_part,
                story.last_read_offset,
                story.exported_markdown_path,
                story.exported_at.isoformat() if story.exported_at else None,
                story.last_updated_at.isoformat() if story.last_updated_at else None,
                story.id,
            ),
        )
        self.conn.commit()

    def delete(self, story_id: int) -> None:
        self.conn.execute("DELETE FROM story WHERE id = ?", (story_id,))
        self.conn.commit()

    def add_part(self, part: StoryPart) -> None:
        self.conn.execute(
            """
            INSERT INTO story_part
                (post_id, story_id, part_number, part_label, segment, segment_count,
                 sort_key, alternate_post_ids, newly_filled, match_confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (story_id, post_id) DO UPDATE SET
                part_number = excluded.part_number,
                part_label = excluded.part_label,
                segment = excluded.segment,
                segment_count = excluded.segment_count,
                sort_key = excluded.sort_key,
                alternate_post_ids = excluded.alternate_post_ids,
                match_confidence = excluded.match_confidence
            """,
            (
                part.post_id,
                part.story_id,
                str(part.part_number) if part.part_number is not None else None,
                part.part_label,
                part.segment,
                part.segment_count,
                part.sort_key,
                ",".join(part.alternate_post_ids),
                int(part.newly_filled),
                part.match_confidence,
            ),
        )
        self.conn.commit()

    def parts(self, story_id: int) -> list[StoryPart]:
        rows = self.conn.execute(
            "SELECT * FROM story_part WHERE story_id = ?", (story_id,)
        ).fetchall()
        return [_row_to_part(row) for row in rows]

    def part_post_ids(self, story_id: int) -> list[str]:
        rows = self.conn.execute(
            "SELECT post_id FROM story_part WHERE story_id = ?", (story_id,)
        ).fetchall()
        return [row["post_id"] for row in rows]

    def clear_newly_filled(self, story_id: int, post_id: str) -> None:
        self.conn.execute(
            "UPDATE story_part SET newly_filled = 0 WHERE story_id = ? AND post_id = ?",
            (story_id, post_id),
        )
        self.conn.commit()

    def add_unavailable(self, rec: UnavailablePart) -> None:
        self.conn.execute(
            """
            INSERT INTO unavailable_part (story_id, part_number, auto_marked)
            VALUES (?, ?, ?)
            ON CONFLICT (story_id, part_number) DO UPDATE SET auto_marked = excluded.auto_marked
            """,
            (rec.story_id, str(rec.part_number), int(rec.auto_marked)),
        )
        self.conn.commit()

    def unavailable(self, story_id: int) -> list[UnavailablePart]:
        rows = self.conn.execute(
            "SELECT * FROM unavailable_part WHERE story_id = ?", (story_id,)
        ).fetchall()
        return [
            UnavailablePart(
                story_id=row["story_id"],
                part_number=Decimal(row["part_number"]),
                auto_marked=bool(row["auto_marked"]),
            )
            for row in rows
        ]

    def clear_unavailable(self, story_id: int, part_number: Decimal) -> None:
        self.conn.execute(
            "DELETE FROM unavailable_part WHERE story_id = ? AND part_number = ?",
            (story_id, str(part_number)),
        )
        self.conn.commit()

    def add_cleaning_rule(self, rule: CleaningRule) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO cleaning_rule (story_id, position, block, seen_in_parts, approved)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                rule.story_id,
                rule.position.value,
                rule.block,
                rule.seen_in_parts,
                None if rule.approved is None else int(rule.approved),
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid or 0)

    def cleaning_rules(self, story_id: int) -> list[CleaningRule]:
        rows = self.conn.execute(
            "SELECT * FROM cleaning_rule WHERE story_id = ?", (story_id,)
        ).fetchall()
        return [
            CleaningRule(
                story_id=row["story_id"],
                position=CleaningPosition(row["position"]),
                block=row["block"],
                seen_in_parts=row["seen_in_parts"],
                approved=None if row["approved"] is None else bool(row["approved"]),
            )
            for row in rows
        ]

    def set_rule_decision(self, rule_id: int, approved: bool) -> None:
        self.conn.execute(
            "UPDATE cleaning_rule SET approved = ? WHERE id = ?", (int(approved), rule_id)
        )
        self.conn.commit()
