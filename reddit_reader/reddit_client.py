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
        crosspost_parent=getattr(submission, "crosspost_parent", None),
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
        """Fetch bodies, silently skipping posts that have since disappeared."""
        bodies: list[PostBody] = []
        for post_id in post_ids:
            try:
                submission = self._reddit.submission(id=post_id)
            except Exception:  # noqa: BLE001 - a gone post is expected, not exceptional
                continue
            bodies.append(PostBody(post_id=post_id, selftext=submission.selftext))
        return bodies

    def get_meta_by_id(self, post_id: str) -> PostMeta | None:
        """Fetch one post's metadata directly by id. Returns None if it's gone."""
        try:
            submission = self._reddit.submission(id=post_id)
        except Exception:  # noqa: BLE001 - a gone post is expected, not exceptional
            return None
        return to_post_meta(submission)

    def check_available(self, post_id: str) -> bool:
        """Report whether a post still exists upstream."""
        try:
            self._reddit.submission(id=post_id)
        except Exception:  # noqa: BLE001
            return False
        return True
