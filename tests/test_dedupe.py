from datetime import UTC, datetime, timedelta

from reddit_reader.dedupe import collapse_duplicates
from reddit_reader.models import PostMeta

BASE = datetime(2026, 1, 1, tzinfo=UTC)
PRIORITY = ["HFY", "BlueFishcakeStories"]


def post(
    post_id: str,
    *,
    sub: str = "HFY",
    title: str = "The Long Road - Chapter 12",
    author: str = "BlueFishcake",
    hours: int = 0,
    crosspost_parent: str | None = None,
) -> PostMeta:
    return PostMeta(
        id=post_id,
        subreddit=sub,
        author=author,
        title=title,
        permalink=f"/r/{sub}/comments/{post_id}/x/",
        created_utc=BASE + timedelta(hours=hours),
        score=1,
        crosspost_parent=crosspost_parent,
    )


def test_unrelated_posts_are_not_collapsed() -> None:
    groups = collapse_duplicates(
        [post("a", title="Road - Chapter 1"), post("b", title="Road - Chapter 2")], PRIORITY
    )
    assert len(groups) == 2


def test_true_crosspost_is_collapsed() -> None:
    groups = collapse_duplicates(
        [post("a"), post("b", sub="BlueFishcakeStories", crosspost_parent="a")], PRIORITY
    )
    assert len(groups) == 1
    assert groups[0].canonical.id == "a"
    assert [p.id for p in groups[0].alternates] == ["b"]


def test_manual_mirror_is_collapsed_by_heuristic() -> None:
    groups = collapse_duplicates(
        [post("a"), post("b", sub="BlueFishcakeStories", hours=2)], PRIORITY
    )
    assert len(groups) == 1
    assert groups[0].canonical.id == "a"


def test_mirror_outside_the_time_window_is_not_collapsed() -> None:
    groups = collapse_duplicates(
        [post("a"), post("b", sub="BlueFishcakeStories", hours=500)], PRIORITY
    )
    assert len(groups) == 2


def test_different_authors_are_never_collapsed() -> None:
    groups = collapse_duplicates(
        [post("a"), post("b", sub="BlueFishcakeStories", author="SomeoneElse", hours=1)],
        PRIORITY,
    )
    assert len(groups) == 2


def test_canonical_follows_subreddit_priority_not_time() -> None:
    groups = collapse_duplicates(
        [post("b", sub="BlueFishcakeStories", hours=0), post("a", sub="HFY", hours=3)],
        PRIORITY,
    )
    assert groups[0].canonical.id == "a"


def test_canonical_is_earliest_within_the_same_subreddit() -> None:
    groups = collapse_duplicates([post("late", hours=5), post("early", hours=0)], PRIORITY)
    assert groups[0].canonical.id == "early"


def test_subreddit_outside_priority_list_ranks_last() -> None:
    groups = collapse_duplicates(
        [post("x", sub="SomewhereElse", hours=0), post("a", sub="HFY", hours=2)], PRIORITY
    )
    assert groups[0].canonical.id == "a"


def test_different_part_numbers_are_not_duplicates() -> None:
    groups = collapse_duplicates(
        [
            post("a", title="Road - Chapter 12"),
            post("b", sub="BlueFishcakeStories", title="Road - Chapter 13", hours=1),
        ],
        PRIORITY,
    )
    assert len(groups) == 2
