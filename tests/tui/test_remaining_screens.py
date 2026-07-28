from datetime import UTC, datetime

import pytest
from textual.widgets import DataTable, Input, Static

from reddit_reader.models import DetectionMatch, PostMeta
from reddit_reader.reddit_client import RedditFetchError
from reddit_reader.service import FetchResult, ReaderService
from reddit_reader.tui.app import RedditReaderApp
from reddit_reader.tui.screens.browse import BrowseScreen
from reddit_reader.tui.screens.curation import CurationScreen
from reddit_reader.tui.screens.search import SearchScreen
from reddit_reader.tui.screens.storage_admin import StorageAdminScreen


def test_browse_fetch_returns_a_result(service: ReaderService) -> None:
    screen = BrowseScreen(service)
    assert screen.do_fetch().fetched == 3


def test_browse_rows_include_the_subreddit_column(service: ReaderService) -> None:
    screen = BrowseScreen(service)
    screen.do_fetch()
    assert all(row[1] == "HFY" for row in screen.rows())


def test_browse_can_switch_listing_type(service: ReaderService) -> None:
    screen = BrowseScreen(service)
    screen.set_listing("top")
    assert service.settings.listing == "top"


def test_browse_filter_narrows_to_one_subreddit(service: ReaderService) -> None:
    screen = BrowseScreen(service)
    screen.do_fetch()
    screen.set_subreddit_filter("Nonexistent")
    assert screen.rows() == []


def test_local_search_finds_cached_posts(service: ReaderService) -> None:
    service.fetch()
    screen = SearchScreen(service)
    assert [p.id for p in screen.do_local_search("Long Road")] == ["a1", "a2"]


def test_local_search_returns_nothing_for_a_miss(service: ReaderService) -> None:
    service.fetch()
    screen = SearchScreen(service)
    assert screen.do_local_search("dragons") == []


def test_live_search_caches_what_it_finds(service: ReaderService) -> None:
    screen = SearchScreen(service)
    found = screen.do_live_search("Second Wind", "HFY")
    assert [p.id for p in found] == ["b1"]
    assert service.posts.get_meta("b1") is not None


def test_curation_accept_commits_a_story(service: ReaderService) -> None:
    candidates = service.fetch().candidates
    screen = CurationScreen(service, candidates)
    story_id = screen.accept(0)
    assert service.stories.get(story_id) is not None


def test_curation_accept_attaches_to_an_existing_story(service: ReaderService) -> None:
    """`existing_story_id` set -> attach_parts, not commit_match (no new Story row)."""
    candidates = service.fetch().candidates
    target = next(c for c in candidates if len(c.post_ids) > 1)  # "The Long Road"
    story_id = service.commit_match(target)
    before_part_ids = set(service.stories.part_post_ids(story_id))
    story_count_before = len(service.stories.all_stories())

    new_post_id = "z9"
    service.posts.upsert_meta(
        PostMeta(
            id=new_post_id,
            subreddit="HFY",
            author=target.author,
            title="The Long Road - Part 99",
            permalink=f"/r/HFY/comments/{new_post_id}/x/",
            created_utc=datetime(2026, 2, 1, tzinfo=UTC),
            score=10,
        )
    )
    match = DetectionMatch(
        base_title=target.base_title,
        author=target.author,
        volume=target.volume,
        post_ids=[new_post_id],
        confidence=0.5,
        existing_story_id=story_id,
    )
    screen = CurationScreen(service, [match])
    result_id = screen.accept(0)

    assert result_id == story_id
    assert len(service.stories.all_stories()) == story_count_before  # no new story created
    assert new_post_id in service.stories.part_post_ids(story_id)
    assert before_part_ids < set(service.stories.part_post_ids(story_id))  # grew, didn't replace


def test_curation_drop_removes_a_candidate(service: ReaderService) -> None:
    candidates = service.fetch().candidates
    screen = CurationScreen(service, candidates)
    before = len(screen.candidates)
    screen.drop(0)
    assert len(screen.candidates) == before - 1


