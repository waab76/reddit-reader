from datetime import UTC, datetime
from pathlib import Path

import pytest

from reddit_reader.models import PostMeta
from reddit_reader.storage.db import connect
from reddit_reader.storage.search import SearchIndex


def make_post(post_id: str, title: str) -> PostMeta:
    return PostMeta(
        id=post_id,
        subreddit="HFY",
        author="BlueFishcake",
        title=title,
        permalink=f"/r/HFY/comments/{post_id}/x/",
        created_utc=datetime(2026, 1, 1, tzinfo=UTC),
        score=1,
    )


@pytest.fixture
def index(tmp_path: Path) -> SearchIndex:
    return SearchIndex(connect(tmp_path / "t.db"))


def test_title_search_finds_post(index: SearchIndex) -> None:
    index.index_title(make_post("a1", "The Long Road - Chapter 1"))
    assert index.search("Long Road") == ["a1"]


def test_bracket_tags_are_searchable(index: SearchIndex) -> None:
    index.index_title(make_post("a1", "[OC] The Long Road - Chapter 1"))
    assert index.search("OC") == ["a1"]


def test_search_misses_unrelated_titles(index: SearchIndex) -> None:
    index.index_title(make_post("a1", "The Long Road"))
    assert index.search("dragons") == []


def test_body_text_is_searchable_once_indexed(index: SearchIndex) -> None:
    index.index_title(make_post("a1", "The Long Road"))
    index.index_body("a1", "The xenobiologist blinked twice.")
    assert index.search("xenobiologist") == ["a1"]


def test_remove_body_drops_body_hits_but_keeps_title_hits(index: SearchIndex) -> None:
    index.index_title(make_post("a1", "The Long Road"))
    index.index_body("a1", "The xenobiologist blinked twice.")
    index.remove_body("a1")
    assert index.search("xenobiologist") == []
    assert index.search("Long Road") == ["a1"]


def test_remove_drops_the_post_entirely(index: SearchIndex) -> None:
    index.index_title(make_post("a1", "The Long Road"))
    index.remove("a1")
    assert index.search("Long Road") == []


def test_reindexing_a_title_does_not_duplicate_results(index: SearchIndex) -> None:
    post = make_post("a1", "The Long Road")
    index.index_title(post)
    index.index_title(post)
    assert index.search("Long Road") == ["a1"]
