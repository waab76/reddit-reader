"""Storage management — usage, untracking, deletion, and pruning."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from reddit_reader.service import ReaderService


def _mb(value: int) -> str:
    return f"{value / 1_048_576:.2f} MB"


class StorageAdminScreen(Screen[None]):
    """What the cache is costing, and how to reclaim it."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("p", "prune", "Prune orphans"),
        ("u", "untrack", "Untrack story"),
        ("d", "delete", "Delete story"),
        ("escape", "app.back", "Back"),
    ]

    def __init__(self, service: ReaderService) -> None:
        super().__init__()
        self.service = service
        self._confirming: int | None = None

    # ---- data -------------------------------------------------------------------

    def usage_lines(self) -> list[str]:
        usage = self.service.storage_usage()
        return [
            f"Database total: {_mb(usage.total_bytes)}",
            f"Cached bodies: {_mb(usage.body_bytes)} across {usage.body_count} posts",
            f"Post metadata: {usage.post_count} posts",
        ]

    def do_prune(self) -> int:
        return self.service.prune_orphans()

    def do_delete(self, story_id: int) -> None:
        self.service.delete_story(story_id)

    def do_untrack(self, story_id: int) -> int:
        return self.service.untrack(story_id)

    # ---- rendering --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="usage")
        yield DataTable(id="stories")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#stories", DataTable)
        table.cursor_type = "row"
        table.add_columns("Story", "Author", "Parts", "Tracked")
        self.refresh_view()

    def refresh_view(self) -> None:
        self.query_one("#usage", Static).update("\n".join(self.usage_lines()))
        table = self.query_one("#stories", DataTable)
        table.clear()
        for story in self.service.stories.all_stories():
            table.add_row(
                story.title,
                story.author,
                str(len(self.service.stories.parts(story.id))),
                "yes" if story.tracked else "no",
                key=str(story.id),
            )

    def _selected_story_id(self) -> int | None:
        table = self.query_one("#stories", DataTable)
        if table.row_count == 0:
            return None
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        return int(row_key.value) if row_key.value else None

    def _status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def action_prune(self) -> None:
        removed = self.do_prune()
        self.refresh_view()
        self._status(f"Pruned {removed} orphaned posts.")

    def action_untrack(self) -> None:
        story_id = self._selected_story_id()
        if story_id is None:
            return
        dropped = self.do_untrack(story_id)
        self.refresh_view()
        self._status(f"Untracked story {story_id}; dropped {dropped} cached bodies.")

    def action_delete(self) -> None:
        story_id = self._selected_story_id()
        if story_id is None:
            return
        if self._confirming != story_id:
            self._confirming = story_id
            self._status(f"Press 'd' again to delete story {story_id}. Post metadata is kept.")
            return
        self.do_delete(story_id)
        self._confirming = None
        self.refresh_view()
        self._status(f"Deleted story {story_id}.")
