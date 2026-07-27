from decimal import Decimal
from pathlib import Path

import pytest

from reddit_reader.config import Settings
from reddit_reader.reddit_client import RedditClient
from reddit_reader.service import ReaderService
from reddit_reader.storage import PostRepository, SearchIndex, StoryRepository, connect
from tests.fakes import FakeReddit, make_submission


def build(tmp_path: Path, *submissions: object) -> ReaderService:
    conn = connect(tmp_path / "t.db")
    return ReaderService(
        settings=Settings(subreddits=["HFY"], export_dir=tmp_path / "out"),
        posts=PostRepository(conn),
        stories=StoryRepository(conn),
        search=SearchIndex(conn),
        client=RedditClient(FakeReddit(submissions=list(submissions))),  # type: ignore[arg-type]
    )


@pytest.fixture
def gapped(tmp_path: Path) -> ReaderService:
    return build(
        tmp_path,
        make_submission("a1", "Road - Part 1", created_days=0),
        make_submission("a3", "Road - Part 3", created_days=14),
    )


def test_gaps_reports_the_missing_number(gapped: ReaderService) -> None:
    story_id = gapped.commit_match(gapped.fetch().candidates[0])
    assert gapped.gaps(story_id) == [Decimal("2")]


def test_marking_unavailable_suppresses_the_gap(gapped: ReaderService) -> None:
    story_id = gapped.commit_match(gapped.fetch().candidates[0])
    gapped.mark_unavailable(story_id, Decimal("2"))
    assert gapped.gaps(story_id) == []


def test_clearing_the_mark_restores_the_gap(gapped: ReaderService) -> None:
    story_id = gapped.commit_match(gapped.fetch().candidates[0])
    gapped.mark_unavailable(story_id, Decimal("2"))
    gapped.clear_unavailable(story_id, Decimal("2"))
    assert gapped.gaps(story_id) == [Decimal("2")]


def test_find_missing_parts_recovers_a_part_from_author_history(tmp_path: Path) -> None:
    service = build(
        tmp_path,
        make_submission("a1", "Road - Part 1", created_days=0),
        make_submission("a3", "Road - Part 3", created_days=14),
    )
    story_id = service.commit_match(service.fetch().candidates[0])
    # Part 2 exists on Reddit but was outside the fetch window.
    service.client._reddit.submissions.append(  # type: ignore[attr-defined]
        make_submission("a2", "Road - Part 2", created_days=7)
    )
    matches = service.find_missing_parts(story_id)
    assert any("a2" in m.post_ids for m in matches)


def test_failed_backfill_auto_marks_the_gap_unavailable(gapped: ReaderService) -> None:
    story_id = gapped.commit_match(gapped.fetch().candidates[0])
    gapped.find_missing_parts(story_id)
    assert gapped.gaps(story_id) == []


def test_export_story_writes_a_markdown_file(tmp_path: Path) -> None:
    service = build(tmp_path, make_submission("a1", "Road - Part 1"))
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)
    path = service.export_story(story_id)
    assert path.exists()
    assert path.read_text().startswith("# ")


def test_export_records_the_path_on_the_story(tmp_path: Path) -> None:
    service = build(tmp_path, make_submission("a1", "Road - Part 1"))
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)
    path = service.export_story(story_id)
    story = service.stories.get(story_id)
    assert story is not None
    assert story.exported_markdown_path == str(path)
    assert story.exported_at is not None


def test_reexport_overwrites_the_same_file(tmp_path: Path) -> None:
    service = build(tmp_path, make_submission("a1", "Road - Part 1"))
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)
    first = service.export_story(story_id)
    second = service.export_story(story_id)
    assert first == second


def test_export_links_writes_a_links_file(tmp_path: Path) -> None:
    service = build(tmp_path, make_submission("a1", "Road - Part 1"))
    story_id = service.commit_match(service.fetch().candidates[0])
    path = service.export_links_file(story_id)
    assert "reddit.com" in path.read_text()


def test_search_local_finds_cached_titles(tmp_path: Path) -> None:
    service = build(tmp_path, make_submission("a1", "The Long Road - Part 1"))
    service.fetch()
    assert [p.id for p in service.search_local("Long Road")] == ["a1"]


def test_search_live_returns_and_caches_results(tmp_path: Path) -> None:
    service = build(tmp_path, make_submission("a1", "The Long Road - Part 1"))
    found = service.search_live("Long Road", subreddit="HFY")
    assert [p.id for p in found] == ["a1"]
    assert service.posts.get_meta("a1") is not None


def test_delete_story_removes_it_but_keeps_post_metadata(tmp_path: Path) -> None:
    service = build(tmp_path, make_submission("a1", "Road - Part 1"))
    story_id = service.commit_match(service.fetch().candidates[0])
    service.delete_story(story_id)
    assert service.stories.get(story_id) is None
    assert service.posts.get_meta("a1") is not None


def test_prune_orphans_clears_ungrouped_metadata(tmp_path: Path) -> None:
    service = build(
        tmp_path,
        make_submission("a1", "Road - Part 1"),
        make_submission("z9", "Unrelated one-shot", created_days=1),
    )
    result = service.fetch()
    match = next(m for m in result.candidates if "a1" in m.post_ids)
    service.commit_match(match)
    assert service.prune_orphans() == 1
    assert service.posts.get_meta("z9") is None
    assert service.posts.get_meta("a1") is not None


def test_storage_usage_reports_counts(tmp_path: Path) -> None:
    service = build(tmp_path, make_submission("a1", "Road - Part 1"))
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)
    usage = service.storage_usage()
    assert usage.post_count == 1
    assert usage.body_count == 1
    assert usage.total_bytes > 0


def test_propose_cleaning_rules_needs_enough_parts(tmp_path: Path) -> None:
    service = build(tmp_path, make_submission("a1", "Road - Part 1"))
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)
    assert service.propose_cleaning_rules(story_id) == []
