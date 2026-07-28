from pathlib import Path

import pytest

from reddit_reader.config import Settings
from reddit_reader.models import PostBody, StoryStatus
from reddit_reader.reddit_client import RedditClient
from reddit_reader.service import ReaderService
from reddit_reader.storage import PostRepository, SearchIndex, StoryRepository, connect
from tests.fakes import FakeReddit, make_submission


@pytest.fixture
def service(tmp_path: Path) -> ReaderService:
    conn = connect(tmp_path / "t.db")
    reddit = FakeReddit(
        submissions=[
            make_submission("a1", "The Long Road - Part 1", created_days=0),
            make_submission("a2", "The Long Road - Part 2", created_days=7),
            make_submission("a3", "The Long Road - Part 3", created_days=14),
        ]
    )
    return ReaderService(
        settings=Settings(subreddits=["HFY"], export_dir=tmp_path / "out"),
        posts=PostRepository(conn),
        stories=StoryRepository(conn),
        search=SearchIndex(conn),
        client=RedditClient(reddit),
    )


def test_fetch_stores_post_metadata(service: ReaderService) -> None:
    result = service.fetch()
    assert result.fetched == 3
    assert service.posts.get_meta("a1") is not None


def test_fetch_records_fetch_state_for_each_subreddit(service: ReaderService) -> None:
    """Item 11: refreshing one subreddit is supposed to leave its own fetch
    state behind, independent of any other configured subreddit."""
    assert service.posts.last_fetched("HFY") is None
    service.fetch()
    assert service.posts.last_fetched("HFY") is not None


def test_fetch_does_not_store_bodies(service: ReaderService) -> None:
    service.fetch()
    assert service.posts.get_body("a1") is None


def test_fetch_indexes_titles_for_search(service: ReaderService) -> None:
    service.fetch()
    assert service.search.search("Long Road")


def test_fetch_produces_a_candidate_series(service: ReaderService) -> None:
    result = service.fetch()
    assert len(result.candidates) == 1
    assert len(result.candidates[0].post_ids) == 3


def test_commit_match_creates_a_story_with_parts(service: ReaderService) -> None:
    match = service.fetch().candidates[0]
    story_id = service.commit_match(match)
    assert service.stories.get(story_id) is not None
    assert len(service.stories.parts(story_id)) == 3


def test_committed_story_records_series_key_and_author(service: ReaderService) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    story = service.stories.get(story_id)
    assert story is not None
    assert story.author == "BlueFishcake"
    assert story.series_key.startswith("bluefishcake:")


def test_second_fetch_auto_attaches_a_new_part(service: ReaderService) -> None:
    service.commit_match(service.fetch().candidates[0])
    service.client._reddit.submissions.append(  # type: ignore[attr-defined]
        make_submission("a4", "The Long Road - Part 4", created_days=21)
    )
    result = service.fetch()
    assert result.auto_attached == 1


def test_auto_attached_part_joins_the_existing_story(service: ReaderService) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    service.client._reddit.submissions.append(  # type: ignore[attr-defined]
        make_submission("a4", "The Long Road - Part 4", created_days=21)
    )
    service.fetch()
    assert len(service.stories.parts(story_id)) == 4


def test_new_volume_does_not_attach_to_the_previous_book(service: ReaderService) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    service.client._reddit.submissions.append(  # type: ignore[attr-defined]
        make_submission("b1", "The Long Road, Book Two, Chapter 1", created_days=30)
    )
    result = service.fetch()
    assert result.auto_attached == 0
    assert len(service.stories.parts(story_id)) == 3


def test_track_fetches_bodies_and_indexes_them(service: ReaderService) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    assert service.track(story_id) == 3
    assert service.posts.get_body("a1") is not None
    story = service.stories.get(story_id)
    assert story is not None
    assert story.tracked is True


def test_untrack_drops_bodies_and_search_entries(service: ReaderService) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)
    assert service.untrack(story_id) == 3
    assert service.posts.get_body("a1") is None
    story = service.stories.get(story_id)
    assert story is not None
    assert story.tracked is False


def test_untrack_keeps_the_story_and_read_position(service: ReaderService) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)
    service.mark_read(story_id, "a2", 0.5)
    service.untrack(story_id)
    story = service.stories.get(story_id)
    assert story is not None
    assert story.last_read_part == "a2"


def test_unread_count_is_derived_from_read_position(service: ReaderService) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    service.mark_read(story_id, "a1", 1.0)
    assert service.unread_count(story_id) == 2


