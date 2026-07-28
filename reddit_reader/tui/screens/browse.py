"""Browse — a merged listing across every configured subreddit."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from reddit_reader.reddit_client import RedditError
from reddit_reader.service import FetchResult, ReaderService
from reddit_reader.tui.navigation import open_post

LISTINGS = ("new", "hot", "top")


class BrowseScreen(Screen[None]):
    """Fetch and inspect raw posts before they become stories."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("f", "fetch", "Fetch"),
        ("l", "cycle_listing", "Listing type"),
        ("o", "open_selected", "Open"),
        ("escape", "app.back", "Back"),
    ]

    def __init__(self, service: ReaderService) -> None:
        super().__init__()
        self.service = service
        self._subreddit_filter: str | None = None
        self._last_result: FetchResult | None = None

    # ---- data -------------------------------------------------------------------

    def set_listing(self, listing: str) -> None:
        if listing in LISTINGS:
            self.service.settings.listing = listing  # type: ignore[assignment]

    def set_subreddit_filter(self, subreddit: str | None) -> None:
        self._subreddit_filter = subreddit

    def do_fetch(self) -> FetchResult:
        self._last_result = self.service.fetch()
        return self._last_result

    def _visible_entries(self) -> list[tuple[str, tuple[str, str, str, str]]]:
        """(post_id, (title, subreddit, author, grouped?)) for every cached post."""
        grouped = {
            post_id
            for story in self.service.stories.all_stories()
            for post_id in self.service.stories.part_post_ids(story.id)
        }
        entries: list[tuple[str, tuple[str, str, str, str]]] = []
        for post_id in self.service.posts.orphaned_ids() + sorted(grouped):
            meta = self.service.posts.get_meta(post_id)
            if meta is None:
                continue
            if self._subreddit_filter and meta.subreddit.lower() != self._subreddit_filter.lower():
                continue
            entries.append(
                (
                    meta.id,
                    (meta.title, meta.subreddit, meta.author, "yes" if meta.id in grouped else "no"),
                )
            )
        return entries

    def rows(self) -> list[tuple[str, str, str, str]]:
        """(title, subreddit, author, grouped?) for every cached post."""
        return [row for _, row in self._visible_entries()]

    def _selected_post_id(self) -> str | None:
        table = self.query_one("#posts", DataTable)
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        return str(row_key.value) if row_key.value else None

    # ---- rendering --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="posts")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#posts", DataTable)
        table.cursor_type = "row"
        table.add_columns("Title", "Subreddit", "Author", "Grouped")
        self.refresh_rows()

    def refresh_rows(self) -> None:
        table = self.query_one("#posts", DataTable)
        table.clear()
        entries = self._visible_entries()
        for post_id, row in entries:
            table.add_row(*row, key=post_id)
        self.query_one("#status", Static).update(
            f"listing: {self.service.settings.listing} — {len(entries)} posts cached"
        )

    def action_fetch(self) -> None:
        try:
            result = self.do_fetch()
        except RedditError as exc:
            self.query_one("#status", Static).update(f"Fetch failed: {exc}")
            return
        self.refresh_rows()
        self.query_one("#status", Static).update(
            f"Fetched {result.fetched}, auto-attached {result.auto_attached}, "
            f"{len(result.candidates)} candidates."
        )
        if result.candidates:
            from reddit_reader.tui.screens.curation import CurationScreen

            self.app.push_screen(CurationScreen(self.service, result.candidates))

    def action_cycle_listing(self) -> None:
        current = LISTINGS.index(self.service.settings.listing)
        self.set_listing(LISTINGS[(current + 1) % len(LISTINGS)])
        self.refresh_rows()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        post_id = self._selected_post_id()
        if post_id is not None:
            open_post(self, self.service, post_id)

    def action_open_selected(self) -> None:
        """Explicit fallback for `o`, independent of DataTable's Enter-triggered
        `RowSelected` message (see the identical binding on `SearchScreen`)."""
        post_id = self._selected_post_id()
        if post_id is not None:
            open_post(self, self.service, post_id)
