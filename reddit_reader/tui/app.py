"""Textual application shell."""

from __future__ import annotations

from typing import ClassVar

from textual.app import App
from textual.binding import BindingType

from reddit_reader.service import ReaderService
from reddit_reader.tui.screens.story_list import StoryListScreen


class RedditReaderApp(App[None]):
    """The interactive reader. Story List is home."""

    CSS = """
    Screen { layout: vertical; }
    DataTable { height: 1fr; }
    #status { dock: bottom; height: 1; background: $panel; color: $text-muted; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        ("q", "quit", "Quit"),
        ("escape", "back", "Back"),
    ]

    def __init__(self, service: ReaderService) -> None:
        super().__init__()
        self.service = service

    def on_mount(self) -> None:
        self.push_screen(StoryListScreen(self.service))

    async def action_back(self) -> None:
        if len(self.screen_stack) > 1:
            self.pop_screen()
