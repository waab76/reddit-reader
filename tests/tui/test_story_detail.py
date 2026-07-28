from decimal import Decimal
from pathlib import Path

from reddit_reader.config import Settings
from reddit_reader.reddit_client import RedditClient
from reddit_reader.service import ReaderService
from reddit_reader.storage import PostRepository, SearchIndex, StoryRepository, connect
from reddit_reader.tui.screens.story_detail import StoryDetailScreen
from tests.fakes import FakeReddit, make_submission


def _build_service(tmp_path: Path, db_name: str, *submissions: object) -> ReaderService:
    conn = connect(tmp_path / db_name)
    return ReaderService(
        settings=Settings(subreddits=["HFY"], export_dir=tmp_path / "out"),
        posts=PostRepository(conn),
        stories=StoryRepository(conn),
        search=SearchIndex(conn),
        client=RedditClient(FakeReddit(submissions=list(submissions))),  # type: ignore[arg-type]
    )


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


# --- Item 6: round part numbers must never render as scientific notation -----


def test_part_rows_render_round_numbers_without_scientific_notation(tmp_path: Path) -> None:
    service = _build_service(tmp_path, "round.db", make_submission("p100", "Road - Part 100"))
    story_id = service.commit_match(service.fetch().candidates[0])
    screen = StoryDetailScreen(service, story_id)
    labels = [row[0] for row in screen.part_rows()]
    assert labels == ["Part 100"]
    assert not any("E+" in label for label in labels)


def test_gap_summary_renders_round_numbers_without_scientific_notation(tmp_path: Path) -> None:
    service = _build_service(
        tmp_path,
        "gap100.db",
        make_submission("p1", "Road - Part 1", created_days=0),
        make_submission("p101", "Road - Part 101", created_days=1),
    )
    story_id = service.commit_match(service.fetch().candidates[0])
    # Suppress every gap except the round number under test (100), so it's
    # guaranteed to survive the item-12 display truncation and appear in the
    # summary intact.
    for number in range(2, 100):
        service.mark_unavailable(story_id, Decimal(number), auto=True)
    screen = StoryDetailScreen(service, story_id)
    summary = screen.gap_summary()
    assert "100" in summary
    assert "E+" not in summary


# --- Item 12: the gap summary must be truncated, not one giant comma list ----


def test_gap_summary_truncates_long_gap_lists(tmp_path: Path) -> None:
    service = _build_service(
        tmp_path,
        "biggap.db",
        make_submission("p1", "Road - Part 1", created_days=0),
        make_submission("p50", "Road - Part 50", created_days=1),
    )
    story_id = service.commit_match(service.fetch().candidates[0])
    screen = StoryDetailScreen(service, story_id)
    summary = screen.gap_summary()
    assert "more" in summary
    assert summary.count(",") < 48
