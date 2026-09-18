"""Browse — a merged listing across every configured subreddit."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from reddit_reader.dedupe import collapse_duplicates
from reddit_reader.models import PostMeta
from reddit_reader.reddit_client import RedditError
from reddit_reader.service import FetchResult, ReaderService
from reddit_reader.tui.navigation import open_post
from reddit_reader.tui.screens import PAGING_KEYS, TITLE_COLUMN_WIDTH

LISTINGS = ("new", "hot", "top")

# "none" keeps the natural fetch/grouping order (orphans first, then grouped
# posts); the rest sort by that column of the visible row tuple, see
# `_ROW_SORT_COLUMNS`.
SORT_KEYS = ("none", "author", "subreddit", "title", "date")

# Index into the (author, subreddit, title, grouped?, tagged?, date) row tuple
# for each sort key that isn't "none". Dates are stored ISO-formatted, so
# lexicographic order (what `_sorted_entries` does for every column) is
# already chronological order.
_ROW_SORT_COLUMNS = {"author": 0, "subreddit": 1, "title": 2, "date": 5}

logger = logging.getLogger(__name__)


class BrowseScreen(Screen[None]):
    """Fetch and inspect raw posts before they become stories."""

    PAGING_KEYS = PAGING_KEYS

    BINDINGS: ClassVar[list[BindingType]] = [
        ("f", "fetch", "Fetch"),
        ("l", "cycle_listing", "Listing type"),
        ("o", "open_selected", "Open"),
        ("p", "preview", "Preview"),
        ("s", "cycle_sort", "Sort"),
        ("S", "reverse_sort", "Reverse sort"),
        ("t", "toggle_tag", "Tag"),
        ("c", "commit_tagged", "Group tagged"),
        ("space", "page_down", "Page down"),
        ("b", "page_up", "Page up"),
        ("g", "scroll_top", "Top"),
        ("G", "scroll_bottom", "Bottom"),
        ("escape", "app.back", "Back"),
    ]

    def __init__(self, service: ReaderService) -> None:
        super().__init__()
        self.service = service
        self._subreddit_filter: str | None = None
        self._last_result: FetchResult | None = None
        self._sort: str = "date"
        self._sort_reverse = True
        # An insertion-ordered set: tag order becomes the anchor-selection
        # order in `ReaderService.tag_group` when none of the tagged posts
        # already belongs to a story, so plain `set` (arbitrary order) would
        # make which post's title/author wins the new story nondeterministic.
        self._tagged: dict[str, None] = {}

    # ---- data -------------------------------------------------------------------

    def set_listing(self, listing: str) -> None:
        if listing in LISTINGS:
            self.service.settings.listing = listing  # type: ignore[assignment]

    def set_subreddit_filter(self, subreddit: str | None) -> None:
        self._subreddit_filter = subreddit

    def set_sort(self, key: str, *, reverse: bool = False) -> None:
        if key in SORT_KEYS:
            self._sort = key
            self._sort_reverse = reverse

    def do_fetch(self) -> FetchResult:
        self._last_result = self.service.fetch()
        return self._last_result

    def _duplicate_ids(self, metas: Iterable[PostMeta]) -> set[str]:
        """Non-canonical ids `collapse_duplicates` folds into another post, per author.

        These are exactly the ids `open_post` (navigation.py) can never act
        on directly — only a match's canonical post ever appears in a
        `DetectionMatch.post_ids` — so Enter/`o` on one is a silent no-op.
        Rather than leave that trap in the listing, Browse hides them.
        """
        duplicate_ids: set[str] = set()
        for author in {meta.author for meta in metas}:
            groups = collapse_duplicates(
                self.service.posts.by_author(author),
                self.service.settings.subreddits,
                window_hours=self.service.settings.dedupe_window_hours,
            )
            duplicate_ids.update(alt.id for group in groups for alt in group.alternates)
        return duplicate_ids

    def _visible_entries(self) -> list[tuple[str, tuple[str, str, str, str, str, str]]]:
        """(post_id, (author, subreddit, title, grouped?, tagged?, date)) for every cached post."""
        grouped = {
            post_id
            for story in self.service.stories.all_stories()
            for post_id in self.service.stories.part_post_ids(story.id)
        }
        orphan_ids = self.service.posts.orphaned_ids()
        orphan_metas = {
            post_id: meta
            for post_id in orphan_ids
            if (meta := self.service.posts.get_meta(post_id)) is not None
        }
        duplicate_ids = self._duplicate_ids(orphan_metas.values())

        entries: list[tuple[str, tuple[str, str, str, str, str, str]]] = []
        for post_id in orphan_ids + sorted(grouped):
            if post_id in duplicate_ids and post_id not in grouped:
                continue
            meta = orphan_metas.get(post_id) or self.service.posts.get_meta(post_id)
            if meta is None:
                continue
            if self._subreddit_filter and meta.subreddit.lower() != self._subreddit_filter.lower():
                continue
            entries.append(
                (
                    meta.id,
                    (
                        meta.author,
                        meta.subreddit,
                        meta.title,
                        "yes" if meta.id in grouped else "no",
                        "yes" if meta.id in self._tagged else "no",
                        meta.created_utc.date().isoformat(),
                    ),
                )
            )
        return self._sorted_entries(entries)

    def _sorted_entries(
        self, entries: list[tuple[str, tuple[str, str, str, str, str, str]]]
    ) -> list[tuple[str, tuple[str, str, str, str, str, str]]]:
        if self._sort == "none":
            return entries
        column = _ROW_SORT_COLUMNS[self._sort]
        return sorted(
            entries, key=lambda entry: entry[1][column].lower(), reverse=self._sort_reverse
        )

    def rows(self) -> list[tuple[str, str, str, str, str, str]]:
        """(author, subreddit, title, grouped?, tagged?, date) for every cached post."""
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
        table.add_column("Author")
        table.add_column("Subreddit")
        # Capped so a runaway-long title can't push Author/Subreddit off screen.
        table.add_column("Title", width=TITLE_COLUMN_WIDTH)
        table.add_column("Grouped")
        table.add_column("Tagged")
        table.add_column("Date")
        self.refresh_rows()

    def refresh_rows(self) -> None:
        table = self.query_one("#posts", DataTable)
        # Rebuilding the table resets the cursor to row 0, which would make
        # tagging several rows in a row (select, `t`, select next, `t`, ...)
        # unusable — every tag would bounce the cursor back to the top.
        # Re-find the previously highlighted post afterwards instead.
        previous = self._selected_post_id() if table.row_count else None
        table.clear()
        entries = self._visible_entries()
        for post_id, row in entries:
            table.add_row(*row, key=post_id)
        if previous is not None:
            for index, (post_id, _) in enumerate(entries):
                if post_id == previous:
                    table.move_cursor(row=index)
                    break
        self._set_status(
            f"listing: {self.service.settings.listing} — {len(entries)} posts cached"
            f" — sort: {self._sort_label()} — tagged: {len(self._tagged)}"
        )

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def _sort_label(self) -> str:
        if self._sort == "none":
            return "none"
        arrow = "↓" if self._sort_reverse else "↑"
        return f"{self._sort} {arrow}"

    def action_fetch(self) -> None:
        try:
            result = self.do_fetch()
        except RedditError as exc:
            logger.warning("fetch failed: %s", exc)
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

    def action_cycle_sort(self) -> None:
        current = SORT_KEYS.index(self._sort)
        self._sort = SORT_KEYS[(current + 1) % len(SORT_KEYS)]
        self.refresh_rows()

    def action_reverse_sort(self) -> None:
        self._sort_reverse = not self._sort_reverse
        self.refresh_rows()

    def action_page_down(self) -> None:
        self.query_one("#posts", DataTable).action_page_down()

    def action_page_up(self) -> None:
        self.query_one("#posts", DataTable).action_page_up()

    def action_scroll_top(self) -> None:
        self.query_one("#posts", DataTable).action_scroll_top()

    def action_scroll_bottom(self) -> None:
        self.query_one("#posts", DataTable).action_scroll_bottom()

    def action_toggle_tag(self) -> None:
        post_id = self._selected_post_id()
        if post_id is None:
            return
        if post_id in self._tagged:
            del self._tagged[post_id]
        else:
            self._tagged[post_id] = None
        self.refresh_rows()

    def action_commit_tagged(self) -> None:
        if len(self._tagged) < 2:
            self._set_status("Tag at least two posts before grouping.")
            return
        try:
            story_id = self.service.tag_group(list(self._tagged))
        except ValueError as exc:
            self._set_status(str(exc))
            return
        self._tagged.clear()
        self.refresh_rows()
        self._set_status(f"Tagged posts grouped into story {story_id}.")

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

    def action_preview(self) -> None:
        post_id = self._selected_post_id()
        if post_id is None:
            return
        from reddit_reader.tui.screens.preview import PreviewScreen

        self.app.push_screen(PreviewScreen(self.service, post_id))
