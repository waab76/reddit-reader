from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from reddit_reader.models import (
    CleaningPosition,
    CleaningRule,
    PostMeta,
    Story,
    StoryPart,
    UnavailablePart,
)
from reddit_reader.storage.db import connect
from reddit_reader.storage.posts import PostRepository
from reddit_reader.storage.stories import StoryRepository


@pytest.fixture
def repos(tmp_path: Path) -> tuple[StoryRepository, PostRepository]:
    conn = connect(tmp_path / "t.db")
    return StoryRepository(conn), PostRepository(conn)


def a_story(**kwargs: object) -> Story:
    base = {
        "id": 0,
        "series_key": "bluefishcake:the long road",
        "title": "The Long Road",
        "author": "BlueFishcake",
    }
    base.update(kwargs)
    return Story(**base)  # type: ignore[arg-type]


def a_post(post_id: str) -> PostMeta:
    return PostMeta(
        id=post_id,
        subreddit="HFY",
        author="BlueFishcake",
        title="The Long Road",
        permalink=f"/r/HFY/comments/{post_id}/x/",
        created_utc=datetime(2026, 1, 1, tzinfo=UTC),
        score=1,
    )


def test_create_assigns_an_id(repos: tuple[StoryRepository, PostRepository]) -> None:
    stories, _ = repos
    assert stories.create(a_story()) == 1


def test_get_roundtrips(repos: tuple[StoryRepository, PostRepository]) -> None:
    stories, _ = repos
    story_id = stories.create(a_story(volume=2, tracked=True))
    got = stories.get(story_id)
    assert got is not None
    assert got.volume == 2
    assert got.tracked is True


def test_find_committed_matches_on_series_key_and_volume(
    repos: tuple[StoryRepository, PostRepository],
) -> None:
    stories, _ = repos
    stories.create(a_story(volume=1))
    stories.create(a_story(volume=2))
    book_two = stories.find_committed("bluefishcake:the long road", 2)
    assert book_two is not None
    assert book_two.volume == 2


def test_find_committed_returns_none_for_unknown_volume(
    repos: tuple[StoryRepository, PostRepository],
) -> None:
    stories, _ = repos
    stories.create(a_story(volume=1))
    assert stories.find_committed("bluefishcake:the long road", 3) is None


def test_by_series_key_groups_volumes(
    repos: tuple[StoryRepository, PostRepository],
) -> None:
    stories, _ = repos
    stories.create(a_story(volume=1))
    stories.create(a_story(volume=2))
    assert [s.volume for s in stories.by_series_key("bluefishcake:the long road")] == [1, 2]


def test_update_persists_read_position(
    repos: tuple[StoryRepository, PostRepository],
) -> None:
    stories, _ = repos
    story_id = stories.create(a_story())
    story = stories.get(story_id)
    assert story is not None
    story.last_read_part = "a1"
    story.last_read_offset = 0.42
    stories.update(story)
    reloaded = stories.get(story_id)
    assert reloaded is not None
    assert reloaded.last_read_part == "a1"
    assert reloaded.last_read_offset == pytest.approx(0.42)


def test_add_part_and_read_back(repos: tuple[StoryRepository, PostRepository]) -> None:
    stories, posts = repos
    posts.upsert_meta(a_post("a1"))
    story_id = stories.create(a_story())
    stories.add_part(
        StoryPart(
            post_id="a1",
            story_id=story_id,
            part_number=Decimal("4.5"),
            part_label="Part 4.5",
            alternate_post_ids=["b2", "c3"],
        )
    )
    part = stories.parts(story_id)[0]
    assert part.part_number == Decimal("4.5")
    assert part.alternate_post_ids == ["b2", "c3"]


def test_clear_newly_filled(repos: tuple[StoryRepository, PostRepository]) -> None:
    stories, posts = repos
    posts.upsert_meta(a_post("a1"))
    story_id = stories.create(a_story())
    stories.add_part(StoryPart(post_id="a1", story_id=story_id, newly_filled=True))
    stories.clear_newly_filled(story_id, "a1")
    assert stories.parts(story_id)[0].newly_filled is False


def test_unavailable_parts_roundtrip(
    repos: tuple[StoryRepository, PostRepository],
) -> None:
    stories, _ = repos
    story_id = stories.create(a_story())
    stories.add_unavailable(
        UnavailablePart(story_id=story_id, part_number=Decimal("4"), auto_marked=True)
    )
    recs = stories.unavailable(story_id)
    assert recs[0].part_number == Decimal("4")
    assert recs[0].auto_marked is True


def test_clear_unavailable_removes_the_mark(
    repos: tuple[StoryRepository, PostRepository],
) -> None:
    stories, _ = repos
    story_id = stories.create(a_story())
    stories.add_unavailable(UnavailablePart(story_id=story_id, part_number=Decimal("4")))
    stories.clear_unavailable(story_id, Decimal("4"))
    assert stories.unavailable(story_id) == []


def test_cleaning_rule_decision_persists(
    repos: tuple[StoryRepository, PostRepository],
) -> None:
    stories, _ = repos
    story_id = stories.create(a_story())
    rule_id = stories.add_cleaning_rule(
        CleaningRule(
            story_id=story_id,
            position=CleaningPosition.TRAILING,
            block="Support me on Patreon!",
            seen_in_parts=12,
        )
    )
    stories.set_rule_decision(rule_id, approved=False)
    assert stories.cleaning_rules(story_id)[0].approved is False


def test_delete_removes_story_and_its_parts(
    repos: tuple[StoryRepository, PostRepository],
) -> None:
    stories, posts = repos
    posts.upsert_meta(a_post("a1"))
    story_id = stories.create(a_story())
    stories.add_part(StoryPart(post_id="a1", story_id=story_id))
    stories.delete(story_id)
    assert stories.get(story_id) is None
    assert stories.parts(story_id) == []
    assert posts.get_meta("a1") is not None  # PostMeta deliberately survives
