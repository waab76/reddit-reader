"""Textual application shell."""

from __future__ import annotations

import logging
from typing import ClassVar

from textual import events
from textual.app import App
from textual.binding import BindingType

from reddit_reader.service import ReaderService
from reddit_reader.tui.screens.story_list import StoryListScreen

logger = logging.getLogger(__name__)


class RedditReaderApp(App[None]):
    """The interactive reader. Story List is home."""

    CSS = """
    Screen { layout: vertical; }
    DataTable { height: 1fr; }
    /* Not docked: Footer already docks bottom, and a second dock to the same
       edge lands #status in that exact region too, so Footer just paints
       over it. Left in normal flow, #status settles directly above Footer
       instead (the docked Footer's space is excluded from the flow). */
    #status { height: 1; background: $panel; color: $text-muted; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        ("q", "quit", "Quit"),
        ("escape", "back", "Back"),
    ]

    def __init__(self, service: ReaderService) -> None:
        super().__init__()
        self.service = service

    def on_mount(self) -> None:
        logger.info("app started")
        self.push_screen(StoryListScreen(self.service))

    def on_key(self, event: events.Key) -> None:
        """DEBUG-trace every keypress, whichever screen/widget ends up handling it.

        This fires regardless of what (if anything) the key is bound to —
        Textual resolves bindings across the whole focus chain up in the App,
        so this handler still sees the key even when a screen or widget deep
        in that chain consumes it. Paging keys are exempted (see
        `PAGING_KEYS`): they fire constantly while reading and add noise
        without diagnostic value.
        """
        if event.key in getattr(self.screen, "PAGING_KEYS", frozenset()):
            return
        logger.debug("key=%s screen=%s", event.key, type(self.screen).__name__)

    async def action_back(self) -> None:
        """Pop to the previous screen, but never past Story List.

        Textual always keeps its own blank default screen at the bottom of
        the stack, underneath whatever `on_mount` pushes — so `screen_stack`
        is never actually length 1 while sitting on Story List, and a naive
        depth check would happily pop into that empty screen with no way
        back except quitting.
        """
        if isinstance(self.screen, StoryListScreen):
            return
        if len(self.screen_stack) > 1:
            self.pop_screen()
