from decimal import Decimal
from pathlib import Path

import pytest

from reddit_reader.config import Settings
from reddit_reader.models import DetectionMatch
from reddit_reader.reddit_client import RedditClient, RedditFetchError
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


def test_find_missing_parts_recovers_a_part_linked_from_a_neighbor(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db")
    reddit = FakeReddit(
        submissions=[
            make_submission("a1", "Road - Part 1", created_days=0),
            make_submission(
                "a3",
                "Road - Part 3",
                created_days=14,
                selftext="Previously: https://www.reddit.com/r/HFY/comments/a2/x/",
            ),
        ],
        # Part 2 was deleted and re-hosted by the author under a fresh post,
        # so it never shows up in `author_submissions` — but it's still
        # fetchable directly, and Part 3 links straight to it.
        unlisted=[make_submission("a2", "Road - Part 2", created_days=7, author_name=None)],
    )
    service = ReaderService(
        settings=Settings(subreddits=["HFY"], export_dir=tmp_path / "out"),
        posts=PostRepository(conn),
        stories=StoryRepository(conn),
        search=SearchIndex(conn),
        client=RedditClient(reddit),
    )
    story_id = service.commit_match(service.fetch().candidates[0])
    assert service.gaps(story_id) == [Decimal("2")]

    matches = service.find_missing_parts(story_id)
    assert any("a2" in m.post_ids for m in matches)
    # Recovered via the link — must not be auto-marked unavailable.
    assert service.gaps(story_id) == [Decimal("2")]


def test_attach_parts_orders_an_unnumbered_part_after_existing_numbered_parts(
    tmp_path: Path,
) -> None:
    """A regression: an unnumbered part (interlude/epilogue/conclusion) attached
    after the fact used to be ordered against only its own match's posts, with
    no numbered sibling to anchor against — so it silently sorted before the
    entire story instead of wherever it chronologically belongs."""
    service = build(
        tmp_path,
        make_submission("a1", "Road - Part 1", created_days=0),
        make_submission("a2", "Road - Part 2", created_days=7),
    )
    story_id = service.commit_match(service.fetch().candidates[0])

    service.client._reddit.submissions.append(  # type: ignore[attr-defined]
        make_submission("a3", "Road - Epilogue", created_days=14)
    )
    meta = service.client.get_meta_by_id("a3")
    assert meta is not None
    service.posts.upsert_meta(meta)

    match = DetectionMatch(
        base_title="road",
        display_title="Road",
        author="BlueFishcake",
        volume=None,
        post_ids=["a3"],
        confidence=1.0,
        existing_story_id=story_id,
    )
    assert service.attach_parts(story_id, match) == 1

    parts = {p.post_id: p for p in service.stories.parts(story_id)}
    assert parts["a1"].sort_key is not None
    assert parts["a1"].sort_key < parts["a2"].sort_key < parts["a3"].sort_key


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


# --- Item 7: Settings.cleaning_enabled must actually reach the export path ---


def test_export_with_cleaning_disabled_keeps_pattern_matched_lines(tmp_path: Path) -> None:
    """`render_markdown` used to always call `clean()` with its default
    `strip_known_patterns=True`, ignoring `cleaning_enabled`. A Patreon-plug
    line should survive an export when cleaning is turned off, matching what
    the reader screen already does."""
    conn = connect(tmp_path / "t.db")
    service = ReaderService(
        settings=Settings(subreddits=["HFY"], export_dir=tmp_path / "out", cleaning_enabled=False),
        posts=PostRepository(conn),
        stories=StoryRepository(conn),
        search=SearchIndex(conn),
        client=RedditClient(FakeReddit(submissions=[make_submission("a1", "Road - Part 1")])),
    )
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)
    service.posts.set_body(
        __import__("reddit_reader.models", fromlist=["PostBody"]).PostBody(
            post_id="a1",
            selftext="Story text.\n\nSupport me on [Patreon](https://patreon.com/x)!",
        )
    )

    path = service.export_story(story_id)

    assert "patreon" in path.read_text().lower()


