import pytest

from reddit_reader.service import ReaderService
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
    from reddit_reader.tui.app import RedditReaderApp

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