def test_curation_merge_combines_two_candidates(service: ReaderService) -> None:
    candidates = service.fetch().candidates
    assert len(candidates) >= 2
    screen = CurationScreen(service, candidates)
    total = len(candidates[0].post_ids) + len(candidates[1].post_ids)
    screen.merge(0, 1)
    assert len(screen.candidates[0].post_ids) == total


def test_curation_split_extracts_posts_into_a_new_candidate(
    service: ReaderService,
) -> None:
    candidates = service.fetch().candidates
    target = next(c for c in candidates if len(c.post_ids) > 1)
    index = candidates.index(target)
    screen = CurationScreen(service, candidates)
    moved = [target.post_ids[0]]
    screen.split(index, moved)
    assert any(c.post_ids == moved for c in screen.candidates)


def test_storage_usage_lines_are_human_readable(service: ReaderService) -> None:
    service.fetch()
    screen = StorageAdminScreen(service)
    lines = screen.usage_lines()
    assert any("post" in line.lower() for line in lines)


def test_storage_prune_reports_a_count(service: ReaderService) -> None:
    service.fetch()
    screen = StorageAdminScreen(service)
    assert screen.do_prune() == 3


def test_storage_delete_removes_the_story(service: ReaderService) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    screen = StorageAdminScreen(service)
    screen.do_delete(story_id)
    assert service.stories.get(story_id) is None


@pytest.mark.asyncio
async def test_every_screen_mounts_without_error(populated: ReaderService) -> None:
    app = RedditReaderApp(populated)
    async with app.run_test() as pilot:
        app.push_screen(BrowseScreen(populated))
        await pilot.pause()
        app.pop_screen()
        app.push_screen(SearchScreen(populated))
        await pilot.pause()
        app.pop_screen()
        app.push_screen(StorageAdminScreen(populated))
        await pilot.pause()


# --- Item 2: Enter must actually run the search, not just call do_local_search -
#
# `Input` binds Enter to `submit` itself and consumes the keypress before the
# screen-level `Binding("enter", "search_local", ...)` ever fires. A test that
# calls `screen.do_local_search()` directly can't catch this — it has to press
# the key through a real Pilot session, on a mounted (and thus focused) input.


@pytest.mark.asyncio
async def test_pressing_enter_in_the_query_field_runs_a_search(populated: ReaderService) -> None:
    app = RedditReaderApp(populated)
    async with app.run_test() as pilot:
        app.push_screen(SearchScreen(populated))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SearchScreen)

        input_widget = screen.query_one("#query", Input)
        input_widget.focus()
        input_widget.value = "Long Road"
        await pilot.press("enter")

        assert screen.results
        assert screen.query_one("#results", DataTable).row_count == len(screen.results)


# --- Item 3: RedditError must be caught and shown, not left to crash the app --


@pytest.mark.asyncio
async def test_action_fetch_shows_a_status_message_instead_of_crashing(
    populated: ReaderService,
) -> None:
    def _boom() -> FetchResult:  # noqa: RUF100
        raise RedditFetchError("network down")

    app = RedditReaderApp(populated)
    async with app.run_test() as pilot:
        app.push_screen(BrowseScreen(populated))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, BrowseScreen)
        screen.do_fetch = _boom  # type: ignore[method-assign]

        screen.action_fetch()
        await pilot.pause()

        status_text = str(screen.query_one("#status", Static).content)
        assert "failed" in status_text.lower()


@pytest.mark.asyncio
async def test_live_search_shows_a_status_message_instead_of_crashing(
    populated: ReaderService,
) -> None:
    def _boom(query: str, subreddit: str | None = None) -> list[PostMeta]:
        raise RedditFetchError("rate limited")

    app = RedditReaderApp(populated)
    async with app.run_test() as pilot:
        app.push_screen(SearchScreen(populated))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SearchScreen)
        screen.do_live_search = _boom  # type: ignore[method-assign]

        screen.action_search_live()
        await pilot.pause()

        status_text = str(screen.query_one("#status", Static).content)
        assert "failed" in status_text.lower()
