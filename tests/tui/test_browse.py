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
