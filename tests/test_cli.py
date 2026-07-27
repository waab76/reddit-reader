from pathlib import Path

import pytest
from typer.testing import CliRunner

from reddit_reader.cli import app, resolve_story
from reddit_reader.config import Settings
from reddit_reader.reddit_client import RedditClient
from reddit_reader.service import ReaderService
from reddit_reader.storage import PostRepository, SearchIndex, StoryRepository, connect
from tests.fakes import FakeReddit, make_submission

runner = CliRunner()


@pytest.fixture
def service(tmp_path: Path) -> ReaderService:
    conn = connect(tmp_path / "t.db")
    return ReaderService(
        settings=Settings(subreddits=["HFY"], export_dir=tmp_path / "out"),
        posts=PostRepository(conn),
        stories=StoryRepository(conn),
        search=SearchIndex(conn),
        client=RedditClient(
            FakeReddit(submissions=[make_submission("a1", "The Long Road - Part 1")])
        ),
    )


def test_resolve_story_by_id(service: ReaderService) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    found = resolve_story(service, str(story_id))
    assert found is not None
    assert found.id == story_id


def test_resolve_story_by_slug(service: ReaderService) -> None:
    service.commit_match(service.fetch().candidates[0])
    found = resolve_story(service, "BlueFishcake/the long road")
    assert found is not None
    assert found.author == "BlueFishcake"


def test_resolve_story_slug_is_case_insensitive(service: ReaderService) -> None:
    service.commit_match(service.fetch().candidates[0])
    assert resolve_story(service, "bluefishcake/THE LONG ROAD") is not None


def test_resolve_story_returns_none_for_unknown(service: ReaderService) -> None:
    assert resolve_story(service, "999") is None


def test_help_lists_every_command() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("tui", "fetch", "list", "export"):
        assert command in result.stdout


def test_fetch_command_help_mentions_subreddits() -> None:
    result = runner.invoke(app, ["fetch", "--help"])
    assert result.exit_code == 0
    assert "subreddit" in result.stdout.lower()


def test_export_command_help_mentions_story() -> None:
    result = runner.invoke(app, ["export", "--help"])
    assert result.exit_code == 0
    assert "story" in result.stdout.lower()


def test_list_command_help_runs() -> None:
    assert runner.invoke(app, ["list", "--help"]).exit_code == 0
