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

    def submission(self, id: str) -> FakeSubmission:  # noqa: A002 - mirrors PRAW's API
        if id in self.missing_ids:
            raise KeyError(id)
        for candidate in self.submissions:
            if candidate.id == id:
                return candidate
        raise KeyError(id)
