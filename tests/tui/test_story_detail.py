from decimal import Decimal

from reddit_reader.service import ReaderService
from reddit_reader.tui.screens.story_detail import StoryDetailScreen


def test_part_rows_list_every_part(populated: ReaderService, multi_part_story_id: int) -> None:
    screen = StoryDetailScreen(populated, multi_part_story_id)
    assert len(screen.part_rows()) == len(populated.stories.parts(multi_part_story_id))


def test_find_missing_is_disabled_for_a_complete_story(
    populated: ReaderService, multi_part_story_id: int
) -> None:
    screen = StoryDetailScreen(populated, multi_part_story_id)
    assert screen.can_find_missing() is False


def test_gap_summary_says_complete_when_there_are_no_gaps(
    populated: ReaderService, multi_part_story_id: int
) -> None:
    screen = StoryDetailScreen(populated, multi_part_story_id)
    assert "no gaps" in screen.gap_summary().lower()


def test_find_missing_is_enabled_when_a_gap_exists(
    populated: ReaderService, multi_part_story_id: int
) -> None:
    story_id = multi_part_story_id
    # Drop part 1 so the sequence starts at 2, creating a missing start.
    parts = populated.stories.parts(story_id)
    target = next(p for p in parts if p.part_number == Decimal("1"))
    populated.stories.conn.execute(
        "DELETE FROM story_part WHERE story_id = ? AND post_id = ?",
        (story_id, target.post_id),
    )
    populated.stories.conn.commit()
    screen = StoryDetailScreen(populated, story_id)
    assert screen.can_find_missing() is True
    assert "1" in screen.gap_summary()


def test_tracking_marks_the_story_tracked(
    populated: ReaderService, multi_part_story_id: int
) -> None:
    screen = StoryDetailScreen(populated, multi_part_story_id)
    screen.do_track()
    story = populated.stories.get(multi_part_story_id)
    assert story is not None
    assert story.tracked is True


def test_untracking_reverses_it(populated: ReaderService, multi_part_story_id: int) -> None:
    screen = StoryDetailScreen(populated, multi_part_story_id)
    screen.do_track()
    screen.do_untrack()
    story = populated.stories.get(multi_part_story_id)
    assert story is not None
    assert story.tracked is False


def test_export_returns_a_written_path(populated: ReaderService, multi_part_story_id: int) -> None:
    screen = StoryDetailScreen(populated, multi_part_story_id)
    screen.do_track()
    path = screen.do_export()
    assert path.exists()


def test_no_cleaning_rules_proposed_for_short_stories(
    populated: ReaderService, multi_part_story_id: int
) -> None:
    screen = StoryDetailScreen(populated, multi_part_story_id)
    screen.do_track()
    assert screen.pending_rules() == []


def test_part_rows_flag_newly_filled_parts(
    populated: ReaderService, multi_part_story_id: int
) -> None:
    story_id = multi_part_story_id
    parts = populated.stories.parts(story_id)
    populated.stories.conn.execute(
        "UPDATE story_part SET newly_filled = 1 WHERE story_id = ? AND post_id = ?",
        (story_id, parts[0].post_id),
    )
    populated.stories.conn.commit()
    screen = StoryDetailScreen(populated, story_id)
    assert any("new" in row[2].lower() for row in screen.part_rows())
