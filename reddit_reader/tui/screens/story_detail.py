"""Story Detail — parts, gaps, tracking, backfill, cleaning approval, export."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from reddit_reader.models import CleaningRule
from reddit_reader.ordering import format_part_number
from reddit_reader.reddit_client import RedditError
from reddit_reader.service import ReaderService

# Cap how many gap numbers get joined into the displayed summary string — a
# story with a title-parsing hiccup can otherwise render dozens of numbers into
# one line.
GAP_DISPLAY_LIMIT = 10


class StoryDetailScreen(Screen[None]):
    """Everything you can do to one story."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("r", "read", "Read"),
        ("t", "track", "Track"),
        ("u", "untrack", "Untrack"),
        ("f", "find_missing", "Find missing"),
        ("e", "export", "Export"),
        ("l", "export_links", "Export links"),
        ("c", "propose_cleaning", "Detect boilerplate"),
        ("escape", "app.back", "Back"),
    ]

    def __init__(self, service: ReaderService, story_id: int) -> None:
        super().__init__()
        self.service = service
        self.story_id = story_id
        self._pending: list[CleaningRule] = []

    # ---- data -------------------------------------------------------------------

    def part_rows(self) -> list[tuple[str, str, str]]:
        """(label, posted date, flags) for each part, in reading order."""
        flags_by_id = {part.post_id: part for part in self.service.stories.parts(self.story_id)}
        rows: list[tuple[str, str, str]] = []

        for group in self.service.ordered_groups(self.story_id):
            lead = group[0]
            if lead.parsed.part_number is not None:
                label = f"Part {format_part_number(lead.parsed.part_number)}"
            elif lead.parsed.part_label:
                label = lead.parsed.part_label
            else:
                label = lead.post.title

            flags: list[str] = []
            part = flags_by_id.get(lead.post.id)
            if part is not None and part.newly_filled:
                flags.append("NEW (backfilled)")
            if not lead.post.available:
                flags.append("unavailable upstream")
            if len(group) > 1:
                flags.append(f"{len(group)} segments")

            rows.append((label, lead.post.created_utc.date().isoformat(), ", ".join(flags)))

        return rows

    def gap_summary(self) -> str:
        gaps = self.service.gaps(self.story_id)
        if not gaps:
            return "No gaps detected."
        shown = gaps[:GAP_DISPLAY_LIMIT]
        text = ", ".join(format_part_number(g) for g in shown)
        if len(gaps) > GAP_DISPLAY_LIMIT:
            text += f", … and {len(gaps) - GAP_DISPLAY_LIMIT} more"
        return "Missing parts: " + text

    def can_find_missing(self) -> bool:
        """Only meaningful when gaps exist — otherwise no API calls are made at all."""
        return bool(self.service.gaps(self.story_id))

    def pending_rules(self) -> list[CleaningRule]:
        return self._pending

    # ---- operations -------------------------------------------------------------

    def do_track(self) -> int:
        count = self.service.track(self.story_id)
        self._pending = self.service.propose_cleaning_rules(self.story_id)
        return count

    def do_untrack(self) -> int:
        return self.service.untrack(self.story_id)

    def do_export(self) -> Path:
        return self.service.export_story(self.story_id)

    def do_export_links(self) -> Path:
        return self.service.export_links_file(self.story_id)

    def approve_rule(self, index: int, approved: bool) -> None:
        rule = self._pending[index]
        rule.approved = approved
        rule_id = self.service.stories.add_cleaning_rule(rule)
        self.service.stories.set_rule_decision(rule_id, approved)
        self._pending.pop(index)

    # ---- rendering --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="summary")
        yield DataTable(id="parts")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#parts", DataTable)
        table.cursor_type = "row"
        table.add_columns("Part", "Posted", "Flags")
        self.refresh_view()

    def refresh_view(self) -> None:
        story = self.service.stories.get(self.story_id)
        if story is None:
            return

        tracked = "tracked" if story.tracked else "untracked"
        status = self.service.story_status(story).value
        self.query_one("#summary", Static).update(
            f"{story.title} by {story.author} — {status}, {tracked}\n{self.gap_summary()}"
        )

        table = self.query_one("#parts", DataTable)
        table.clear()
        for label, posted, flags in self.part_rows():
            table.add_row(label, posted, flags or "-")

        if self._pending:
            preview = self._pending[0]
            self._status(
                f"Detected boilerplate in {preview.seen_in_parts} parts — "
                "press 'y' to strip it, 'n' to keep it."
            )

    def _status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    # ---- actions ----------------------------------------------------------------

    def action_read(self) -> None:
        from reddit_reader.tui.screens.reader import ReaderScreen

        story = self.service.stories.get(self.story_id)
        if story is None or not story.tracked:
            self._status("Track this story first (t) to cache its text.")
            return
        self.app.push_screen(ReaderScreen(self.service, self.story_id))

    def action_track(self) -> None:
        try:
            count = self.do_track()
        except RedditError as exc:
            self._status(f"Tracking failed: {exc}")
            return
        self._status(f"Tracked. Cached {count} bodies.")
        self.refresh_view()

    def action_untrack(self) -> None:
        count = self.do_untrack()
        self._status(f"Untracked. Dropped {count} cached bodies.")
        self.refresh_view()

    def action_find_missing(self) -> None:
        if not self.can_find_missing():
            self._status("No gaps — nothing to find.")
            return
        try:
            matches = self.service.find_missing_parts(self.story_id)
        except RedditError as exc:
            self._status(f"Find missing failed: {exc}")
            return
        self._status(f"Found {len(matches)} candidate groups from author history.")
        self.refresh_view()

    def action_export(self) -> None:
        self._status(f"Wrote {self.do_export()}")

    def action_export_links(self) -> None:
        self._status(f"Wrote {self.do_export_links()}")

    def action_propose_cleaning(self) -> None:
        self._pending = self.service.propose_cleaning_rules(self.story_id)
        self._status(
            f"{len(self._pending)} boilerplate blocks detected."
            if self._pending
            else "No repeated boilerplate found."
        )
        self.refresh_view()
