"""Curation — review candidate series before they become stories."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from reddit_reader.models import DetectionMatch
from reddit_reader.service import ReaderService


class CurationScreen(Screen[None]):
    """Accept, merge, split, or drop detected candidates."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("a", "accept", "Accept"),
        ("d", "drop", "Drop"),
        ("m", "mark_merge", "Mark/merge"),
        ("escape", "app.back", "Back"),
    ]

    def __init__(self, service: ReaderService, candidates: list[DetectionMatch]) -> None:
        super().__init__()
        self.service = service
        self.candidates = list(candidates)
        self._merge_anchor: int | None = None

    # ---- operations -------------------------------------------------------------

    def accept(self, index: int) -> int:
        """Commit a candidate, attaching to its existing story when it has one."""
        match = self.candidates[index]
        if match.existing_story_id is not None:
            story_id = match.existing_story_id
            self.service.attach_parts(story_id, match)
        else:
            story_id = self.service.commit_match(match)
        self.candidates.pop(index)
        return story_id

    def drop(self, index: int) -> None:
        self.candidates.pop(index)

    def merge(self, a: int, b: int) -> None:
        """Fold candidate `b` into candidate `a`."""
        first, second = self.candidates[a], self.candidates[b]
        combined = list(dict.fromkeys([*first.post_ids, *second.post_ids]))
        first.post_ids = combined
        first.confidence = min(first.confidence, second.confidence)
        first.reasons = [*first.reasons, "merged by hand"]
        self.candidates.pop(b)

    def split(self, index: int, post_ids: list[str]) -> None:
        """Move `post_ids` out of a candidate into a new one."""
        source = self.candidates[index]
        moved = [pid for pid in post_ids if pid in source.post_ids]
        if not moved:
            return
        source.post_ids = [pid for pid in source.post_ids if pid not in moved]
        self.candidates.append(
            DetectionMatch(
                base_title=source.base_title,
                author=source.author,
                volume=source.volume,
                post_ids=moved,
                confidence=source.confidence,
                reasons=["split by hand"],
            )
        )

    # ---- rendering --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="candidates")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#candidates", DataTable)
        table.cursor_type = "row"
        table.add_columns("Title", "Author", "Volume", "Parts", "Confidence", "Existing")
        self.refresh_rows()

    def refresh_rows(self) -> None:
        table = self.query_one("#candidates", DataTable)
        table.clear()
        for match in self.candidates:
            table.add_row(
                match.base_title,
                match.author,
                str(match.volume) if match.volume is not None else "-",
                str(len(match.post_ids)),
                f"{match.confidence:.2f}",
                str(match.existing_story_id) if match.existing_story_id else "-",
            )
        self.query_one("#status", Static).update(f"{len(self.candidates)} candidates")

    def _cursor(self) -> int:
        return self.query_one("#candidates", DataTable).cursor_row

    def action_accept(self) -> None:
        if self.candidates:
            self.accept(self._cursor())
            self.refresh_rows()

    def action_drop(self) -> None:
        if self.candidates:
            self.drop(self._cursor())
            self.refresh_rows()

    def action_mark_merge(self) -> None:
        current = self._cursor()
        if self._merge_anchor is None:
            self._merge_anchor = current
            self.query_one("#status", Static).update("Merge anchor set — pick the second.")
            return
        if self._merge_anchor != current:
            self.merge(self._merge_anchor, current)
        self._merge_anchor = None
        self.refresh_rows()
