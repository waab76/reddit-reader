"""Preview — a quick look at one post's body, before it's curated into a story."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Markdown, Static

from reddit_reader.reddit_client import RedditError
from reddit_reader.service import ReaderService
from reddit_reader.tui.markdown import to_display_markdown
from reddit_reader.tui.screens import PAGING_KEYS


class PreviewScreen(Screen[None]):
    """Fetches (and caches) one post's body on demand, read-only."""

    PAGING_KEYS = PAGING_KEYS

    BINDINGS: ClassVar[list[BindingType]] = [
        ("s", "toggle_spoilers", "Toggle spoilers"),
        ("space", "page_down", "Page down"),
        ("b", "page_up", "Page up"),
        ("g", "scroll_top", "Top"),
        ("G", "scroll_bottom", "Bottom"),
        ("escape", "app.back", "Back"),
    ]

    def __init__(self, service: ReaderService, post_id: str) -> None:
        super().__init__()
        self.service = service
        self.post_id = post_id
        self.reveal_spoilers = False

    # ---- content --------------------------------------------------------------

    def heading(self) -> str:
        meta = self.service.posts.get_meta(self.post_id)
        if meta is None:
            return self.post_id
        return f"{meta.title} — u/{meta.author} (r/{meta.subreddit})"

    def rendered_text(self) -> str:
        """Cleaned, spoiler-masked body text, fetching and caching it if needed."""
        try:
            body = self.service.preview_body(self.post_id)
        except RedditError as exc:
            return f"*Preview failed: {exc}*"

        if body is None:
            return "*No body available for this post.*"
        return to_display_markdown(body.selftext, reveal_spoilers=self.reveal_spoilers)

    # ---- rendering ----------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="heading")
        with VerticalScroll(id="body-scroll"):
            yield Markdown("", id="body")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_view()

    def refresh_view(self) -> None:
        self.query_one("#heading", Static).update(self.heading())
        self.query_one("#body", Markdown).update(self.rendered_text())

    # ---- actions --------------------------------------------------------------

    def action_toggle_spoilers(self) -> None:
        self.reveal_spoilers = not self.reveal_spoilers
        self.refresh_view()

    def action_page_down(self) -> None:
        self.query_one("#body-scroll", VerticalScroll).scroll_page_down()

    def action_page_up(self) -> None:
        self.query_one("#body-scroll", VerticalScroll).scroll_page_up()

    def action_scroll_top(self) -> None:
        self.query_one("#body-scroll", VerticalScroll).scroll_home()

    def action_scroll_bottom(self) -> None:
        self.query_one("#body-scroll", VerticalScroll).scroll_end()
