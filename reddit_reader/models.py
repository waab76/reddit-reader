"""Pydantic models shared across every layer of the application."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field

REDDIT_BASE_URL = "https://reddit.com"


class StoryStatus(str, Enum):  # noqa: UP042
    """Derived completion state of a story."""

    COMPLETE = "complete"
    ONGOING = "ongoing"
    STALE = "stale"


class CleaningPosition(str, Enum):  # noqa: UP042
    """Which end of a part a learned boilerplate block sits at."""

    LEADING = "leading"
    TRAILING = "trailing"


class PostMeta(BaseModel):
    """Lightweight post record, cached for every post the app has ever seen."""

    id: str
    subreddit: str
    author: str
    title: str
    permalink: str
    created_utc: datetime
    score: int
    crosspost_parent: str | None = None
    available: bool = True

    @property
    def url(self) -> str:
        return f"{REDDIT_BASE_URL}{self.permalink}"


class PostBody(BaseModel):
    """Raw post body, cached only for posts belonging to a tracked story."""

    post_id: str
    selftext: str


class StoryPart(BaseModel):
    """A post's membership in a story, with its resolved position."""

    post_id: str
    story_id: int
    part_number: Decimal | None = None
    part_label: str | None = None
    segment: int | None = None
    segment_count: int | None = None
    sort_key: str | None = None
    alternate_post_ids: list[str] = Field(default_factory=list)
    newly_filled: bool = False
    match_confidence: float = 0.0


class Story(BaseModel):
    """A committed series (one volume of one serial by one author)."""

    id: int
    series_key: str
    title: str
    author: str
    volume: int | None = None
    tracked: bool = False
    last_read_part: str | None = None
    last_read_offset: float = 0.0
    exported_markdown_path: str | None = None
    exported_at: datetime | None = None
    last_updated_at: datetime | None = None


class UnavailablePart(BaseModel):
    """A part number known to be unfillable, so gap detection stops reporting it."""

    story_id: int
    part_number: Decimal
    auto_marked: bool = False


class CleaningRule(BaseModel):
    """A learned per-story header/footer block and the user's decision about it."""

    story_id: int
    position: CleaningPosition
    block: str
    seen_in_parts: int
    approved: bool | None = None


class DetectionMatch(BaseModel):
    """A transient candidate grouping. Never persisted."""

    base_title: str
    author: str
    volume: int | None
    post_ids: list[str]
    confidence: float
    reasons: list[str] = Field(default_factory=list)
    existing_story_id: int | None = None
    # Non-canonical duplicate/mirrored post ids collapsed into each canonical
    # post in `post_ids`, keyed by that canonical post's id. Threaded through to
    # `StoryPart.alternate_post_ids` so a collapsed mirror is recorded rather
    # than silently discarded.
    alternate_post_ids: dict[str, list[str]] = Field(default_factory=dict)
