from datetime import UTC, datetime

import pytest

from reddit_reader.reddit_client import (
    RedditClient,
    RedditFetchError,
    to_post_meta,
)
from tests.fakes import FakeAuthor, FakeReddit, FakeSubreddit, LazyFetchTrap, make_submission


@pytest.fixture
def client() -> RedditClient:
    reddit = FakeReddit(
        submissions=[
            make_submission("a1", "Road - Part 1", created_days=0),
            make_submission("a2", "Road - Part 2", created_days=7),
            make_submission("b1", "Other - Part 1", subreddit_name="WritingPrompts"),
            make_submission("c1", "Road - Part 3", author_name="SomeoneElse"),
        ]
    )
    return RedditClient(reddit)


def test_to_post_meta_converts_fields() -> None:
    sub = make_submission("a1", "Road - Part 1", score=42)
    meta = to_post_meta(sub)
    assert meta.id == "a1"
    assert meta.title == "Road - Part 1"
    assert meta.subreddit == "HFY"
    assert meta.author == "BlueFishcake"
    assert meta.score == 42
    assert meta.available is True


def test_to_post_meta_maps_missing_author_to_deleted() -> None:
    meta = to_post_meta(make_submission("a1", "Road", author_name=None))
    assert meta.author == "[deleted]"


def test_fetch_listing_filters_by_subreddit(client: RedditClient) -> None:
    posts = client.fetch_listing("HFY", "new", limit=10)
    assert {p.id for p in posts} == {"a1", "a2", "c1"}


def test_fetch_listing_respects_limit(client: RedditClient) -> None:
    assert len(client.fetch_listing("HFY", "new", limit=1)) == 1


def test_fetch_listing_top_accepts_time_window(client: RedditClient) -> None:
    posts = client.fetch_listing("HFY", "top", limit=10, time_window="year")
    assert posts


def test_search_matches_titles(client: RedditClient) -> None:
    assert {p.id for p in client.search("Road", subreddit="HFY")} == {"a1", "a2", "c1"}


def test_search_across_all_of_reddit(client: RedditClient) -> None:
    assert {p.id for p in client.search("Other")} == {"b1"}


def test_author_submissions_filters_by_author(client: RedditClient) -> None:
    assert {p.id for p in client.author_submissions("SomeoneElse")} == {"c1"}


def test_fetch_bodies_returns_text(client: RedditClient) -> None:
    bodies = client.fetch_bodies(["a1"])
    assert bodies[0].post_id == "a1"
    assert bodies[0].selftext == "Story text."


def test_fetch_bodies_skips_missing_posts(client: RedditClient) -> None:
    assert client.fetch_bodies(["nope"]) == []


def test_get_meta_by_id_returns_the_post(client: RedditClient) -> None:
    meta = client.get_meta_by_id("a1")
    assert meta is not None
    assert meta.id == "a1"
    assert meta.title == "Road - Part 1"


def test_get_meta_by_id_returns_none_for_missing_post(client: RedditClient) -> None:
    assert client.get_meta_by_id("nope") is None


def test_check_available_is_false_for_missing_post(client: RedditClient) -> None:
    assert client.check_available("nope") is False


def test_check_available_is_true_for_present_post(client: RedditClient) -> None:
    assert client.check_available("a1") is True


def test_fetch_listing_wraps_underlying_errors() -> None:
    class Exploding(FakeReddit):
        def subreddit(self, name: str) -> object:
            raise RuntimeError("network down")

    with pytest.raises(RedditFetchError):
        RedditClient(Exploding()).fetch_listing("HFY", "new", limit=5)


# --- Item 4: real PRAW submissions are lazy -----------------------------------
#
# `FakeReddit.submission()` never raises by itself (see tests/fakes.py); a
# missing/deleted post only fails on attribute access, matching real PRAW. These
# tests only pass if fetch_bodies/get_meta_by_id/check_available actually touch
# an attribute inside their `try` blocks, not just the constructor call.


def test_fetch_bodies_skips_a_post_that_fails_on_attribute_access(client: RedditClient) -> None:
    reddit = FakeReddit(missing_ids={"gone"})
    assert RedditClient(reddit).fetch_bodies(["gone"]) == []


def test_get_meta_by_id_returns_none_for_a_post_that_fails_on_attribute_access() -> None:
    reddit = FakeReddit(missing_ids={"gone"})
    assert RedditClient(reddit).get_meta_by_id("gone") is None


def test_check_available_forces_a_fetch_so_a_lazy_failure_is_caught() -> None:
    reddit = FakeReddit(missing_ids={"gone"})
    assert RedditClient(reddit).check_available("gone") is False


# --- Item 5: crosspost_parent must not trigger a lazy fetch, and is normalized -


def test_to_post_meta_does_not_trigger_a_fetch_to_read_crosspost_parent() -> None:
    """`crosspost_parent` is deliberately absent from this fake's `__dict__`.

    If `to_post_meta` used `getattr(submission, "crosspost_parent", None)`
    instead of reading `__dict__` directly, this would raise (see
    `LazyFetchTrap`) instead of returning `None`.
    """
    sub = LazyFetchTrap(
        id="a1",
        subreddit=FakeSubreddit(display_name="HFY"),
        author=FakeAuthor(name="BlueFishcake"),
        title="Road - Part 1",
        permalink="/r/HFY/comments/a1/x/",
        created_utc=datetime(2026, 1, 1, tzinfo=UTC).timestamp(),
        score=10,
    )
    meta = to_post_meta(sub)
    assert meta.crosspost_parent is None


def test_to_post_meta_strips_the_t3_prefix_from_crosspost_parent() -> None:
    sub = make_submission("b1", "Road - Part 1", crosspost_parent="t3_abc123")
    meta = to_post_meta(sub)
    assert meta.crosspost_parent == "abc123"
