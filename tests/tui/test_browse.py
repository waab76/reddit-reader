from pathlib import Path

from reddit_reader.config import Settings
from reddit_reader.reddit_client import RedditClient
from reddit_reader.service import ReaderService
from reddit_reader.storage import PostRepository, SearchIndex, StoryRepository, connect
from reddit_reader.tui.screens.browse import BrowseScreen
from tests.fakes import FakeReddit, make_submission


def _service_with_duplicates(tmp_path: Path) -> ReaderService:
    """Four copies of the same post mirrored across subreddits, all orphaned.

    `HFY` outranks `mirror` in `subreddits`, so collapse_duplicates should
    always pick the `HFY` copy as canonical regardless of creation order.
    """
    conn = connect(tmp_path / "t.db")
    reddit = FakeReddit(
        submissions=[
            make_submission("dup1", "A Story [Part 1]", subreddit_name="mirror", created_days=0),
            make_submission("dup2", "A Story [Part 1]", subreddit_name="mirror", created_days=0),
            make_submission("dup3", "A Story [Part 1]", subreddit_name="mirror", created_days=0),
            make_submission("canon", "A Story [Part 1]", subreddit_name="HFY", created_days=0),
        ]
    )
    return ReaderService(
        settings=Settings(subreddits=["HFY", "mirror"], export_dir=tmp_path / "out"),
        posts=PostRepository(conn),
        stories=StoryRepository(conn),
        search=SearchIndex(conn),
        client=RedditClient(reddit),
    )


def test_browse_hides_duplicate_copies(tmp_path: Path) -> None:
    service = _service_with_duplicates(tmp_path)
    service.fetch()

    screen = BrowseScreen(service)
    entries = screen._visible_entries()
    ids = {post_id for post_id, _ in entries}

    assert "canon" in ids
    assert "dup1" not in ids
    assert "dup2" not in ids
    assert "dup3" not in ids


def test_browse_still_shows_a_grouped_post_that_also_has_orphaned_mirrors(
    tmp_path: Path,
) -> None:
    """An already-attached story part must stay visible even though it's the
    "canonical" side of a dedupe cluster whose other copies are still
    orphaned — only the still-orphaned mirrors should be hidden."""
    service = _service_with_duplicates(tmp_path)
    for match in service.fetch().candidates:
        service.commit_match(match)

    screen = BrowseScreen(service)
    entries = screen._visible_entries()
    ids = {post_id for post_id, _ in entries}

    assert "canon" in ids
    assert "dup1" not in ids
    assert "dup2" not in ids
    assert "dup3" not in ids


def _service_with_mixed_posts(tmp_path: Path) -> ReaderService:
    conn = connect(tmp_path / "t.db")
    reddit = FakeReddit(
        submissions=[
            make_submission("p1", "Charlie's Tale", author_name="zeta", subreddit_name="HFY"),
            make_submission("p2", "Alpha's Tale", author_name="alpha", subreddit_name="mirror"),
            make_submission("p3", "Bravo's Tale", author_name="mu", subreddit_name="HFY"),
        ]
    )
    return ReaderService(
        settings=Settings(subreddits=["HFY", "mirror"], export_dir=tmp_path / "out"),
        posts=PostRepository(conn),
        stories=StoryRepository(conn),
        search=SearchIndex(conn),
        client=RedditClient(reddit),
    )


def test_sort_by_author(tmp_path: Path) -> None:
    service = _service_with_mixed_posts(tmp_path)
    service.fetch()

    screen = BrowseScreen(service)
    screen.set_sort("author")
    authors = [row[0] for row in screen.rows()]

    assert authors == sorted(authors)


def test_sort_by_title_reversed(tmp_path: Path) -> None:
    service = _service_with_mixed_posts(tmp_path)
    service.fetch()

    screen = BrowseScreen(service)
    screen.set_sort("title", reverse=True)
    titles = [row[2] for row in screen.rows()]

    assert titles == sorted(titles, reverse=True)


def test_set_sort_ignores_unknown_key(tmp_path: Path) -> None:
    """Guards against a typo silently landing the screen on a bogus sort."""
    service = _service_with_mixed_posts(tmp_path)
    service.fetch()

    screen = BrowseScreen(service)
    screen.set_sort("bogus")

    assert screen._sort == "none"


def test_reverse_sort_flag(tmp_path: Path) -> None:
    service = _service_with_mixed_posts(tmp_path)
    service.fetch()

    screen = BrowseScreen(service)
    screen.set_sort("author", reverse=True)
    authors = [row[0] for row in screen.rows()]

    assert authors == sorted(authors, reverse=True)
