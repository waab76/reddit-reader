"""Browse — a merged listing across every configured subreddit."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from reddit_reader.service import FetchResult, ReaderService

LISTINGS = ("new", "hot", "top")


class BrowseScreen(Screen[None]):
    """Fetch and inspect raw posts before they become stories."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("f", "fetch", "Fetch"),
        ("l", "cycle_listing", "Listing type"),
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

    def rows(self) -> list[tuple[str, str, str, str]]:
        """(title, subreddit, author, grouped?) for every cached post."""
        grouped = {
            post_id
            for story in self.service.stories.all_stories()
            for post_id in self.service.stories.part_post_ids(story.id)
        }
        rows: list[tuple[str, str, str, str]] = []
        for post_id in self.service.posts.orphaned_ids() + sorted(grouped):
            meta = self.service.posts.get_meta(post_id)
            if meta is None:
                continue
            if self._subreddit_filter and meta.subreddit.lower() != self._subreddit_filter.lower():
                continue
            rows.append(
                (meta.title, meta.subreddit, meta.author, "yes" if meta.id in grouped else "no")
            )
        return rows

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
        for row in self.rows():
            table.add_row(*row)
        self.query_one("#status", Static).update(
            f"listing: {self.service.settings.listing} — {len(self.rows())} posts cached"
        )

    def action_fetch(self) -> None:
        result = self.do_fetch()
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
