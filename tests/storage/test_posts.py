from datetime import UTC, datetime
from pathlib import Path

import pytest

from reddit_reader.models import PostBody, PostMeta
from reddit_reader.storage.db import connect
from reddit_reader.storage.posts import PostRepository


def make_post(post_id: str, *, author: str = "BlueFishcake", score: int = 10) -> PostMeta:
    return PostMeta(
        id=post_id,
        subreddit="HFY",
        author=author,
        title=f"The Long Road - Chapter {post_id}",
        permalink=f"/r/HFY/comments/{post_id}/x/",
        created_utc=datetime(2026, 1, 1, tzinfo=UTC),
        score=score,
    )


@pytest.fixture
def repo(tmp_path: Path) -> PostRepository:
    return PostRepository(connect(tmp_path / "t.db"))


def test_upsert_then_get_roundtrips(repo: PostRepository) -> None:
    post = make_post("a1")
    repo.upsert_meta(post)
    assert repo.get_meta("a1") == post


def test_get_meta_returns_none_when_absent(repo: PostRepository) -> None:
    assert repo.get_meta("nope") is None


def test_upsert_updates_mutable_fields(repo: PostRepository) -> None:
    repo.upsert_meta(make_post("a1", score=10))
    repo.upsert_meta(make_post("a1", score=99))
    got = repo.get_meta("a1")
    assert got is not None
    assert got.score == 99


def test_upsert_many_and_get_many(repo: PostRepository) -> None:
    repo.upsert_many([make_post("a1"), make_post("a2")])
    assert {p.id for p in repo.get_many(["a1", "a2", "missing"])} == {"a1", "a2"}


def test_by_author_filters(repo: PostRepository) -> None:
    repo.upsert_many([make_post("a1", author="X"), make_post("a2", author="Y")])
    assert [p.id for p in repo.by_author("X")] == ["a1"]


def test_body_roundtrips(repo: PostRepository) -> None:
    repo.upsert_meta(make_post("a1"))
    repo.set_body(PostBody(post_id="a1", selftext="Once upon a time."))
    body = repo.get_body("a1")
    assert body is not None
    assert body.selftext == "Once upon a time."


def test_delete_bodies_reports_count_and_leaves_meta(repo: PostRepository) -> None:
    repo.upsert_many([make_post("a1"), make_post("a2")])
    repo.set_body(PostBody(post_id="a1", selftext="x"))
    repo.set_body(PostBody(post_id="a2", selftext="y"))
    assert repo.delete_bodies(["a1", "a2"]) == 2
    assert repo.get_body("a1") is None
    assert repo.get_meta("a1") is not None


def test_mark_unavailable_clears_flag(repo: PostRepository) -> None:
    repo.upsert_meta(make_post("a1"))
    repo.mark_unavailable("a1")
    got = repo.get_meta("a1")
    assert got is not None
    assert got.available is False


def test_orphaned_ids_lists_posts_in_no_story(repo: PostRepository) -> None:
    repo.upsert_many([make_post("a1"), make_post("a2")])
    repo.conn.execute("INSERT INTO story (series_key, title, author) VALUES ('k', 't', 'a')")
    repo.conn.execute("INSERT INTO story_part (post_id, story_id) VALUES ('a1', 1)")
    repo.conn.commit()
    assert repo.orphaned_ids() == ["a2"]


def test_delete_meta_removes_rows(repo: PostRepository) -> None:
    repo.upsert_many([make_post("a1"), make_post("a2")])
    assert repo.delete_meta(["a1"]) == 1
    assert repo.get_meta("a1") is None
    assert repo.get_meta("a2") is not None
