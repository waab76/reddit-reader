import pytest

from reddit_reader.service import ReaderService
from reddit_reader.tui.app import RedditReaderApp
from reddit_reader.tui.screens.story_list import StoryListScreen


@pytest.mark.asyncio
async def test_app_starts_on_the_story_list(populated: ReaderService) -> None:
    app = RedditReaderApp(populated)
    async with app.run_test():
        assert isinstance(app.screen, StoryListScreen)


@pytest.mark.asyncio
async def test_story_list_shows_untracked_stories(populated: ReaderService) -> None:
    app = RedditReaderApp(populated)
    async with app.run_test():
        screen = app.screen
        assert isinstance(screen, StoryListScreen)
        assert len(screen.visible_stories()) == 2
        assert all(not s.tracked for s in screen.visible_stories())


@pytest.mark.asyncio
async def test_filter_by_tracked_state(populated: ReaderService) -> None:
    stories = populated.stories.all_stories()
    populated.track(stories[0].id)
    app = RedditReaderApp(populated)
    async with app.run_test():
        screen = app.screen
        assert isinstance(screen, StoryListScreen)
        screen.set_filter("tracked", "tracked")
        assert len(screen.visible_stories()) == 1


def test_sort_by_part_count(populated: ReaderService) -> None:
    screen = StoryListScreen(populated)
    screen.set_sort("parts")
    counts = [len(populated.stories.parts(s.id)) for s in screen.visible_stories()]
    assert counts == sorted(counts, reverse=True)


def test_sort_by_recency(populated: ReaderService) -> None:
    screen = StoryListScreen(populated)
    screen.set_sort("recent")
    assert screen.visible_stories()


def test_filter_by_read_state_unstarted(populated: ReaderService) -> None:
    screen = StoryListScreen(populated)
    screen.set_filter("read", "unstarted")
    assert len(screen.visible_stories()) == 2


def test_filter_by_read_state_in_progress(populated: ReaderService) -> None:
    story = populated.stories.all_stories()[0]
    populated.mark_read(story.id, populated.stories.part_post_ids(story.id)[0], 0.5)
    screen = StoryListScreen(populated)
    screen.set_filter("read", "in_progress")
    assert len(screen.visible_stories()) == 1


def test_filter_by_status(populated: ReaderService) -> None:
    populated.settings.stale_after_days = 1
    screen = StoryListScreen(populated)
    screen.set_filter("status", "stale")
    assert screen.visible_stories()


def test_clearing_a_filter_restores_everything(populated: ReaderService) -> None:
    screen = StoryListScreen(populated)
    screen.set_filter("tracked", "tracked")
    screen.set_filter("tracked", None)
    assert len(screen.visible_stories()) == 2


def test_volumes_of_one_serial_sort_together(populated: ReaderService) -> None:
    screen = StoryListScreen(populated)
    screen.set_sort("series")
    keys = [s.series_key for s in screen.visible_stories()]
    assert keys == sorted(keys)
