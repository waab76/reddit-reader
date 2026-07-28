from pathlib import Path

import pytest

from reddit_reader.config import Settings
from reddit_reader.reddit_client import RedditClient
from reddit_reader.service import ReaderService
from reddit_reader.storage import PostRepository, SearchIndex, StoryRepository, connect
from tests.fakes import FakeReddit, make_submission


@pytest.fixture
def service(tmp_path: Path) -> ReaderService:
    conn = connect(tmp_path / "t.db")
    reddit = FakeReddit(
        submissions=[
            make_submission("a1", "The Long Road - Part 1", created_days=0),
            make_submission("a2", "The Long Road - Part 2", created_days=7),
            make_submission("b1", "Second Wind - Part 1", created_days=1),
        ]
    )
    return ReaderService(
        settings=Settings(subreddits=["HFY"], export_dir=tmp_path / "out"),
        posts=PostRepository(conn),
        stories=StoryRepository(conn),
        search=SearchIndex(conn),
        client=RedditClient(reddit),
    )


@pytest.fixture
def populated(service: ReaderService) -> ReaderService:
    for match in service.fetch().candidates:
        service.commit_match(match)
    return service


@pytest.fixture
def multi_part_story_id(populated: ReaderService) -> int:
    """The multi-part serial, not the one-shot.

    `all_stories()` sorts by series_key, so index 0 is "Second Wind" (one part)
    rather than "The Long Road" (two). Tests that need several parts must ask
    for this fixture instead of guessing an index.
    """
    return max(
        populated.stories.all_stories(),
        key=lambda s: len(populated.stories.parts(s.id)),
    ).id
