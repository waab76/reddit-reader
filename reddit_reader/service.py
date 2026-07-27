"""Application operations binding storage, detection, and the Reddit client.

Both the CLI and the TUI call into here, so neither holds business logic.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import BaseModel

from reddit_reader.config import Settings
from reddit_reader.detection import (
    decide_attachment,
    group_posts,
    series_key,
)
from reddit_reader.models import (
    DetectionMatch,
    PostMeta,
    Story,
    StoryPart,
    StoryStatus,
)
from reddit_reader.navlinks import parse_nav_links
from reddit_reader.ordering import OrderedPart, group_segments, resolve_order
from reddit_reader.reddit_client import RedditClient
from reddit_reader.storage import PostRepository, SearchIndex, StoryRepository
from reddit_reader.titles import parse_title

COMPLETION_MARKERS = ("[complete]", "[final]", "[fin]", "the end")


class FetchResult(BaseModel):
    """What a fetch produced: raw counts plus candidates needing curation."""

    fetched: int
    auto_attached: int
    candidates: list[DetectionMatch]


class ReaderService:
    """Every operation the UI layers need."""

    def __init__(
        self,
        settings: Settings,
        posts: PostRepository,
        stories: StoryRepository,
        search: SearchIndex,
        client: RedditClient,
    ) -> None:
        self.settings = settings
        self.posts = posts
        self.stories = stories
        self.search = search
        self.client = client

    # ---- fetching and detection -------------------------------------------------

    def fetch(self, subreddits: Sequence[str] | None = None) -> FetchResult:
        """Fetch listings, store metadata, auto-attach known parts, return candidates."""
        targets = list(subreddits or self.settings.subreddits)
        collected: list[PostMeta] = []

        for subreddit in targets:
            collected.extend(
                self.client.fetch_listing(
                    subreddit,
                    self.settings.listing,
                    self.settings.fetch_limit,
                    self.settings.time_window,
                )
            )

        self.posts.upsert_many(collected)
        for post in collected:
            self.search.index_title(post)

        matches = group_posts(collected, self.settings.subreddits)

        auto_attached = 0
        candidates: list[DetectionMatch] = []

        for match in matches:
            existing = self.stories.find_committed(
                series_key(match.author, match.base_title), match.volume
            )
            decision = decide_attachment(match, existing, self.settings.attach_threshold)

            if decision.action == "auto_attach" and decision.story_id is not None:
                auto_attached += self._attach_parts(decision.story_id, match)
            else:
                match.existing_story_id = decision.story_id
                candidates.append(match)

        return FetchResult(
            fetched=len(collected), auto_attached=auto_attached, candidates=candidates
        )

    def _attach_parts(self, story_id: int, match: DetectionMatch) -> int:
        """Add any of `match`'s posts not already in the story. Returns how many."""
        known = set(self.stories.part_post_ids(story_id))
        new_ids = [post_id for post_id in match.post_ids if post_id not in known]
        if not new_ids:
            return 0

        story = self.stories.get(story_id)
        read_key = self._read_sort_key(story_id) if story else None

        for part in self._build_parts(story_id, match.post_ids, match.confidence):
            if part.post_id not in new_ids:
                continue
            # A part landing behind the read position can never be flagged unread by
            # derivation, so mark it explicitly.
            if read_key is not None and part.sort_key is not None and part.sort_key < read_key:
                part.newly_filled = True
            self.stories.add_part(part)
            if story and story.tracked:
                self._cache_body(part.post_id)

        if story:
            story.last_updated_at = datetime.now(UTC)
            self.stories.update(story)
            if story.tracked:
                # New parts arrived: re-run the nav pass over the enlarged story.
                self.nav_link_expansion(story_id)

        return len(new_ids)

    def _build_parts(
        self, story_id: int, post_ids: Sequence[str], confidence: float
    ) -> list[StoryPart]:
        metas = self.posts.get_many(list(post_ids))
        ordered = resolve_order([(m, parse_title(m.title)) for m in metas])
        return [
            StoryPart(
                post_id=item.post.id,
                story_id=story_id,
                part_number=item.parsed.part_number,
                part_label=item.parsed.part_label,
                segment=item.parsed.segment,
                segment_count=item.parsed.segment_count,
                sort_key=item.sort_key,
                match_confidence=confidence,
            )
            for item in ordered
        ]

    def commit_match(self, match: DetectionMatch) -> int:
        """Turn a curated candidate into a committed story."""
        story_id = self.stories.create(
            Story(
                id=0,
                series_key=series_key(match.author, match.base_title),
                title=match.base_title.title(),
                author=match.author,
                volume=match.volume,
                last_updated_at=datetime.now(UTC),
            )
        )
        for part in self._build_parts(story_id, match.post_ids, match.confidence):
            self.stories.add_part(part)
        return story_id

    # ---- tracking ---------------------------------------------------------------

    def _cache_body(self, post_id: str) -> None:
        for body in self.client.fetch_bodies([post_id]):
            self.posts.set_body(body)
            self.search.index_body(body.post_id, body.selftext)

    def track(self, story_id: int) -> int:
        """Track a story: eagerly cache every known part's body."""
        story = self.stories.get(story_id)
        if story is None:
            return 0

        post_ids = self.stories.part_post_ids(story_id)
        bodies = self.client.fetch_bodies(post_ids)
        for body in bodies:
            self.posts.set_body(body)
            self.search.index_body(body.post_id, body.selftext)

        # Anything we asked for and did not get back is gone upstream.
        returned = {b.post_id for b in bodies}
        for post_id in post_ids:
            if post_id not in returned:
                self.posts.mark_unavailable(post_id)

        story.tracked = True
        self.stories.update(story)

        # Bodies are local now, so the nav-link pass costs nothing but CPU.
        self.nav_link_expansion(story_id)
        return len(bodies)

    def nav_link_expansion(self, story_id: int) -> list[str]:
        """Follow First/Prev/Next chains in cached bodies to find parts titles missed.

        Runs only on tracked stories, where bodies are already cached. Returns
        candidate post ids — they are never silently added to the story.
        """
        story = self.stories.get(story_id)
        if story is None or not story.tracked:
            return []

        known = set(self.stories.part_post_ids(story_id))
        referenced: list[str] = []

        for post_id in known:
            body = self.posts.get_body(post_id)
            if body is None:
                continue
            links = parse_nav_links(body.selftext)
            for candidate in (links.first, links.previous, links.next):
                if candidate and candidate not in known and candidate not in referenced:
                    referenced.append(candidate)

        # Pull metadata for anything not already cached so it can be reviewed.
        for candidate in referenced:
            if self.posts.get_meta(candidate) is None:
                for meta in self.client.search(candidate, limit=1):
                    self.posts.upsert_meta(meta)
                    self.search.index_title(meta)

        return referenced

    def untrack(self, story_id: int) -> int:
        """Stop tracking: drop cached bodies and their search entries, keep the story."""
        post_ids = self.stories.part_post_ids(story_id)
        dropped = self.posts.delete_bodies(post_ids)
        for post_id in post_ids:
            self.search.remove_body(post_id)

        story = self.stories.get(story_id)
        if story:
            story.tracked = False
            self.stories.update(story)
        return dropped

    # ---- reading state ----------------------------------------------------------

    def ordered_parts(self, story_id: int) -> list[OrderedPart]:
        metas = self.posts.get_many(self.stories.part_post_ids(story_id))
        return resolve_order([(m, parse_title(m.title)) for m in metas])

    def ordered_groups(self, story_id: int) -> list[list[OrderedPart]]:
        return group_segments(self.ordered_parts(story_id))

    def _read_sort_key(self, story_id: int) -> str | None:
        story = self.stories.get(story_id)
        if story is None or story.last_read_part is None:
            return None
        for part in self.ordered_parts(story_id):
            if part.post.id == story.last_read_part:
                return part.sort_key
        return None

    def unread_count(self, story_id: int) -> int:
        """Parts ordering after the read position. Derived, never stored."""
        parts = self.ordered_parts(story_id)
        read_key = self._read_sort_key(story_id)
        if read_key is None:
            return len(parts)
        return sum(1 for part in parts if part.sort_key > read_key)

    def newly_filled(self, story_id: int) -> list[StoryPart]:
        """Backfilled parts sitting behind the read position, which unread can't catch."""
        return [part for part in self.stories.parts(story_id) if part.newly_filled]

    def mark_read(self, story_id: int, post_id: str, offset: float) -> None:
        story = self.stories.get(story_id)
        if story is None:
            return
        story.last_read_part = post_id
        story.last_read_offset = offset
        self.stories.update(story)
        self.stories.clear_newly_filled(story_id, post_id)

    # ---- status -----------------------------------------------------------------

    def story_status(self, story: Story) -> StoryStatus:
        """Derived from explicit completion markers, else the newest part's age."""
        metas = self.posts.get_many(self.stories.part_post_ids(story.id))
        if not metas:
            return StoryStatus.STALE

        for meta in metas:
            lowered = meta.title.lower()
            if any(marker in lowered for marker in COMPLETION_MARKERS):
                return StoryStatus.COMPLETE

        newest = max(meta.created_utc for meta in metas)
        age_days = (datetime.now(UTC) - newest).days
        return (
            StoryStatus.STALE if age_days > self.settings.stale_after_days else StoryStatus.ONGOING
        )