def test_export_with_cleaning_enabled_still_strips_known_patterns(tmp_path: Path) -> None:
    service = build(tmp_path, make_submission("a1", "Road - Part 1"))
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)
    service.posts.set_body(
        __import__("reddit_reader.models", fromlist=["PostBody"]).PostBody(
            post_id="a1",
            selftext="Story text.\n\nSupport me on [Patreon](https://patreon.com/x)!",
        )
    )

    path = service.export_story(story_id)

    assert "patreon" not in path.read_text().lower()


# --- Item 8: learned-rule proposal must align with what clean() actually sees -


def test_learned_rule_survives_a_leading_nav_line(tmp_path: Path) -> None:
    """`clean()` strips known patterns (nav links, plugs, sign-offs) BEFORE
    applying a learned rule, so a learned block has to be discovered against
    that same pattern-stripped text. `propose_cleaning_rules` used to run
    detection over the raw body instead, so a recurring header immediately
    following a nav-link line — the single most common real HFY boilerplate
    shape — would be learned as "nav line + header" and then never match the
    already-nav-stripped text `clean()` hands `apply_rules`, silently leaving
    the header in place."""
    from reddit_reader.cleaning import clean
    from reddit_reader.models import CleaningPosition, PostBody

    def body(chapter: int) -> str:
        return (
            "[First](https://redd.it/aaa) | [Prev](https://redd.it/bbb) | "
            "[Next](https://redd.it/ccc)\n"
            f"*The Long Road, Chapter {chapter}*\n"
            "A Blue Fishcake production.\n"
            "\n"
            f"Story content unique to chapter {chapter} goes here."
        )

    service = build(
        tmp_path,
        make_submission("a1", "Road - Part 1", created_days=0),
        make_submission("a2", "Road - Part 2", created_days=1),
        make_submission("a3", "Road - Part 3", created_days=2),
    )
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)
    for n, post_id in enumerate(service.stories.part_post_ids(story_id), start=1):
        service.posts.set_body(PostBody(post_id=post_id, selftext=body(n)))

    rules = service.propose_cleaning_rules(story_id)
    leading = next(r for r in rules if r.position == CleaningPosition.LEADING)
    leading.approved = True
    rule_id = service.stories.add_cleaning_rule(leading)
    service.stories.set_rule_decision(rule_id, True)

    cleaned = clean(body(1), service.stories.cleaning_rules(story_id))

    assert "Blue Fishcake production" not in cleaned
    assert "unique to chapter 1" in cleaned


# --- check_for_updates / check_all_for_updates --------------------------------


def test_check_for_updates_attaches_a_new_part_from_author_history(tmp_path: Path) -> None:
    service = build(tmp_path, make_submission("a1", "Road - Part 1", created_days=0))
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)

    service.client._reddit.submissions.append(  # type: ignore[attr-defined]
        make_submission("a2", "Road - Part 2", created_days=7)
    )
    result = service.check_for_updates(story_id)

    assert result.attached == 1
    assert "a2" in service.stories.part_post_ids(story_id)


def test_check_for_updates_caches_the_new_part_body(tmp_path: Path) -> None:
    """The new part is on a tracked story, so it should be cached immediately,
    the same as any other auto-attach."""
    service = build(tmp_path, make_submission("a1", "Road - Part 1", created_days=0))
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)

    service.client._reddit.submissions.append(  # type: ignore[attr-defined]
        make_submission("a2", "Road - Part 2", created_days=7)
    )
    service.check_for_updates(story_id)

    assert service.posts.get_body("a2") is not None


def test_check_for_updates_does_nothing_for_an_untracked_story(tmp_path: Path) -> None:
    service = build(tmp_path, make_submission("a1", "Road - Part 1", created_days=0))
    story_id = service.commit_match(service.fetch().candidates[0])

    service.client._reddit.submissions.append(  # type: ignore[attr-defined]
        make_submission("a2", "Road - Part 2", created_days=7)
    )
    result = service.check_for_updates(story_id)

    assert result.attached == 0
    assert "a2" not in service.stories.part_post_ids(story_id)


def test_check_for_updates_ignores_a_different_series_by_the_same_author(tmp_path: Path) -> None:
    service = build(tmp_path, make_submission("a1", "Road - Part 1", created_days=0))
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)

    service.client._reddit.submissions.append(  # type: ignore[attr-defined]
        make_submission("z1", "A Different Story - Part 1", created_days=7)
    )
    result = service.check_for_updates(story_id)

    assert result.attached == 0
    assert service.stories.parts(story_id).__len__() == 1


