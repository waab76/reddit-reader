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


class SearchScreen(Screen[None]):
    """Keyword search over cached posts, escalating to Reddit on request."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("enter", "search_local", "Search cache"),
        ("ctrl+r", "search_live", "Search Reddit"),
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
        for story in self.service.stories.all_stories():
            if post_id in self.service.stories.part_post_ids(story.id):
                from reddit_reader.tui.screens.story_detail import StoryDetailScreen

                self.app.push_screen(StoryDetailScreen(self.service, story.id))
                return

        meta = self.service.posts.get_meta(post_id)
        if meta is None:
            return

        from reddit_reader.detection import group_posts
        from reddit_reader.tui.screens.curation import CurationScreen

        author_posts = self.service.posts.by_author(meta.author)
        candidates = [
            match
            for match in group_posts(author_posts, self.service.settings.subreddits)
            if post_id in match.post_ids
        ]
        if candidates:
            self.app.push_screen(CurationScreen(self.service, candidates))

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
