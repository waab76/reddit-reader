"""Story List — every committed story, tracked or not."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from reddit_reader.models import Story
from reddit_reader.ordering import format_part_number
from reddit_reader.service import ReaderService

SORT_KEYS = ("series", "score", "parts", "recent")

# Cap how many gap numbers get joined into the "Gaps" table cell — a story with
# a title-parsing hiccup can otherwise render dozens of comma-separated numbers
# into one cell.
GAP_DISPLAY_LIMIT = 10


def format_gap_cell(gaps: Sequence[Decimal]) -> str:
    """The "Gaps" table cell text: truncated, and never scientific notation."""
    if not gaps:
        return "-"
    shown = gaps[:GAP_DISPLAY_LIMIT]
    text = ", ".join(format_part_number(g) for g in shown)
    if len(gaps) > GAP_DISPLAY_LIMIT:
        text += f", +{len(gaps) - GAP_DISPLAY_LIMIT} more"
    return text


class StoryListScreen(Screen[None]):
    """Home screen. Untracked stories appear here so they have a route to detail."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("enter", "open", "Open"),
        ("s", "cycle_sort", "Sort"),
        ("t", "toggle_tracked_filter", "Tracked filter"),
        ("b", "browse", "Browse"),
        ("/", "search", "Search"),
        ("g", "storage", "Storage"),
    ]

    def __init__(self, service: ReaderService) -> None:
        super().__init__()
        self.service = service
        self._sort = "series"
        self._filters: dict[str, str | None] = {
            "tracked": None,
            "read": None,
            "status": None,
        }

    # ---- data -------------------------------------------------------------------

    def set_sort(self, key: str) -> None:
        if key in SORT_KEYS:
            self._sort = key

    def set_filter(self, name: str, value: str | None) -> None:
        self._filters[name] = value

    def _passes_filters(self, story: Story) -> bool:
        tracked = self._filters["tracked"]
        if tracked == "tracked" and not story.tracked:
            return False
        if tracked == "untracked" and story.tracked:
            return False

        read = self._filters["read"]
        if read is not None:
            unread = self.service.unread_count(story.id)
            total = len(self.service.stories.parts(story.id))
            # "Finished" means every known part has been passed and the last one
            # read to completion. A story can sit on its final part with a
            # partial offset (unread == 0 but not yet done) and still count as
            # in-progress rather than finished.
            finished = unread == 0 and story.last_read_offset >= 1.0
            if read == "unstarted" and story.last_read_part is not None:
                return False
            if read == "in_progress" and (story.last_read_part is None or finished):
                return False
            if read == "has_unread" and (unread == 0 or unread == total):
                return False

        status = self._filters["status"]
        return status is None or self.service.story_status(story).value == status

    def _sort_value(self, story: Story) -> tuple[object, ...]:
        metas = self.service.posts.get_many(self.service.stories.part_post_ids(story.id))
        if self._sort == "score":
            return (-max((m.score for m in metas), default=0),)
        if self._sort == "parts":
            return (-len(self.service.stories.parts(story.id)),)
        if self._sort == "recent":
            newest = max((m.created_utc for m in metas), default=None)
            return (0 if newest is None else -newest.timestamp(),)
        return (story.series_key, story.volume or 0)

    def visible_stories(self) -> list[Story]:
        stories = [s for s in self.service.stories.all_stories() if self._passes_filters(s)]
        return sorted(stories, key=self._sort_value)

    # ---- rendering --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="stories")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#stories", DataTable)
        table.cursor_type = "row"
        table.add_columns("Title", "Author", "Parts", "Status", "Tracked", "Unread", "Gaps", "New")
        self.refresh_rows()

    def refresh_rows(self) -> None:
        table = self.query_one("#stories", DataTable)
        table.clear()
        visible = self.visible_stories()
        for story in visible:
            parts = len(self.service.stories.parts(story.id))
            gaps = self.service.gaps(story.id)
            filled = self.service.newly_filled(story.id)
            volume = f" (vol {story.volume})" if story.volume is not None else ""
            table.add_row(
                f"{story.title}{volume}",
                story.author,
                str(parts),
                self.service.story_status(story).value,
                "yes" if story.tracked else "no",
                str(self.service.unread_count(story.id)),
                format_gap_cell(gaps),
                str(len(filled)) if filled else "-",
                key=str(story.id),
            )
        self._set_status(f"{len(visible)} stories — sort: {self._sort}")

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    # ---- actions ----------------------------------------------------------------

    def _selected_story_id(self) -> int | None:
        table = self.query_one("#stories", DataTable)
        if table.row_count == 0:
            return None
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        return int(row_key.value) if row_key.value else None

    def action_cycle_sort(self) -> None:
        current = SORT_KEYS.index(self._sort)
        self._sort = SORT_KEYS[(current + 1) % len(SORT_KEYS)]
        self.refresh_rows()

    def action_toggle_tracked_filter(self) -> None:
        cycle = {None: "tracked", "tracked": "untracked", "untracked": None}
        self._filters["tracked"] = cycle[self._filters["tracked"]]
        self.refresh_rows()

    def action_open(self) -> None:
        from reddit_reader.tui.screens.story_detail import StoryDetailScreen

        story_id = self._selected_story_id()
        if story_id is not None:
            self.app.push_screen(StoryDetailScreen(self.service, story_id))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """`DataTable` consumes Enter itself (bound to `select_cursor`) before the
        screen-level `Binding("enter", "open", ...)` ever fires, so the screen
        binding alone is dead on a focused table. This message handler is what
        actually makes Enter open the selected story."""
        self.action_open()

    def action_browse(self) -> None:
        from reddit_reader.tui.screens.browse import BrowseScreen

        self.app.push_screen(BrowseScreen(self.service))

    def action_search(self) -> None:
        from reddit_reader.tui.screens.search import SearchScreen

        self.app.push_screen(SearchScreen(self.service))

    def action_storage(self) -> None:
        from reddit_reader.tui.screens.storage_admin import StorageAdminScreen

        self.app.push_screen(StorageAdminScreen(self.service))
