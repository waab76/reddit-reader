from pathlib import Path

import pytest

from reddit_reader.config import Settings
from reddit_reader.reddit_client import RedditClient
from reddit_reader.service import ReaderService
from reddit_reader.storage import PostRepository, SearchIndex, StoryRepository, connect
from reddit_reader.tui.app import RedditReaderApp
from reddit_reader.tui.screens.reader import ReaderScreen
from tests.fakes import FakeReddit, make_submission


@pytest.fixture
def tracked_story(populated: ReaderService, multi_part_story_id: int) -> int:
    """The multi-part serial, tracked so its bodies are cached."""
    populated.track(multi_part_story_id)
    return multi_part_story_id


def test_reader_starts_at_the_first_part_when_nothing_read(
    populated: ReaderService, tracked_story: int
) -> None:
    screen = ReaderScreen(populated, tracked_story)
    assert screen.part_index == 0


def test_reader_resumes_from_the_saved_position(
    populated: ReaderService, tracked_story: int
) -> None:
    story_id = tracked_story
    second = populated.ordered_parts(story_id)[1].post.id
    populated.mark_read(story_id, second, 0.5)
    screen = ReaderScreen(populated, story_id)
    assert screen.part_index == 1


def test_rendered_text_contains_the_body(populated: ReaderService, tracked_story: int) -> None:
    screen = ReaderScreen(populated, tracked_story)
    assert "Story text." in screen.rendered_text()


def test_heading_names_the_part(populated: ReaderService, tracked_story: int) -> None:
    screen = ReaderScreen(populated, tracked_story)
    assert "Part 1" in screen.heading()


def test_next_part_advances(populated: ReaderService, tracked_story: int) -> None:
    screen = ReaderScreen(populated, tracked_story)
    assert screen.next_part() is True
    assert screen.part_index == 1


def test_next_part_stops_at_the_end(populated: ReaderService, tracked_story: int) -> None:
    screen = ReaderScreen(populated, tracked_story)
    total = len(populated.ordered_groups(tracked_story))
    screen.jump_to(total - 1)
    assert screen.next_part() is False


def test_previous_part_goes_back(populated: ReaderService, tracked_story: int) -> None:
    screen = ReaderScreen(populated, tracked_story)
    screen.next_part()
    assert screen.previous_part() is True
    assert screen.part_index == 0


def test_previous_part_stops_at_the_start(populated: ReaderService, tracked_story: int) -> None:
    screen = ReaderScreen(populated, tracked_story)
    assert screen.previous_part() is False


def test_advancing_saves_the_read_position(populated: ReaderService, tracked_story: int) -> None:
    screen = ReaderScreen(populated, tracked_story)
    screen.next_part()
    story = populated.stories.get(tracked_story)
    assert story is not None
    assert story.last_read_part == populated.ordered_parts(tracked_story)[1].post.id


def test_save_position_records_the_offset(populated: ReaderService, tracked_story: int) -> None:
    screen = ReaderScreen(populated, tracked_story)
    screen.save_position(0.75)
    story = populated.stories.get(tracked_story)
    assert story is not None
    assert story.last_read_offset == 0.75


def test_spoilers_are_concealed_until_toggled(populated: ReaderService, tracked_story: int) -> None:
    story_id = tracked_story
    post_id = populated.ordered_parts(story_id)[0].post.id
    from reddit_reader.models import PostBody

    populated.posts.set_body(
        PostBody(post_id=post_id, selftext="She was >!the traitor!< all along.")
    )
    screen = ReaderScreen(populated, story_id)
    assert "the traitor" not in screen.rendered_text()
    screen.toggle_spoilers()
    assert "the traitor" in screen.rendered_text()


def test_jumping_to_a_part_updates_the_index(populated: ReaderService, tracked_story: int) -> None:
    screen = ReaderScreen(populated, tracked_story)
    screen.jump_to(1)
    assert screen.part_index == 1


# --- Item 6: round part numbers must never render as scientific notation -----


def test_heading_renders_round_part_numbers_without_scientific_notation(tmp_path: Path) -> None:
    conn = connect(tmp_path / "round.db")
    service = ReaderService(
        settings=Settings(subreddits=["HFY"], export_dir=tmp_path / "out"),
        posts=PostRepository(conn),
        stories=StoryRepository(conn),
        search=SearchIndex(conn),
        client=RedditClient(FakeReddit(submissions=[make_submission("p100", "Road - Part 100")])),
    )
    story_id = service.commit_match(service.fetch().candidates[0])
    screen = ReaderScreen(service, story_id)
    assert screen.heading() == "Part 100"
    assert "E+" not in screen.heading()


