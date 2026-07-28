"""Reader — renders one part at a time and remembers where you stopped."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Markdown, Static

from reddit_reader.cleaning import clean
from reddit_reader.ordering import format_part_number
from reddit_reader.service import ReaderService
from reddit_reader.tui.markdown import to_display_markdown


class ReaderScreen(Screen[None]):
    """One part at a time, resuming from the saved position."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("n", "next", "Next part"),
        ("p", "previous", "Previous part"),
        ("s", "toggle_spoilers", "Toggle spoilers"),
        ("space", "page_down", "Page down"),
        ("b", "page_up", "Page up"),
        ("g", "scroll_top", "Top"),
        ("G", "scroll_bottom", "Bottom"),
        ("escape", "app.back", "Back"),
    ]

    def __init__(self, service: ReaderService, story_id: int) -> None:
        super().__init__()
        self.service = service
        self.story_id = story_id
        self.groups = service.ordered_groups(story_id)
        self.reveal_spoilers = False
        self.part_index = self._starting_index()
        self._scroll_restored = False

    def _starting_index(self) -> int:
        story = self.service.stories.get(self.story_id)
        if story is None or story.last_read_part is None:
            return 0
        for index, group in enumerate(self.groups):
            if any(part.post.id == story.last_read_part for part in group):
                return index
        return 0

    # ---- content ----------------------------------------------------------------

    def heading(self) -> str:
        group = self.groups[self.part_index]
        lead = group[0]
        if lead.parsed.part_number is not None:
            return f"Part {format_part_number(lead.parsed.part_number)}"
        if lead.parsed.part_label:
            return lead.parsed.part_label
        return lead.post.title

    def rendered_text(self) -> str:
        """Cleaned, spoiler-masked text for the current part (all its segments)."""
        rules = self.service.stories.cleaning_rules(self.story_id)
        chunks: list[str] = []

        for part in self.groups[self.part_index]:
            body = self.service.posts.get_body(part.post.id)
            if body is None:
                continue
            cleaned = clean(
                body.selftext,
                rules,
                strip_known_patterns=self.service.settings.cleaning_enabled,
            )
            chunks.append(to_display_markdown(cleaned, reveal_spoilers=self.reveal_spoilers))

        return "\n\n".join(chunks)

    # ---- navigation -------------------------------------------------------------

    def _current_post_id(self) -> str:
        return self.groups[self.part_index][0].post.id

    def save_position(self, offset: float) -> None:
        self.service.mark_read(self.story_id, self._current_post_id(), offset)

    def jump_to(self, index: int) -> None:
        if 0 <= index < len(self.groups):
            self.part_index = index
            self.save_position(0.0)

    def next_part(self) -> bool:
        if self.part_index + 1 >= len(self.groups):
            return False
        self.part_index += 1
        self.save_position(0.0)
        return True

    def previous_part(self) -> bool:
        if self.part_index == 0:
            return False
        self.part_index -= 1
        self.save_position(0.0)
        return True

    def toggle_spoilers(self) -> None:
        self.reveal_spoilers = not self.reveal_spoilers

    # ---- rendering --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="heading")
        with VerticalScroll(id="body-scroll"):
            yield Markdown("", id="body")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_view()

    def on_markdown_table_of_contents_updated(self, event: Markdown.TableOfContentsUpdated) -> None:
        """Fires once Markdown finishes asynchronously mounting its content blocks.

        `Markdown.update()` returns an awaitable that mounts blocks in the
        background; `max_scroll_y` reads 0 until that finishes, so restoring a
        saved fractional scroll position any earlier (e.g. from
        `call_after_refresh` alone, which fires before the mount completes)
        would compute against a not-yet-real content height and land at 0. This
        message is the earliest reliable "layout is now correct" signal. Only
        acted on once, for the initial resume — later part changes reset
        position deliberately (see `next_part`/`previous_part`).
        """
        if self._scroll_restored:
            return
        self._scroll_restored = True
        # Even once mounting completes, the scroll region's own metrics
        # (`max_scroll_y`) settle on the *following* layout pass, not this one —
        # one more `call_after_refresh` hop is needed before they're trustworthy.
        self.call_after_refresh(self._restore_scroll_position)

    def _restore_scroll_position(self, attempts: int = 20) -> None:
        """Apply the saved fractional read position, if this is the resumed part.

        `max_scroll_y` can still read 0 for a few more layout passes after
        Markdown finishes mounting its blocks (the scroll region's own metrics
        settle a beat later). Retry across a bounded number of refresh cycles
        rather than guessing a fixed number of hops.
        """
        story = self.service.stories.get(self.story_id)
        if story is None or story.last_read_offset <= 0:
            return
        try:
            scroll = self.query_one("#body-scroll", VerticalScroll)
        except Exception:  # noqa: BLE001 - screen may be torn down before mount completes
            return
        if scroll.max_scroll_y <= 0 and attempts > 0:
            self.call_after_refresh(lambda: self._restore_scroll_position(attempts - 1))
            return
        maximum = max(scroll.max_scroll_y, 1)
        scroll.scroll_y = min(story.last_read_offset, 1.0) * maximum

    def refresh_view(self) -> None:
        self.query_one("#heading", Static).update(
            f"{self.heading()}  ({self.part_index + 1}/{len(self.groups)})"
        )
        self.query_one("#body", Markdown).update(self.rendered_text())

    def action_next(self) -> None:
        if self.next_part():
            self.refresh_view()

    def action_previous(self) -> None:
        if self.previous_part():
            self.refresh_view()

    def action_toggle_spoilers(self) -> None:
        self.toggle_spoilers()
        self.refresh_view()

    def action_page_down(self) -> None:
        self.query_one("#body-scroll", VerticalScroll).scroll_page_down()

    def action_page_up(self) -> None:
        self.query_one("#body-scroll", VerticalScroll).scroll_page_up()

    def action_scroll_top(self) -> None:
        self.query_one("#body-scroll", VerticalScroll).scroll_home()

    def action_scroll_bottom(self) -> None:
        self.query_one("#body-scroll", VerticalScroll).scroll_end()

    def on_unmount(self) -> None:
        """Persist how far through the part the reader had scrolled."""
        try:
            scroll = self.query_one("#body-scroll", VerticalScroll)
        except Exception:  # noqa: BLE001 - screen may be torn down before mount completes
            return
        maximum = max(scroll.max_scroll_y, 1)
        self.save_position(min(1.0, scroll.scroll_y / maximum))
