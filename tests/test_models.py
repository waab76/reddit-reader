from datetime import UTC, datetime
from decimal import Decimal

from reddit_reader.models import (
    CleaningPosition,
    CleaningRule,
    DetectionMatch,
    PostBody,
    PostMeta,
    Story,
    StoryPart,
    StoryStatus,
    UnavailablePart,
)


def _post(post_id: str = "abc123") -> PostMeta:
    return PostMeta(
        id=post_id,
        subreddit="HFY",
        author="BlueFishcake",
        title="The Long Road - Chapter 12",
        permalink="/r/HFY/comments/abc123/the_long_road_chapter_12/",
        created_utc=datetime(2026, 1, 1, tzinfo=UTC),
        score=4200,
    )


def test_postmeta_defaults_to_available_with_no_crosspost() -> None:
    post = _post()
    assert post.available is True
    assert post.crosspost_parent is None


def test_postmeta_url_builds_absolute_permalink() -> None:
    assert _post().url == "https://reddit.com/r/HFY/comments/abc123/the_long_road_chapter_12/"


def test_postbody_holds_raw_text() -> None:
    body = PostBody(post_id="abc123", selftext="Once upon a time.")
    assert body.selftext == "Once upon a time."


def test_storypart_accepts_decimal_part_numbers() -> None:
    part = StoryPart(post_id="abc123", story_id=1, part_number=Decimal("4.5"))
    assert part.part_number == Decimal("4.5")


def test_storypart_defaults() -> None:
    part = StoryPart(post_id="abc123", story_id=1)
    assert part.part_number is None
    assert part.part_label is None
    assert part.segment is None
    assert part.newly_filled is False
    assert part.alternate_post_ids == []


def test_story_defaults_to_untracked_and_unread() -> None:
    story = Story(
        id=1, series_key="bluefishcake:the long road", title="The Long Road", author="BlueFishcake"
    )
    assert story.tracked is False
    assert story.volume is None
    assert story.last_read_part is None
    assert story.last_read_offset == 0.0


def test_unavailable_part_records_how_it_was_marked() -> None:
    rec = UnavailablePart(story_id=1, part_number=Decimal("4"), auto_marked=True)
    assert rec.auto_marked is True


def test_cleaning_rule_starts_undecided() -> None:
    rule = CleaningRule(
        story_id=1,
        position=CleaningPosition.LEADING,
        block="---\n[First] [Prev] [Next]\n---",
        seen_in_parts=9,
    )
    assert rule.approved is None


def test_detection_match_carries_confidence_and_reasons() -> None:
    match = DetectionMatch(
        base_title="the long road",
        author="BlueFishcake",
        volume=None,
        post_ids=["abc123", "def456"],
        confidence=0.91,
        reasons=["titles 98% similar", "part numbers ascend cleanly"],
    )
    assert match.confidence == 0.91
    assert match.reasons[0].startswith("titles")


def test_story_status_values() -> None:
    assert {s.value for s in StoryStatus} == {"complete", "ongoing", "stale"}
