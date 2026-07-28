"""Fakes standing in for PRAW so no test touches the network."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

BASE = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass
class FakeAuthor:
    name: str


@dataclass
class FakeSubreddit:
    display_name: str


@dataclass
class FakeSubmission:
    id: str
    title: str
    selftext: str = "Story text."
    subreddit_name: str = "HFY"
    author_name: str | None = "BlueFishcake"
    created_days: int = 0
    score: int = 100
    crosspost_parent: str | None = None

    @property
    def subreddit(self) -> FakeSubreddit:
        return FakeSubreddit(display_name=self.subreddit_name)

    @property
    def author(self) -> FakeAuthor | None:
        return FakeAuthor(name=self.author_name) if self.author_name else None

    @property
    def permalink(self) -> str:
        return f"/r/{self.subreddit_name}/comments/{self.id}/x/"

    @property
    def created_utc(self) -> float:
        return (BASE + timedelta(days=self.created_days)).timestamp()


def make_submission(post_id: str, title: str, **kwargs: object) -> FakeSubmission:
    return FakeSubmission(id=post_id, title=title, **kwargs)  # type: ignore[arg-type]


class FakeMissingSubmission:
    """Models a real PRAW submission for a gone/nonexistent post.

    Real PRAW submissions are lazy: `reddit.submission(id=...)` never raises by
    itself, only attribute access does (the HTTP call happens on first access
    to an un-cached attribute). `id` is always known immediately (it's what you
    constructed the object with), so it's a real attribute here too; anything
    else raises, exactly like a deleted/missing post would on first fetch.
    """

    def __init__(self, post_id: str) -> None:
        self.id = post_id

    def __getattr__(self, name: str) -> object:
        raise LookupError(f"submission {self.id!r} not found")


class LazyFetchTrap:
    """A submission-shaped object exposing only explicitly "populated" attributes.

    Models the listing-derived, not-yet-fetched submissions PRAW hands back from
    a subreddit listing: some fields (id, title, score, ...) are already present
    in `__dict__` from the listing JSON, but anything not explicitly populated
    raises if accessed, standing in for the lazy HTTP fetch a real un-cached
    attribute access would trigger. Used to prove conversion code reads only
    what's already there and never touches the network to do it.
    """

    def __init__(self, **populated: object) -> None:
        self.__dict__.update(populated)

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"accessing {name!r} would trigger a lazy PRAW fetch")


class FakeListing:
    def __init__(self, submissions: list[FakeSubmission]) -> None:
        self._submissions = submissions

    def new(self, limit: int | None = None) -> list[FakeSubmission]:
        return self._submissions[:limit]

    def hot(self, limit: int | None = None) -> list[FakeSubmission]:
        return self._submissions[:limit]

    def top(self, time_filter: str = "all", limit: int | None = None) -> list[FakeSubmission]:
        return self._submissions[:limit]

    def search(
        self, query: str, limit: int | None = None, **kwargs: object
    ) -> list[FakeSubmission]:
        hits = [s for s in self._submissions if query.lower() in s.title.lower()]
        return hits[:limit]


class FakeRedditor:
    def __init__(self, submissions: list[FakeSubmission]) -> None:
        self.submissions = FakeListing(submissions)


@dataclass
class FakeReddit:
    """Minimal stand-in for `praw.Reddit`."""

    submissions: list[FakeSubmission] = field(default_factory=list)
    missing_ids: set[str] = field(default_factory=set)

    def subreddit(self, name: str) -> FakeListing:
        if name == "all":
            return FakeListing(self.submissions)
        return FakeListing(
            [s for s in self.submissions if s.subreddit_name.lower() == name.lower()]
        )

    def redditor(self, name: str) -> FakeRedditor:
        return FakeRedditor([s for s in self.submissions if s.author_name == name])

    def submission(self, id: str) -> FakeSubmission | FakeMissingSubmission:  # noqa: A002
        """Mirrors PRAW's API: construction never fails, even for a missing post.

        Real PRAW submissions are lazy — `reddit.submission(id=...)` always
        succeeds; only a later attribute access triggers the fetch that can
        fail. Raising here immediately (the old behavior) let production code
        get away with only wrapping the constructor call in a `try`, which
        would silently break against the real API. Returning a
        `FakeMissingSubmission` instead defers the failure to attribute access,
        same as the real thing.
        """
        if id not in self.missing_ids:
            for candidate in self.submissions:
                if candidate.id == id:
                    return candidate
        return FakeMissingSubmission(id)
