import pytest

from reddit_reader.service import ReaderService
from reddit_reader.tui.screens.reader import ReaderScreen


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
