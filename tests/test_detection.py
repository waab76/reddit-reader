from datetime import UTC, datetime, timedelta

from reddit_reader.detection import DELETED_AUTHOR, group_posts, series_key
from reddit_reader.models import PostMeta

BASE = datetime(2026, 1, 1, tzinfo=UTC)
PRIORITY = ["HFY"]


def post(post_id: str, title: str, *, author: str = "BlueFishcake", days: int = 0) -> PostMeta:
    return PostMeta(
        id=post_id,
        subreddit="HFY",
        author=author,
        title=title,
        permalink=f"/r/HFY/comments/{post_id}/x/",
        created_utc=BASE + timedelta(days=days),
        score=1,
    )


def test_series_key_is_author_and_title_normalized() -> None:
    assert series_key("BlueFishcake", "the long road") == "bluefishcake:the long road"


def test_posts_of_one_serial_group_together() -> None:
    matches = group_posts(
        [
            post("a", "The Long Road - Part 1", days=0),
            post("b", "The Long Road - Part 2", days=7),
        ],
        PRIORITY,
    )
    assert len(matches) == 1
    assert set(matches[0].post_ids) == {"a", "b"}


def test_different_authors_do_not_group() -> None:
    matches = group_posts(
        [
            post("a", "The Long Road - Part 1"),
            post("b", "The Long Road - Part 2", author="SomeoneElse", days=7),
        ],
        PRIORITY,
    )
    assert len(matches) == 2


def test_different_volumes_do_not_group() -> None:
    matches = group_posts(
        [
            post("a", "The Long Road, Book One, Chapter 1", days=0),
            post("b", "The Long Road, Book Two, Chapter 1", days=7),
        ],
        PRIORITY,
    )
    assert len(matches) == 2
    assert {m.volume for m in matches} == {1, 2}


def test_deleted_author_posts_never_group_with_each_other() -> None:
    matches = group_posts(
        [
            post("a", "The Long Road - Part 1", author=DELETED_AUTHOR, days=0),
            post("b", "The Long Road - Part 2", author=DELETED_AUTHOR, days=7),
        ],
        PRIORITY,
    )
    assert len(matches) == 2


def test_clean_sequence_scores_higher_than_ragged_one() -> None:
    clean = group_posts(
        [
            post("a", "The Long Road - Part 1", days=0),
            post("b", "The Long Road - Part 2", days=7),
            post("c", "The Long Road - Part 3", days=14),
        ],
        PRIORITY,
    )[0]
    ragged = group_posts(
        [
            post("d", "The Short Road - Part 1", days=0),
            post("e", "The Short Road", days=400),
        ],
        PRIORITY,
    )[0]
    assert clean.confidence > ragged.confidence


def test_confidence_is_within_bounds() -> None:
    matches = group_posts(
        [post("a", "Road - Part 1"), post("b", "Road - Part 2", days=7)], PRIORITY
    )
    assert 0.0 <= matches[0].confidence <= 1.0


def test_match_carries_reasons() -> None:
    matches = group_posts(
        [post("a", "Road - Part 1"), post("b", "Road - Part 2", days=7)], PRIORITY
    )
    assert matches[0].reasons


def test_mirrored_duplicates_count_once() -> None:
    mirror = post("b", "The Long Road - Part 1", days=0)
    mirror = mirror.model_copy(update={"subreddit": "Mirror"})
    matches = group_posts([post("a", "The Long Road - Part 1", days=0), mirror], PRIORITY)
    assert len(matches) == 1
    assert matches[0].post_ids == ["a"]


def test_single_post_still_produces_a_match() -> None:
    matches = group_posts([post("a", "The Long Road - Part 1")], PRIORITY)
    assert len(matches) == 1
    assert matches[0].post_ids == ["a"]


# --- Item 9: alternate (collapsed duplicate) ids must survive onto the match --


def test_alternates_are_recorded_on_the_canonical_post_id() -> None:
    mirror = post("b", "The Long Road - Part 1", days=0).model_copy(update={"subreddit": "Mirror"})
    matches = group_posts([post("a", "The Long Road - Part 1", days=0), mirror], PRIORITY)
    assert matches[0].post_ids == ["a"]
    assert matches[0].alternate_post_ids == {"a": ["b"]}


# --- Item 11: Settings.dedupe_window_hours must actually change grouping -----


def test_group_posts_respects_a_configured_dedupe_window() -> None:
    a = post("a", "The Long Road - Chapter 1", days=0)
    b = post("b", "The Long Road - Chapter 1", days=0).model_copy(
        update={"subreddit": "Mirror", "created_utc": a.created_utc + timedelta(hours=2)}
    )

    # Default window (48h): 2 hours apart collapses into one canonical post
    # with "b" recorded as an alternate.
    default_match = group_posts([a, b], ["HFY", "Mirror"])[0]
    assert default_match.post_ids == ["a"]
    assert default_match.alternate_post_ids.get("a") == ["b"]

    # A configured window narrower than the gap between them must stop the
    # collapse: both posts survive as separate canonical entries in one match.
    narrow_match = group_posts([a, b], ["HFY", "Mirror"], window_hours=1)[0]
    assert set(narrow_match.post_ids) == {"a", "b"}
    assert narrow_match.alternate_post_ids == {}
