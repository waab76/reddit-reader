import pytest
from textual.widgets import DataTable

from reddit_reader.reddit_client import RedditFetchError
from reddit_reader.service import ReaderService
from reddit_reader.tui.app import RedditReaderApp
from reddit_reader.tui.screens.browse import BrowseScreen
from reddit_reader.tui.screens.preview import PreviewScreen
from reddit_reader.tui.screens.search import SearchScreen


def test_rendered_text_contains_the_body(service: ReaderService) -> None:
    service.fetch()
    screen = PreviewScreen(service, "a1")
    assert "Story text." in screen.rendered_text()


def test_heading_shows_title_and_author(service: ReaderService) -> None:
    service.fetch()
    screen = PreviewScreen(service, "a1")
    assert "The Long Road - Part 1" in screen.heading()
    assert "BlueFishcake" in screen.heading()


def test_rendered_text_caches_the_body_it_fetched(service: ReaderService) -> None:
    service.fetch()
    assert service.posts.get_body("a1") is None

    screen = PreviewScreen(service, "a1")
    screen.rendered_text()

    assert service.posts.get_body("a1") is not None


def test_rendered_text_reports_a_reddit_error_instead_of_raising(service: ReaderService) -> None:
    service.fetch()

    def _boom(post_id: str) -> None:
        raise RedditFetchError("rate limited")

    screen = PreviewScreen(service, "a1")
    screen.service.preview_body = _boom  # type: ignore[method-assign]

    assert "failed" in screen.rendered_text().lower()


@pytest.mark.asyncio
async def test_preview_screen_mounts_without_error(service: ReaderService) -> None:
    service.fetch()
    app = RedditReaderApp(service)
    async with app.run_test() as pilot:
        app.push_screen(PreviewScreen(service, "a1"))
        await pilot.pause()
        assert isinstance(app.screen, PreviewScreen)


@pytest.mark.asyncio
async def test_pressing_p_previews_a_browse_row(service: ReaderService) -> None:
    service.fetch()
    app = RedditReaderApp(service)
    async with app.run_test() as pilot:
        app.push_screen(BrowseScreen(service))
        await pilot.pause()
        app.screen.query_one("#posts", DataTable).focus()
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()

        assert isinstance(app.screen, PreviewScreen)


@pytest.mark.asyncio
async def test_pressing_p_previews_a_search_result(service: ReaderService) -> None:
    service.fetch()
    app = RedditReaderApp(service)
    async with app.run_test() as pilot:
        app.push_screen(SearchScreen(service))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SearchScreen)

        screen.do_local_search("Long Road")
        screen.refresh_rows()
        screen.query_one("#results", DataTable).focus()
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()

        assert isinstance(app.screen, PreviewScreen)
