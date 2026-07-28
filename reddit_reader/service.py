"""Application operations binding storage, detection, and the Reddit client.

Both the CLI and the TUI call into here, so neither holds business logic.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel

from reddit_reader.cleaning import detect_boilerplate, strip_patterns
from reddit_reader.config import Settings
from reddit_reader.detection import (
    decide_attachment,
    find_gaps,
    group_posts,
    series_key,
)
from reddit_reader.export import (
    export_filename,
    render_links,
    render_markdown,
    write_export,
)
from reddit_reader.models import (
    CleaningRule,
    DetectionMatch,
    PostMeta,
    Story,
    StoryPart,
    StoryStatus,
    UnavailablePart,
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


class StorageUsage(BaseModel):
    """How much disk the local cache is using."""

    total_bytes: int
    body_bytes: int
    post_count: int
    body_count: int


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
            # Record this subreddit's own fetch state as soon as its listing
            # succeeds, so each subreddit's position is independent of whether a
            # later one in the batch fails.
            self.posts.record_fetch(subreddit, datetime.now(UTC))

        self.posts.upsert_many(collected)
        for post in collected:
            self.search.index_title(post)

        matches = group_posts(
            collected, self.settings.subreddits, window_hours=self.settings.dedupe_window_hours
        )

        auto_attached = 0
        candidates: list[DetectionMatch] = []

        for match in matches:
            existing = self.stories.find_committed(
                series_key(match.author, match.base_title), match.volume
            )
            decision = decide_attachment(match, existing, self.settings.attach_threshold)

            if decision.action == "auto_attach" and decision.story_id is not None:
                auto_attached += self.attach_parts(decision.story_id, match)
            else:
                match.existing_story_id = decision.story_id
                candidates.append(match)

        return FetchResult(
            fetched=len(collected), auto_attached=auto_attached, candidates=candidates
        )

    def attach_parts(self, story_id: int, match: DetectionMatch) -> int:
        """Add any of `match`'s posts not already in the story. Returns how many."""
        known = set(self.stories.part_post_ids(story_id))
        new_ids = [post_id for post_id in match.post_ids if post_id not in known]
        if not new_ids:
            return 0

        story = self.stories.get(story_id)
        read_key = self._read_sort_key(story_id) if story else None

        for part in self._build_parts(
            story_id, match.post_ids, match.confidence, match.alternate_post_ids
        ):
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
        self,
        story_id: int,
        post_ids: Sequence[str],
        confidence: float,
        alternate_post_ids: Mapping[str, Sequence[str]] | None = None,
    ) -> list[StoryPart]:
        metas = self.posts.get_many(list(post_ids))
        ordered = resolve_order([(m, parse_title(m.title)) for m in metas])
        alternates = alternate_post_ids or {}
        return [
            StoryPart(
                post_id=item.post.id,
                story_id=story_id,
                part_number=item.parsed.part_number,
                part_label=item.parsed.part_label,
                segment=item.parsed.segment,
                segment_count=item.parsed.segment_count,
                sort_key=item.sort_key,
                alternate_post_ids=list(alternates.get(item.post.id, [])),
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
        for part in self._build_parts(
            story_id, match.post_ids, match.confidence, match.alternate_post_ids
        ):
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
                meta = self.client.get_meta_by_id(candidate)
                if meta is not None:
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

    # ---- gaps and backfill ------------------------------------------------------

    def gaps(self, story_id: int) -> list[Decimal]:
        """Interior gaps and a missing start, minus anything known unavailable."""
        numbers = [
            part.part_number
            for part in self.stories.parts(story_id)
            if part.part_number is not None
        ]
        unavailable = [rec.part_number for rec in self.stories.unavailable(story_id)]
        return find_gaps(numbers, unavailable)

    def mark_unavailable(self, story_id: int, part_number: Decimal, auto: bool = False) -> None:
        self.stories.add_unavailable(
            UnavailablePart(story_id=story_id, part_number=part_number, auto_marked=auto)
        )

    def clear_unavailable(self, story_id: int, part_number: Decimal) -> None:
        self.stories.clear_unavailable(story_id, part_number)

    def find_missing_parts(self, story_id: int) -> list[DetectionMatch]:
        """Pull author history to backfill gaps. Only meaningful when gaps exist."""
        missing = self.gaps(story_id)
        if not missing:
            return []

        story = self.stories.get(story_id)
        if story is None:
            return []

        history = self.client.author_submissions(story.author)
        self.posts.upsert_many(history)
        for post in history:
            self.search.index_title(post)

        known = set(self.stories.part_post_ids(story_id))
        target_key = series_key(story.author, story.title.lower())

        candidates: list[DetectionMatch] = []
        found_numbers: set[Decimal] = set()

        for match in group_posts(
            history, self.settings.subreddits, window_hours=self.settings.dedupe_window_hours
        ):
            if series_key(match.author, match.base_title) != target_key:
                continue
            if match.volume != story.volume:
                continue
            new_ids = [pid for pid in match.post_ids if pid not in known]
            if not new_ids:
                continue
            match.post_ids = new_ids
            match.existing_story_id = story_id
            candidates.append(match)
            for meta in self.posts.get_many(new_ids):
                parsed = parse_title(meta.title)
                if parsed.part_number is not None:
                    found_numbers.add(parsed.part_number)

        # Anything the author's full history could not produce is unfillable.
        for number in missing:
            if number not in found_numbers:
                self.mark_unavailable(story_id, number, auto=True)

        return candidates

    # ---- export -----------------------------------------------------------------

    def _rules_for(self, story_id: int) -> list[CleaningRule]:
        if not self.settings.cleaning_enabled:
            return []
        return self.stories.cleaning_rules(story_id)

    def export_story(self, story_id: int) -> Path:
        """Regenerate the story's full markdown file, overwriting in place."""
        story = self.stories.get(story_id)
        if story is None:
            raise ValueError(f"no story with id {story_id}")

        groups = self.ordered_groups(story_id)
        bodies = {
            post_id: body.selftext
            for post_id in self.stories.part_post_ids(story_id)
            if (body := self.posts.get_body(post_id)) is not None
        }

        content = render_markdown(
            story,
            groups,
            bodies,
            self._rules_for(story_id),
            strip_known_patterns=self.settings.cleaning_enabled,
        )
        path = self.settings.export_dir / export_filename(story)
        write_export(path, content)

        story.exported_markdown_path = str(path)
        story.exported_at = datetime.now(UTC)
        self.stories.update(story)
        return path

    def export_links_file(self, story_id: int) -> Path:
        story = self.stories.get(story_id)
        if story is None:
            raise ValueError(f"no story with id {story_id}")

        alternates: dict[str, list[PostMeta]] = {}
        for part in self.stories.parts(story_id):
            if part.alternate_post_ids:
                alternates[part.post_id] = self.posts.get_many(part.alternate_post_ids)

        content = render_links(story, self.ordered_groups(story_id), alternates)
        path = self.settings.export_dir / export_filename(story).replace(".md", "-links.md")
        write_export(path, content)
        return path

    # ---- search -----------------------------------------------------------------

    def search_local(self, query: str, limit: int = 50) -> list[PostMeta]:
        return self.posts.get_many(self.search.search(query, limit))

    def search_live(
        self, query: str, subreddit: str | None = None, limit: int = 50
    ) -> list[PostMeta]:
        """Search Reddit directly, merging results into the local cache."""
        found = self.client.search(query, subreddit, limit)
        self.posts.upsert_many(found)
        for post in found:
            self.search.index_title(post)
        return found

    # ---- storage management -----------------------------------------------------

    def delete_story(self, story_id: int) -> None:
        """Remove a story and its annotations; PostMeta survives for re-detection."""
        post_ids = self.stories.part_post_ids(story_id)
        self.posts.delete_bodies(post_ids)
        for post_id in post_ids:
            self.search.remove_body(post_id)
        self.stories.delete(story_id)

    def prune_orphans(self) -> int:
        """Clear cached metadata belonging to no story."""
        orphans = self.posts.orphaned_ids()
        for post_id in orphans:
            self.search.remove(post_id)
        return self.posts.delete_meta(orphans)

    def storage_usage(self) -> StorageUsage:
        counts = self.posts.conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM post_meta) AS posts,
                (SELECT COUNT(*) FROM post_body) AS bodies,
                (SELECT COALESCE(SUM(LENGTH(selftext)), 0) FROM post_body) AS body_bytes
            """
        ).fetchone()
        page_info = self.posts.conn.execute(
            "SELECT page_count * page_size AS total FROM pragma_page_count(), pragma_page_size()"
        ).fetchone()
        return StorageUsage(
            total_bytes=page_info["total"],
            body_bytes=counts["body_bytes"],
            post_count=counts["posts"],
            body_count=counts["bodies"],
        )

    # ---- learned cleaning -------------------------------------------------------

    def propose_cleaning_rules(self, story_id: int) -> list[CleaningRule]:
        """Detect repeated headers/footers. Returns proposals only — never applied.

        Detection runs over `strip_patterns()` output, not the raw body: `clean()`
        strips known patterns (nav links, plugs, sign-offs) *before* applying a
        learned rule, so a learned block must be discovered against that same
        pattern-stripped text. Otherwise a block that overlapped pattern-stripped
        content (a nav-link line immediately above a recurring header, the most
        common real HFY shape) would be learned against text that no longer
        exists at apply time, and `apply_rules`'s line-for-line match would
        silently strip nothing.
        """
        bodies = [
            strip_patterns(body.selftext)
            for post_id in self.stories.part_post_ids(story_id)
            if (body := self.posts.get_body(post_id)) is not None
        ]
        blocks = detect_boilerplate(
            bodies,
            window=self.settings.cleaning_window,
            majority=self.settings.cleaning_majority,
            min_parts=self.settings.cleaning_min_parts,
        )
        return [
            CleaningRule(
                story_id=story_id,
                position=block.position,
                block=block.block,
                seen_in_parts=block.seen_in_parts,
            )
            for block in blocks
        ]
