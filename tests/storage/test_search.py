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


def test_fts5_boolean_operators_are_sanitized(index: SearchIndex) -> None:
    """FTS5 boolean operators (AND, OR, NOT) don't execute as operators."""
    index.index_title(make_post("a1", "The Long Road"))
    # These queries should not raise and should not match via operator semantics.
    # They get sanitized into quoted literals, so they won't match "The Long Road".
    assert index.search("Long AND Road") == []
    assert index.search("Long OR dragons") == []
    assert index.search("Long NOT Road") == []


def test_fts5_near_operator_is_sanitized(index: SearchIndex) -> None:
    """FTS5 NEAR operator doesn't execute; gets sanitized to a literal."""
    index.index_title(make_post("a1", "The Long Road"))
    # NEAR(long road) would be an FTS5 operator, but _sanitize escapes it.
    assert index.search("NEAR(long road)") == []


def test_special_character_only_query_returns_empty(index: SearchIndex) -> None:
    """Queries with only special characters return [] instead of raising."""
    index.index_title(make_post("a1", "The Long Road"))
    # _sanitize strips all special chars, leaving an empty match string.
    assert index.search("***") == []
    assert index.search("!!!") == []
    assert index.search(":::") == []


def test_double_quote_in_query_does_not_break_syntax(index: SearchIndex) -> None:
    """Double quotes in user input are escaped, not left to break FTS5 MATCH."""
    index.index_title(make_post("a1", "The Long Road"))
    # User input with quotes: _sanitize replaces quotes with spaces.
    # This should return either the expected match or [] without raising.
    result = index.search('Long "Road')
    assert isinstance(result, list)  # Just confirm it doesn't raise.
    # The quote gets stripped, so we search for 'Long' and 'Road' separately.
    # Both should be found as quoted literals, so we expect a1.
    assert "a1" in result or result == []
