"""PRAW wrapper. The only module that touches Reddit's API types.

Everything crossing out of here is a pydantic model, and every underlying
exception is re-raised as a typed error, so no other module needs to know
PRAW exists.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from reddit_reader.models import PostBody, PostMeta

ListingType = Literal["new", "hot", "top"]
TimeWindow = Literal["day", "week", "month", "year", "all"]

DELETED_AUTHOR = "[deleted]"


class RedditError(Exception):
    """Base class for every Reddit-side failure."""


class RedditAuthError(RedditError):
    """Credentials were rejected."""


class RedditFetchError(RedditError):
    """A listing, search, or submission fetch failed."""


def _crosspost_parent_id(submission: Any) -> str | None:
    """Read `crosspost_parent` without triggering a lazy fetch, and normalize it.

    `getattr(submission, "crosspost_parent", None)` on a listing-derived (not yet
    fetched) submission would trigger a full lazy-fetch HTTP request before
    raising `AttributeError` for the ~99% of posts that have no crosspost parent
    at all — turning one listing fetch into potentially hundreds of extra
    requests. Reading straight from `__dict__` only sees what PRAW already
    populated from the listing response, no fetch involved.

    Real Reddit's `crosspost_parent` is a fullname like `t3_abc123`, not a bare
    post id, so it's stripped here once at the boundary rather than downstream
    (e.g. `dedupe.py` compares crosspost_parent directly against bare ids).
    """
    raw = submission.__dict__.get("crosspost_parent")
    if not isinstance(raw, str):
        return None
    return raw[3:] if raw.startswith("t3_") else raw


def to_post_meta(submission: Any) -> PostMeta:
    """Convert a PRAW submission into a `PostMeta`. The single conversion boundary."""
    author = getattr(submission, "author", None)
    return PostMeta(
        id=submission.id,
        subreddit=submission.subreddit.display_name,
        author=author.name if author is not None else DELETED_AUTHOR,
        title=submission.title,
        permalink=submission.permalink,
        created_utc=datetime.fromtimestamp(submission.created_utc, tz=UTC),
        score=getattr(submission, "score", 0),
        crosspost_parent=_crosspost_parent_id(submission),
    )


class RedditClient:
    """Fetches listings, searches, author history, and bodies."""

    def __init__(self, reddit: Any) -> None:
        self._reddit = reddit

    def fetch_listing(
        self,
        subreddit: str,
        listing: ListingType,
        limit: int,
        time_window: TimeWindow = "all",
    ) -> list[PostMeta]:
        try:
            source = self._reddit.subreddit(subreddit)
            if listing == "top":
                submissions = source.top(time_filter=time_window, limit=limit)
            elif listing == "hot":
                submissions = source.hot(limit=limit)
            else:
                submissions = source.new(limit=limit)
            return [to_post_meta(s) for s in submissions]
        except RedditError:
            raise
        except Exception as exc:
            raise RedditFetchError(f"failed to fetch r/{subreddit} ({listing})") from exc

    def search(self, query: str, subreddit: str | None = None, limit: int = 50) -> list[PostMeta]:
        target = subreddit or "all"
        try:
            source = self._reddit.subreddit(target)
            return [to_post_meta(s) for s in source.search(query, limit=limit)]
        except Exception as exc:
            raise RedditFetchError(f"search failed in r/{target}") from exc

    def author_submissions(self, author: str, limit: int | None = None) -> list[PostMeta]:
        try:
            redditor = self._reddit.redditor(author)
            return [to_post_meta(s) for s in redditor.submissions.new(limit=limit)]
        except Exception as exc:
            raise RedditFetchError(f"failed to fetch history for u/{author}") from exc

    def fetch_bodies(self, post_ids: Sequence[str]) -> list[PostBody]:
        """Fetch bodies, silently skipping posts that have since disappeared.

        Real PRAW submissions are lazy: `reddit.submission(id=...)` never makes
        an HTTP call by itself, only attribute access does. So `selftext` must be
        read inside the same `try` as construction, or a deleted/missing post
        would raise here (uncaught) instead of being skipped as promised.
        """
        bodies: list[PostBody] = []
        for post_id in post_ids:
            try:
                submission = self._reddit.submission(id=post_id)
                selftext = submission.selftext
            except Exception:  # noqa: BLE001 - a gone post is expected, not exceptional
                continue
            bodies.append(PostBody(post_id=post_id, selftext=selftext))
        return bodies

    def get_meta_by_id(self, post_id: str) -> PostMeta | None:
        """Fetch one post's metadata directly by id. Returns None if it's gone.

        `to_post_meta` reads attributes, which is what actually triggers the
        lazy fetch for a real PRAW submission — it must stay inside the `try`.
        """
        try:
            submission = self._reddit.submission(id=post_id)
            return to_post_meta(submission)
        except Exception:  # noqa: BLE001 - a gone post is expected, not exceptional
            return None

    def check_available(self, post_id: str) -> bool:
        """Report whether a post still exists upstream.

        Constructing the submission object never touches the network for real
        PRAW; only attribute access does. Force that fetch here so a deleted
        post actually raises and gets caught, instead of this always reporting
        `True`.
        """
        try:
            submission = self._reddit.submission(id=post_id)
            _ = submission.title
        except Exception:  # noqa: BLE001
            return False
        return True
