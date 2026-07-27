import pytest

from reddit_reader.reddit_client import (
    RedditClient,
    RedditFetchError,
    to_post_meta,
)
from tests.fakes import FakeReddit, make_submission


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
