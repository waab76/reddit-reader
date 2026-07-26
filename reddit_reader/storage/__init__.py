"""Persistence layer: SQLite repositories and the full-text index."""

from reddit_reader.storage.db import connect
from reddit_reader.storage.posts import PostRepository
from reddit_reader.storage.search import SearchIndex
from reddit_reader.storage.stories import StoryRepository

__all__ = ["PostRepository", "SearchIndex", "StoryRepository", "connect"]