def test_unread_count_is_everything_when_nothing_read(service: ReaderService) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    assert service.unread_count(story_id) == 3


def test_story_status_is_stale_for_old_serials(service: ReaderService) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    story = service.stories.get(story_id)
    assert story is not None
    service.settings.stale_after_days = 1
    assert service.story_status(story) == StoryStatus.STALE


def test_story_status_is_ongoing_for_recent_serials(service: ReaderService, tmp_path: Path) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    story = service.stories.get(story_id)
    assert story is not None
    service.settings.stale_after_days = 100_000
    assert service.story_status(story) == StoryStatus.ONGOING


def test_story_status_is_complete_when_a_title_says_so(service: ReaderService) -> None:
    service.client._reddit.submissions.append(  # type: ignore[attr-defined]
        make_submission("z9", "The Long Road - Part 4 [Complete]", created_days=21)
    )
    story_id = service.commit_match(service.fetch().candidates[0])
    story = service.stories.get(story_id)
    assert story is not None
    assert service.story_status(story) == StoryStatus.COMPLETE


def test_nav_expansion_finds_a_part_the_titles_missed(service: ReaderService) -> None:
    # An inconsistently titled chapter that title matching cannot group,
    # but which part 3's Next link points at.
    service.client._reddit.submissions.append(  # type: ignore[attr-defined]
        make_submission("odd1", "A Detour", created_days=21)
    )
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)
    service.posts.set_body(
        __import__("reddit_reader.models", fromlist=["PostBody"]).PostBody(
            post_id="a3",
            selftext="End of chapter.\n\n[Next](https://www.reddit.com/r/HFY/comments/odd1/x/)",
        )
    )
    assert service.nav_link_expansion(story_id) == ["odd1"]


def test_nav_expansion_ignores_parts_already_in_the_story(service: ReaderService) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)
    service.posts.set_body(
        __import__("reddit_reader.models", fromlist=["PostBody"]).PostBody(
            post_id="a1",
            selftext="[Next](https://www.reddit.com/r/HFY/comments/a2/x/)",
        )
    )
    assert service.nav_link_expansion(story_id) == []


def test_nav_expansion_is_empty_for_untracked_stories(service: ReaderService) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    assert service.nav_link_expansion(story_id) == []


def test_crosspost_pair_collapses_to_one_part_with_alternate_recorded(tmp_path: Path) -> None:
    """Item 9: a collapsed duplicate/mirror must be recorded as an alternate on
    the surviving StoryPart, not silently discarded — and that has to survive a
    write/read round trip through storage, not just live in memory."""
    conn = connect(tmp_path / "dup.db")
    reddit = FakeReddit(
        submissions=[
            make_submission("m1", "Road - Part 1", created_days=0, subreddit_name="HFY"),
            make_submission(
                "m1x",
                "Road - Part 1",
                created_days=0,
                subreddit_name="RoadMirror",
                crosspost_parent="t3_m1",
            ),
        ]
    )
    svc = ReaderService(
        settings=Settings(subreddits=["HFY", "RoadMirror"], export_dir=tmp_path / "out"),
        posts=PostRepository(conn),
        stories=StoryRepository(conn),
        search=SearchIndex(conn),
        client=RedditClient(reddit),
    )
    story_id = svc.commit_match(svc.fetch().candidates[0])
    parts = svc.stories.parts(story_id)
    assert len(parts) == 1
    assert parts[0].alternate_post_ids == ["m1x"]

    # Round-trip: read it back fresh from storage, not the in-memory object.
    reloaded = svc.stories.parts(story_id)
    assert reloaded[0].alternate_post_ids == ["m1x"]


def test_nav_expansion_fetches_metadata_for_a_candidate_not_yet_cached(
    service: ReaderService,
) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)

    # Unlike odd1 in the earlier test, this post was never part of any
    # listing fetch, so its metadata is genuinely absent from the local
    # cache -- only reachable through a direct by-id lookup.
    service.client._reddit.submissions.append(  # type: ignore[attr-defined]
        make_submission("odd2", "A Second Detour", created_days=22)
    )
    service.posts.set_body(
        PostBody(
            post_id="a3",
            selftext="End of chapter.\n\n[Next](https://www.reddit.com/r/HFY/comments/odd2/x/)",
        )
    )

    assert service.posts.get_meta("odd2") is None
    assert service.nav_link_expansion(story_id) == ["odd2"]
    assert service.posts.get_meta("odd2") is not None
