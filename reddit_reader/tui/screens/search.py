"""Search — local cache first, with an explicit live Reddit search."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Static

from reddit_reader.models import PostMeta
from reddit_reader.reddit_client import RedditError
from reddit_reader.service import ReaderService
from reddit_reader.tui.navigation import open_post


class SearchScreen(Screen[None]):
    """Keyword search over cached posts, escalating to Reddit on request."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("enter", "search_local", "Search cache"),
        ("ctrl+r", "search_live", "Search Reddit"),
        ("o", "open_selected", "Open"),
        ("escape", "app.back", "Back"),
    ]

    def __init__(self, service: ReaderService) -> None:
        super().__init__()
        self.service = service
        self.results: list[PostMeta] = []

    # ---- data -------------------------------------------------------------------

    def do_local_search(self, query: str) -> list[PostMeta]:
        self.results = self.service.search_local(query)
        return self.results

    def do_live_search(self, query: str, subreddit: str | None = None) -> list[PostMeta]:
        self.results = self.service.search_live(query, subreddit)
        return self.results

    def open_for_post(self, post_id: str) -> None:
        """Jump to the story containing this post, or curate its detected series."""
        open_post(self, self.service, post_id)

    # ---- rendering --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Search titles (and bodies of tracked stories)…", id="query")
        yield DataTable(id="results")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results", DataTable)
        table.cursor_type = "row"
        table.add_columns("Title", "Subreddit", "Author")

    def _query(self) -> str:
        return self.query_one("#query", Input).value

    def _selected_post_id(self) -> str | None:
        table = self.query_one("#results", DataTable)
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        return str(row_key.value) if row_key.value else None

    def refresh_rows(self) -> None:
        table = self.query_one("#results", DataTable)
        table.clear()
        for meta in self.results:
            table.add_row(meta.title, meta.subreddit, meta.author, key=meta.id)
        self.query_one("#status", Static).update(f"{len(self.results)} results")

    def action_search_local(self) -> None:
        self.do_local_search(self._query())
        self.refresh_rows()

    def action_search_live(self) -> None:
        try:
            self.do_live_search(self._query())
        except RedditError as exc:
            self.query_one("#status", Static).update(f"Live search failed: {exc}")
            return
        self.refresh_rows()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """`Input` consumes Enter itself (bound to `submit`) before the
        screen-level `Binding("enter", "search_local", ...)` ever fires, so the
        screen binding alone is dead while the query field is focused. This
        message handler is what actually runs the search on Enter."""
        self.action_search_local()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """`DataTable` consumes Enter itself (bound to `select_cursor`) before the
        screen-level `Binding("enter", "search_local", ...)` ever fires, so
        selecting a result row was previously dead. This message handler is what
        actually turns Enter-on-a-row into `open_for_post`."""
        post_id = self._selected_post_id()
        if post_id is not None:
            self.open_for_post(post_id)

    def action_open_selected(self) -> None:
        """Explicit fallback for `o`: some terminals never deliver a DataTable's
        Enter-triggered `RowSelected` message (observed over SSH on at least one
        Linux setup), leaving row selection unreachable. This binding opens the
        highlighted row directly, independent of that message."""
        post_id = self._selected_post_id()
        if post_id is not None:
            self.open_for_post(post_id)
