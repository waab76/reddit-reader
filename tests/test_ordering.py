from datetime import UTC, datetime, timedelta
from decimal import Decimal

from reddit_reader.models import PostMeta
from reddit_reader.ordering import group_segments, resolve_order
from reddit_reader.titles import parse_title

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def post(post_id: str, title: str, *, days: int = 0) -> PostMeta:
    return PostMeta(
        id=post_id,
        subreddit="HFY",
        author="BlueFishcake",
        title=title,
        permalink=f"/r/HFY/comments/{post_id}/x/",
        created_utc=BASE + timedelta(days=days),
        score=1,
    )


def ordered(*posts: PostMeta) -> list[str]:
    return [p.post.id for p in resolve_order([(p, parse_title(p.title)) for p in posts])]


def test_numbered_parts_sort_by_number_not_arrival() -> None:
    assert ordered(
        post("c", "Road - Part 3", days=0),
        post("a", "Road - Part 1", days=1),
        post("b", "Road - Part 2", days=2),
    ) == ["a", "b", "c"]


def test_decimal_part_sorts_between_whole_numbers() -> None:
    assert ordered(
        post("a", "Road - Part 4", days=0),
        post("c", "Road - Part 5", days=2),
        post("b", "Road - Part 4.5", days=1),
    ) == ["a", "b", "c"]


def test_named_part_follows_the_numbered_part_it_was_posted_after() -> None:
    assert ordered(
        post("a", "Road - Part 1", days=0),
        post("i", "Road - Interlude", days=1),
        post("b", "Road - Part 2", days=2),
    ) == ["a", "i", "b"]


def test_named_part_before_any_numbered_part_sorts_first() -> None:
    assert ordered(
        post("p", "Road - Prologue", days=0),
        post("a", "Road - Part 1", days=1),
    ) == ["p", "a"]


def test_two_named_parts_in_the_same_slot_keep_time_order() -> None:
    assert ordered(
        post("a", "Road - Part 1", days=0),
        post("i2", "Road - Intermission", days=2),
        post("i1", "Road - Interlude", days=1),
        post("b", "Road - Part 2", days=3),
    ) == ["a", "i1", "i2", "b"]


def test_entirely_unnumbered_story_falls_back_to_time_order() -> None:
    assert ordered(
        post("b", "Road - The Ending", days=1),
        post("a", "Road - The Beginning", days=0),
    ) == ["a", "b"]


def test_segments_stay_together_in_segment_order() -> None:
    result = ordered(
        post("b", "Road - Chapter 12 (2/2)", days=1),
        post("a", "Road - Chapter 12 (1/2)", days=0),
        post("c", "Road - Chapter 13", days=2),
    )
    assert result == ["a", "b", "c"]


def test_group_segments_merges_one_logical_part() -> None:
    parts = resolve_order(
        [
            (p, parse_title(p.title))
            for p in [
                post("a", "Road - Chapter 12 (1/2)", days=0),
                post("b", "Road - Chapter 12 (2/2)", days=1),
                post("c", "Road - Chapter 13", days=2),
            ]
        ]
    )
    groups = group_segments(parts)
    assert [[p.post.id for p in g] for g in groups] == [["a", "b"], ["c"]]


def test_group_segments_keeps_distinct_parts_separate() -> None:
    parts = resolve_order(
        [
            (p, parse_title(p.title))
            for p in [post("a", "Road - Part 1"), post("b", "Road - Part 2", days=1)]
        ]
    )
    assert [[p.post.id for p in g] for g in group_segments(parts)] == [["a"], ["b"]]


def test_sort_key_is_stable_and_sortable_as_text() -> None:
    parts = resolve_order(
        [
            (p, parse_title(p.title))
            for p in [post("a", "Road - Part 2", days=1), post("b", "Road - Part 10", days=0)]
        ]
    )
    keys = [p.sort_key for p in parts]
    assert keys == sorted(keys)
    assert parts[0].post.id == "a"


def test_anchor_of_named_part_matches_preceding_number() -> None:
    parts = resolve_order(
        [
            (p, parse_title(p.title))
            for p in [post("a", "Road - Part 7"), post("i", "Road - Interlude", days=1)]
        ]
    )
    interlude = next(p for p in parts if p.post.id == "i")
    assert interlude.anchor == Decimal("7")
    assert interlude.tiebreak == 1