def test_check_for_updates_reexports_a_previously_exported_story(tmp_path: Path) -> None:
    service = build(tmp_path, make_submission("a1", "Road - Part 1", created_days=0))
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)
    path = service.export_story(story_id)
    before = path.read_text()

    service.client._reddit.submissions.append(  # type: ignore[attr-defined]
        make_submission("a2", "Road - Part 2", created_days=7)
    )
    service.check_for_updates(story_id)

    after = path.read_text()
    assert after != before
    assert "Part 2" in after


def test_check_for_updates_skips_reexport_when_nothing_new_attached(tmp_path: Path) -> None:
    service = build(tmp_path, make_submission("a1", "Road - Part 1", created_days=0))
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)
    service.export_story(story_id)
    story = service.stories.get(story_id)
    assert story is not None
    exported_at = story.exported_at

    service.check_for_updates(story_id)

    story = service.stories.get(story_id)
    assert story is not None
    assert story.exported_at == exported_at


def test_check_all_for_updates_only_checks_tracked_stories(tmp_path: Path) -> None:
    service = build(
        tmp_path,
        make_submission("a1", "Road - Part 1", created_days=0),
        make_submission("b1", "Other Tale - Part 1", created_days=0),
    )
    results = service.fetch()
    tracked_id = service.commit_match(next(m for m in results.candidates if "a1" in m.post_ids))
    service.commit_match(next(m for m in results.candidates if "b1" in m.post_ids))
    service.track(tracked_id)

    updates = service.check_all_for_updates()

    assert [r.story_id for r in updates] == [tracked_id]


def test_check_all_for_updates_skips_complete_stories(tmp_path: Path) -> None:
    service = build(
        tmp_path,
        make_submission("a1", "Road - Part 1 [Complete]", created_days=0),
    )
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)

    assert service.check_all_for_updates() == []


def test_check_all_for_updates_survives_one_author_lookup_failing(tmp_path: Path) -> None:
    service = build(
        tmp_path,
        make_submission("a1", "Road - Part 1", created_days=0),
        make_submission("b1", "Other Tale - Part 1", created_days=0, author_name="OtherAuthor"),
    )
    results = service.fetch()
    first_id = service.commit_match(next(m for m in results.candidates if "a1" in m.post_ids))
    second_id = service.commit_match(next(m for m in results.candidates if "b1" in m.post_ids))
    service.track(first_id)
    service.track(second_id)

    def _boom(author: str, limit: int | None = None) -> list[object]:
        if author == "BlueFishcake":
            raise RedditFetchError("rate limited")
        return []

    service.client.author_submissions = _boom  # type: ignore[method-assign]

    updates = service.check_all_for_updates()

    assert [r.story_id for r in updates] == [second_id]


# --- preview_body --------------------------------------------------------------


def test_preview_body_fetches_and_caches_an_uncommitted_post(tmp_path: Path) -> None:
    service = build(tmp_path, make_submission("a1", "Road - Part 1"))
    service.fetch()
    assert service.posts.get_body("a1") is None

    body = service.preview_body("a1")

    assert body is not None
    assert body.selftext == "Story text."
    assert service.posts.get_body("a1") is not None


def test_preview_body_reuses_an_already_cached_body(tmp_path: Path) -> None:
    from reddit_reader.models import PostBody

    service = build(tmp_path, make_submission("a1", "Road - Part 1"))
    service.fetch()
    service.posts.set_body(PostBody(post_id="a1", selftext="Edited cached text."))

    body = service.preview_body("a1")

    assert body is not None
    assert body.selftext == "Edited cached text."


def test_preview_body_is_none_for_a_gone_post(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db")
    reddit = FakeReddit(
        submissions=[make_submission("a1", "Road - Part 1")], missing_ids={"a1"}
    )
    service = ReaderService(
        settings=Settings(subreddits=["HFY"], export_dir=tmp_path / "out"),
        posts=PostRepository(conn),
        stories=StoryRepository(conn),
        search=SearchIndex(conn),
        client=RedditClient(reddit),
    )
    service.fetch()
    assert service.preview_body("a1") is None