# --- Item 10: resuming a story must restore the saved fractional offset ------


@pytest.mark.asyncio
async def test_resuming_a_story_restores_the_saved_scroll_offset(
    populated: ReaderService, tracked_story: int
) -> None:
    from textual.containers import VerticalScroll

    story_id = tracked_story
    # A long body so there's real scroll height to restore a fraction of.
    from reddit_reader.models import PostBody

    first_post_id = populated.ordered_parts(story_id)[0].post.id
    populated.posts.set_body(
        PostBody(post_id=first_post_id, selftext="\n\n".join(f"Paragraph {n}." for n in range(200)))
    )
    populated.mark_read(story_id, first_post_id, 0.6)

    app = RedditReaderApp(populated)
    async with app.run_test() as pilot:
        screen = ReaderScreen(populated, story_id)
        app.push_screen(screen)
        await pilot.pause()
        await pilot.pause()  # let call_after_refresh's scheduled callback run

        scroll = screen.query_one("#body-scroll", VerticalScroll)
        maximum = max(scroll.max_scroll_y, 1)
        assert maximum > 0
        assert scroll.scroll_y == pytest.approx(0.6 * maximum, abs=1.0)


# --- vim-style paging: space/b to page, g/G to jump to top/bottom -------------


@pytest.fixture
def long_body_screen_setup(populated: ReaderService, tracked_story: int):  # noqa: ANN201
    """A tracked story whose first part has enough text to actually scroll."""
    from reddit_reader.models import PostBody

    story_id = tracked_story
    first_post_id = populated.ordered_parts(story_id)[0].post.id
    populated.posts.set_body(
        PostBody(post_id=first_post_id, selftext="\n\n".join(f"Paragraph {n}." for n in range(200)))
    )
    return story_id


@pytest.mark.asyncio
async def test_pressing_capital_g_jumps_to_the_bottom(
    populated: ReaderService, long_body_screen_setup: int
) -> None:
    from textual.containers import VerticalScroll

    app = RedditReaderApp(populated)
    async with app.run_test() as pilot:
        screen = ReaderScreen(populated, long_body_screen_setup)
        app.push_screen(screen)
        await pilot.pause()
        await pilot.pause()

        scroll = screen.query_one("#body-scroll", VerticalScroll)
        assert scroll.max_scroll_y > 0

        await pilot.press("G")
        await pilot.pause()

        assert scroll.scroll_y == scroll.max_scroll_y


@pytest.mark.asyncio
async def test_pressing_lowercase_g_jumps_to_the_top(
    populated: ReaderService, long_body_screen_setup: int
) -> None:
    from textual.containers import VerticalScroll

    app = RedditReaderApp(populated)
    async with app.run_test() as pilot:
        screen = ReaderScreen(populated, long_body_screen_setup)
        app.push_screen(screen)
        await pilot.pause()
        await pilot.pause()

        scroll = screen.query_one("#body-scroll", VerticalScroll)
        await pilot.press("G")
        await pilot.pause()
        assert scroll.scroll_y > 0  # sanity: we actually moved off the top

        await pilot.press("g")
        await pilot.pause()

        assert scroll.scroll_y == 0


@pytest.mark.asyncio
async def test_pressing_space_pages_down(
    populated: ReaderService, long_body_screen_setup: int
) -> None:
    from textual.containers import VerticalScroll

    app = RedditReaderApp(populated)
    async with app.run_test() as pilot:
        screen = ReaderScreen(populated, long_body_screen_setup)
        app.push_screen(screen)
        await pilot.pause()
        await pilot.pause()

        scroll = screen.query_one("#body-scroll", VerticalScroll)
        assert scroll.scroll_y == 0

        await pilot.press("space")
        await pilot.pause()

        assert 0 < scroll.scroll_y <= scroll.max_scroll_y


@pytest.mark.asyncio
async def test_pressing_b_pages_up(populated: ReaderService, long_body_screen_setup: int) -> None:
    from textual.containers import VerticalScroll

    app = RedditReaderApp(populated)
    async with app.run_test() as pilot:
        screen = ReaderScreen(populated, long_body_screen_setup)
        app.push_screen(screen)
        await pilot.pause()
        await pilot.pause()

        scroll = screen.query_one("#body-scroll", VerticalScroll)
        await pilot.press("G")
        await pilot.pause()
        after_bottom = scroll.scroll_y
        assert after_bottom > 0

        await pilot.press("b")
        await pilot.pause()

        assert scroll.scroll_y < after_bottom
