# reddit-reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an interactive TUI tool that finds multi-part serial fiction across Reddit subreddits, assembles the parts into ordered stories, and lets you read and export them.

**Architecture:** Layered modules communicating only through pydantic models. Pure logic (title parsing, ordering, grouping, gap detection, cleaning) has no I/O and is unit-tested directly. Storage is stdlib `sqlite3` behind a repository layer. PRAW is confined to one wrapper module that converts raw API objects into pydantic models at the boundary. The Textual TUI sits on top and knows nothing about how detection or storage work internally.

**Tech Stack:** Python 3.12, uv, pydantic 2.x, pydantic-settings, praw, typer, textual, text2num, pytest, ruff, mypy.

**Source spec:** `docs/superpowers/specs/2026-07-26-reddit-reader-design.md`

## Global Constraints

- Python 3.12+.
- `uv` for all environment/dependency management. `pyproject.toml` is the single source of truth for dependencies and metadata.
- `ruff` for both linting and formatting. `mypy` run in strict mode. Both must pass before every commit.
- `pydantic` for all data models and settings. Raw PRAW objects are converted into `PostMeta`/`PostBody` at the `reddit_client.py` boundary — nothing downstream touches PRAW types.
- **Raw text is never mutated in storage.** The raw post title and raw post body are stored verbatim; normalization and cleaning are applied at comparison/render time only.
- **Bodies are cached only for tracked stories.** `PostMeta` is stored for every post seen; `PostBody` only for posts belonging to a `Story` with `tracked = True`.
- Configuration precedence for every user-facing option: **CLI flags > config file > environment variables**.
- No background processes. All fetching and refreshing is an explicit user action.
- No real network calls in tests. PRAW is faked at the `reddit_client.py` boundary.

## File Structure

```
pyproject.toml                     # deps, tool config (ruff, mypy, pytest)
reddit_reader/
  __init__.py
  models.py                        # all pydantic models
  titles.py                        # title parsing: markers, numbers, volumes, brackets, segments
  ordering.py                      # sort keys, part sequencing, segment grouping
  detection.py                     # grouping, confidence scoring, gap detection, attach decisions
  dedupe.py                        # crosspost / mirrored-post collapsing
  navlinks.py                      # First/Prev/Next link parsing from bodies
  cleaning.py                      # pattern stripping + learned header/footer detection
  export.py                        # markdown story export + links export
  reddit_client.py                 # PRAW wrapper: listings, search, author history, typed errors
  config.py                        # pydantic-settings layering + praw.ini profile selection
  service.py                       # application operations binding storage + detection + client
  cli.py                           # typer entry point
  storage/
    __init__.py                    # public repository surface
    schema.py                      # DDL constants + migration runner
    db.py                          # connection management
    posts.py                       # PostMeta / PostBody repository
    stories.py                     # Story / StoryPart / UnavailablePart / CleaningRule repository
    search.py                      # FTS5 index management and queries
  tui/
    __init__.py
    app.py                         # Textual App, screen stack, key bindings
    markdown.py                    # reddit-flavoured markdown → display markdown
    screens/
      story_list.py
      story_detail.py
      reader.py
      browse.py
      search.py
      curation.py
      storage_admin.py
tests/
  test_titles.py
  test_ordering.py
  test_detection.py
  test_dedupe.py
  test_navlinks.py
  test_cleaning.py
  test_export.py
  test_reddit_client.py
  test_config.py
  test_cli.py
  storage/
    test_posts.py
    test_stories.py
    test_search.py
  tui/
    test_screens.py
  fakes.py                         # FakeReddit and fixture builders shared by tests
```

**Why this split:** title parsing is the single most rule-dense area of the spec, so it gets its own module and test file rather than living inside `detection.py`. Ordering (sort keys, segments) is separable pure logic with its own edge cases. Storage is a package because four distinct repositories plus schema and FTS management in one file would be unwieldy. Everything in the top level of `reddit_reader/` is I/O-free except `reddit_client.py`, `storage/`, `config.py`, and `cli.py`.

---

# Layer 0 — Scaffolding

### Task 1: Project scaffolding and tooling

**Files:**
- Create: `pyproject.toml`, `reddit_reader/__init__.py`, `tests/__init__.py`, `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces: an installed package `reddit_reader` importable in tests; `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy reddit_reader` all runnable.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "reddit-reader"
version = "0.1.0"
description = "Find, assemble, and read multi-part serial fiction from Reddit"
requires-python = ">=3.12"
dependencies = [
    "praw>=7.7",
    "pydantic>=2.6",
    "pydantic-settings>=2.2",
    "typer>=0.12",
    "textual>=0.60",
    "text2num>=2.5",
]

[project.scripts]
reddit-reader = "reddit_reader.cli:app"

[dependency-groups]
dev = [
    "pytest>=8.0",
    "ruff>=0.4",
    "mypy>=1.10",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "SIM", "RUF", "A", "BLE"]

[tool.mypy]
python_version = "3.12"
strict = true
warn_unreachable = true

[[tool.mypy.overrides]]
module = ["praw.*", "prawcore.*", "text2num.*"]
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create the package and test package markers**

Create `reddit_reader/__init__.py` containing:

```python
"""Find, assemble, and read multi-part serial fiction from Reddit."""

__version__ = "0.1.0"
```

Create an empty `tests/__init__.py`.

- [ ] **Step 3: Create `.gitignore`**

```gitignore
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
dist/
*.db
```

- [ ] **Step 4: Sync the environment and verify tooling runs**

Run:
```bash
uv sync
uv run ruff check .
uv run mypy reddit_reader
uv run pytest
```

Expected: `ruff` and `mypy` pass. `pytest` reports "no tests ran" (exit code 5) — that is correct at this point.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock reddit_reader/__init__.py tests/__init__.py .gitignore
git commit -m "chore: scaffold project with uv, ruff, mypy, pytest"
```

---

# Layer 1 — Models and Storage

**Checkpoint A** at the end of this layer: models exist, a SQLite database can be created, posts and stories can be written and read back, and full-text search works.

### Task 2: Pydantic models

**Files:**
- Create: `reddit_reader/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `PostMeta`, `PostBody`, `Story`, `StoryPart`, `UnavailablePart`, `CleaningRule`, `DetectionMatch`, and the enums `StoryStatus`, `CleaningPosition`. Every later task imports from here.

- [ ] **Step 1: Write the failing test**

Create `tests/test_models.py`:

```python
from datetime import UTC, datetime
from decimal import Decimal

from reddit_reader.models import (
    CleaningPosition,
    CleaningRule,
    DetectionMatch,
    PostBody,
    PostMeta,
    Story,
    StoryPart,
    StoryStatus,
    UnavailablePart,
)


def _post(post_id: str = "abc123") -> PostMeta:
    return PostMeta(
        id=post_id,
        subreddit="HFY",
        author="BlueFishcake",
        title="The Long Road - Chapter 12",
        permalink="/r/HFY/comments/abc123/the_long_road_chapter_12/",
        created_utc=datetime(2026, 1, 1, tzinfo=UTC),
        score=4200,
    )


def test_postmeta_defaults_to_available_with_no_crosspost() -> None:
    post = _post()
    assert post.available is True
    assert post.crosspost_parent is None


def test_postmeta_url_builds_absolute_permalink() -> None:
    assert _post().url == "https://reddit.com/r/HFY/comments/abc123/the_long_road_chapter_12/"


def test_postbody_holds_raw_text() -> None:
    body = PostBody(post_id="abc123", selftext="Once upon a time.")
    assert body.selftext == "Once upon a time."


def test_storypart_accepts_decimal_part_numbers() -> None:
    part = StoryPart(post_id="abc123", story_id=1, part_number=Decimal("4.5"))
    assert part.part_number == Decimal("4.5")


def test_storypart_defaults() -> None:
    part = StoryPart(post_id="abc123", story_id=1)
    assert part.part_number is None
    assert part.part_label is None
    assert part.segment is None
    assert part.newly_filled is False
    assert part.alternate_post_ids == []


def test_story_defaults_to_untracked_and_unread() -> None:
    story = Story(id=1, series_key="bluefishcake:the long road", title="The Long Road",
                  author="BlueFishcake")
    assert story.tracked is False
    assert story.volume is None
    assert story.last_read_part is None
    assert story.last_read_offset == 0.0


def test_unavailable_part_records_how_it_was_marked() -> None:
    rec = UnavailablePart(story_id=1, part_number=Decimal("4"), auto_marked=True)
    assert rec.auto_marked is True


def test_cleaning_rule_starts_undecided() -> None:
    rule = CleaningRule(
        story_id=1,
        position=CleaningPosition.LEADING,
        block="---\n[First] [Prev] [Next]\n---",
        seen_in_parts=9,
    )
    assert rule.approved is None


def test_detection_match_carries_confidence_and_reasons() -> None:
    match = DetectionMatch(
        base_title="the long road",
        author="BlueFishcake",
        volume=None,
        post_ids=["abc123", "def456"],
        confidence=0.91,
        reasons=["titles 98% similar", "part numbers ascend cleanly"],
    )
    assert match.confidence == 0.91
    assert match.reasons[0].startswith("titles")


def test_story_status_values() -> None:
    assert {s.value for s in StoryStatus} == {"complete", "ongoing", "stale"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'reddit_reader.models'`

- [ ] **Step 3: Write the implementation**

Create `reddit_reader/models.py`:

```python
"""Pydantic models shared across every layer of the application."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field

REDDIT_BASE_URL = "https://reddit.com"


class StoryStatus(str, Enum):
    """Derived completion state of a story."""

    COMPLETE = "complete"
    ONGOING = "ongoing"
    STALE = "stale"


class CleaningPosition(str, Enum):
    """Which end of a part a learned boilerplate block sits at."""

    LEADING = "leading"
    TRAILING = "trailing"


class PostMeta(BaseModel):
    """Lightweight post record, cached for every post the app has ever seen."""

    id: str
    subreddit: str
    author: str
    title: str
    permalink: str
    created_utc: datetime
    score: int
    crosspost_parent: str | None = None
    available: bool = True

    @property
    def url(self) -> str:
        return f"{REDDIT_BASE_URL}{self.permalink}"


class PostBody(BaseModel):
    """Raw post body, cached only for posts belonging to a tracked story."""

    post_id: str
    selftext: str


class StoryPart(BaseModel):
    """A post's membership in a story, with its resolved position."""

    post_id: str
    story_id: int
    part_number: Decimal | None = None
    part_label: str | None = None
    segment: int | None = None
    segment_count: int | None = None
    sort_key: str | None = None
    alternate_post_ids: list[str] = Field(default_factory=list)
    newly_filled: bool = False
    match_confidence: float = 0.0


class Story(BaseModel):
    """A committed series (one volume of one serial by one author)."""

    id: int
    series_key: str
    title: str
    author: str
    volume: int | None = None
    tracked: bool = False
    last_read_part: str | None = None
    last_read_offset: float = 0.0
    exported_markdown_path: str | None = None
    exported_at: datetime | None = None
    last_updated_at: datetime | None = None


class UnavailablePart(BaseModel):
    """A part number known to be unfillable, so gap detection stops reporting it."""

    story_id: int
    part_number: Decimal
    auto_marked: bool = False


class CleaningRule(BaseModel):
    """A learned per-story header/footer block and the user's decision about it."""

    story_id: int
    position: CleaningPosition
    block: str
    seen_in_parts: int
    approved: bool | None = None


class DetectionMatch(BaseModel):
    """A transient candidate grouping. Never persisted."""

    base_title: str
    author: str
    volume: int | None
    post_ids: list[str]
    confidence: float
    reasons: list[str] = Field(default_factory=list)
    existing_story_id: int | None = None
```

Note `last_read_part` is a `str` because it holds a `post_id` — a `StoryPart` reference, not a part number, so unnumbered parts remain resumable.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Verify lint and types**

Run:
```bash
uv run ruff check . && uv run ruff format . && uv run mypy reddit_reader
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add reddit_reader/models.py tests/test_models.py
git commit -m "feat: add pydantic models for posts, stories, and detection"
```

---

### Task 3: Database schema and connection management

**Files:**
- Create: `reddit_reader/storage/__init__.py`, `reddit_reader/storage/schema.py`, `reddit_reader/storage/db.py`
- Test: `tests/storage/__init__.py`, `tests/storage/test_db.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `connect(path: Path) -> sqlite3.Connection` which applies the schema on first use and returns a connection with foreign keys enabled and `Row` factory set. `SCHEMA_VERSION: int`.

- [ ] **Step 1: Write the failing test**

Create `tests/storage/__init__.py` (empty) and `tests/storage/test_db.py`:

```python
from pathlib import Path

from reddit_reader.storage.db import connect
from reddit_reader.storage.schema import SCHEMA_VERSION


def test_connect_creates_all_tables(tmp_path: Path) -> None:
    conn = connect(tmp_path / "test.db")
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    names = {row["name"] for row in rows}
    assert {
        "post_meta",
        "post_body",
        "story",
        "story_part",
        "unavailable_part",
        "cleaning_rule",
        "fetch_state",
    } <= names


def test_connect_records_schema_version(tmp_path: Path) -> None:
    conn = connect(tmp_path / "test.db")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == SCHEMA_VERSION


def test_connect_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    connect(path).close()
    conn = connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_foreign_keys_are_enforced(tmp_path: Path) -> None:
    conn = connect(tmp_path / "test.db")
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_rows_are_accessible_by_name(tmp_path: Path) -> None:
    conn = connect(tmp_path / "test.db")
    row = conn.execute("SELECT 1 AS answer").fetchone()
    assert row["answer"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/storage/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'reddit_reader.storage'`

- [ ] **Step 3: Write the schema**

Create `reddit_reader/storage/__init__.py` (empty for now) and `reddit_reader/storage/schema.py`:

```python
"""SQLite DDL and schema versioning."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 1

DDL = """
CREATE TABLE IF NOT EXISTS post_meta (
    id               TEXT PRIMARY KEY,
    subreddit        TEXT NOT NULL,
    author           TEXT NOT NULL,
    title            TEXT NOT NULL,
    permalink        TEXT NOT NULL,
    created_utc      TEXT NOT NULL,
    score            INTEGER NOT NULL,
    crosspost_parent TEXT,
    available        INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_post_meta_author ON post_meta (author);
CREATE INDEX IF NOT EXISTS idx_post_meta_subreddit ON post_meta (subreddit);

CREATE TABLE IF NOT EXISTS post_body (
    post_id  TEXT PRIMARY KEY REFERENCES post_meta (id) ON DELETE CASCADE,
    selftext TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS story (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    series_key             TEXT NOT NULL,
    title                  TEXT NOT NULL,
    author                 TEXT NOT NULL,
    volume                 INTEGER,
    tracked                INTEGER NOT NULL DEFAULT 0,
    last_read_part         TEXT,
    last_read_offset       REAL NOT NULL DEFAULT 0.0,
    exported_markdown_path TEXT,
    exported_at            TEXT,
    last_updated_at        TEXT
);

CREATE INDEX IF NOT EXISTS idx_story_series_key ON story (series_key);

CREATE TABLE IF NOT EXISTS story_part (
    post_id             TEXT NOT NULL REFERENCES post_meta (id) ON DELETE CASCADE,
    story_id            INTEGER NOT NULL REFERENCES story (id) ON DELETE CASCADE,
    part_number         TEXT,
    part_label          TEXT,
    segment             INTEGER,
    segment_count       INTEGER,
    sort_key            TEXT,
    alternate_post_ids  TEXT NOT NULL DEFAULT '',
    newly_filled        INTEGER NOT NULL DEFAULT 0,
    match_confidence    REAL NOT NULL DEFAULT 0.0,
    PRIMARY KEY (story_id, post_id)
);

CREATE TABLE IF NOT EXISTS unavailable_part (
    story_id    INTEGER NOT NULL REFERENCES story (id) ON DELETE CASCADE,
    part_number TEXT NOT NULL,
    auto_marked INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (story_id, part_number)
);

CREATE TABLE IF NOT EXISTS cleaning_rule (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id       INTEGER NOT NULL REFERENCES story (id) ON DELETE CASCADE,
    position       TEXT NOT NULL,
    block          TEXT NOT NULL,
    seen_in_parts  INTEGER NOT NULL,
    approved       INTEGER
);

CREATE TABLE IF NOT EXISTS fetch_state (
    subreddit    TEXT PRIMARY KEY,
    last_fetched TEXT,
    newest_seen  TEXT
);
"""


def apply_schema(conn: sqlite3.Connection) -> None:
    """Create every table if absent and stamp the schema version."""
    conn.executescript(DDL)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
```

- [ ] **Step 4: Write the connection module**

Create `reddit_reader/storage/db.py`:

```python
"""SQLite connection management."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from reddit_reader.storage.schema import apply_schema


def connect(path: Path) -> sqlite3.Connection:
    """Open (creating if needed) the database at `path` with the schema applied."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_schema(conn)
    return conn
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/storage/test_db.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add reddit_reader/storage tests/storage
git commit -m "feat: add SQLite schema and connection management"
```

---

### Task 4: Post repository

**Files:**
- Create: `reddit_reader/storage/posts.py`
- Test: `tests/storage/test_posts.py`

**Interfaces:**
- Consumes: `PostMeta`, `PostBody` from Task 2; `connect` from Task 3.
- Produces: `PostRepository` with methods `upsert_meta(post: PostMeta) -> None`, `upsert_many(posts: Iterable[PostMeta]) -> None`, `get_meta(post_id: str) -> PostMeta | None`, `get_many(post_ids: Sequence[str]) -> list[PostMeta]`, `by_author(author: str) -> list[PostMeta]`, `set_body(body: PostBody) -> None`, `get_body(post_id: str) -> PostBody | None`, `delete_bodies(post_ids: Sequence[str]) -> int`, `mark_unavailable(post_id: str) -> None`, `orphaned_ids() -> list[str]`, `delete_meta(post_ids: Sequence[str]) -> int`.

- [ ] **Step 1: Write the failing test**

Create `tests/storage/test_posts.py`:

```python
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
    repo.conn.execute(
        "INSERT INTO story (series_key, title, author) VALUES ('k', 't', 'a')"
    )
    repo.conn.execute("INSERT INTO story_part (post_id, story_id) VALUES ('a1', 1)")
    repo.conn.commit()
    assert repo.orphaned_ids() == ["a2"]


def test_delete_meta_removes_rows(repo: PostRepository) -> None:
    repo.upsert_many([make_post("a1"), make_post("a2")])
    assert repo.delete_meta(["a1"]) == 1
    assert repo.get_meta("a1") is None
    assert repo.get_meta("a2") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/storage/test_posts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'reddit_reader.storage.posts'`

- [ ] **Step 3: Write the implementation**

Create `reddit_reader/storage/posts.py`:

```python
"""Repository for post metadata and bodies."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from datetime import datetime

from reddit_reader.models import PostBody, PostMeta


def _row_to_meta(row: sqlite3.Row) -> PostMeta:
    return PostMeta(
        id=row["id"],
        subreddit=row["subreddit"],
        author=row["author"],
        title=row["title"],
        permalink=row["permalink"],
        created_utc=datetime.fromisoformat(row["created_utc"]),
        score=row["score"],
        crosspost_parent=row["crosspost_parent"],
        available=bool(row["available"]),
    )


class PostRepository:
    """Reads and writes `post_meta` and `post_body`."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert_meta(self, post: PostMeta) -> None:
        self.upsert_many([post])

    def upsert_many(self, posts: Iterable[PostMeta]) -> None:
        self.conn.executemany(
            """
            INSERT INTO post_meta
                (id, subreddit, author, title, permalink, created_utc, score,
                 crosspost_parent, available)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                title = excluded.title,
                score = excluded.score,
                crosspost_parent = excluded.crosspost_parent,
                available = excluded.available
            """,
            [
                (
                    p.id,
                    p.subreddit,
                    p.author,
                    p.title,
                    p.permalink,
                    p.created_utc.isoformat(),
                    p.score,
                    p.crosspost_parent,
                    int(p.available),
                )
                for p in posts
            ],
        )
        self.conn.commit()

    def get_meta(self, post_id: str) -> PostMeta | None:
        row = self.conn.execute("SELECT * FROM post_meta WHERE id = ?", (post_id,)).fetchone()
        return _row_to_meta(row) if row else None

    def get_many(self, post_ids: Sequence[str]) -> list[PostMeta]:
        if not post_ids:
            return []
        placeholders = ", ".join("?" * len(post_ids))
        rows = self.conn.execute(
            f"SELECT * FROM post_meta WHERE id IN ({placeholders})", tuple(post_ids)
        ).fetchall()
        return [_row_to_meta(row) for row in rows]

    def by_author(self, author: str) -> list[PostMeta]:
        rows = self.conn.execute(
            "SELECT * FROM post_meta WHERE author = ? ORDER BY created_utc", (author,)
        ).fetchall()
        return [_row_to_meta(row) for row in rows]

    def set_body(self, body: PostBody) -> None:
        self.conn.execute(
            """
            INSERT INTO post_body (post_id, selftext) VALUES (?, ?)
            ON CONFLICT (post_id) DO UPDATE SET selftext = excluded.selftext
            """,
            (body.post_id, body.selftext),
        )
        self.conn.commit()

    def get_body(self, post_id: str) -> PostBody | None:
        row = self.conn.execute(
            "SELECT * FROM post_body WHERE post_id = ?", (post_id,)
        ).fetchone()
        return PostBody(post_id=row["post_id"], selftext=row["selftext"]) if row else None

    def delete_bodies(self, post_ids: Sequence[str]) -> int:
        if not post_ids:
            return 0
        placeholders = ", ".join("?" * len(post_ids))
        cursor = self.conn.execute(
            f"DELETE FROM post_body WHERE post_id IN ({placeholders})", tuple(post_ids)
        )
        self.conn.commit()
        return cursor.rowcount

    def mark_unavailable(self, post_id: str) -> None:
        self.conn.execute("UPDATE post_meta SET available = 0 WHERE id = ?", (post_id,))
        self.conn.commit()

    def orphaned_ids(self) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT id FROM post_meta
            WHERE id NOT IN (SELECT post_id FROM story_part)
            ORDER BY id
            """
        ).fetchall()
        return [row["id"] for row in rows]

    def delete_meta(self, post_ids: Sequence[str]) -> int:
        if not post_ids:
            return 0
        placeholders = ", ".join("?" * len(post_ids))
        cursor = self.conn.execute(
            f"DELETE FROM post_meta WHERE id IN ({placeholders})", tuple(post_ids)
        )
        self.conn.commit()
        return cursor.rowcount
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/storage/test_posts.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Verify lint and types, then commit**

```bash
uv run ruff check . && uv run ruff format . && uv run mypy reddit_reader
git add reddit_reader/storage/posts.py tests/storage/test_posts.py
git commit -m "feat: add post repository with meta and body storage"
```

---

### Task 5: Full-text search index

**Files:**
- Create: `reddit_reader/storage/search.py`
- Modify: `reddit_reader/storage/schema.py` (add FTS5 table to `DDL`)
- Test: `tests/storage/test_search.py`

**Interfaces:**
- Consumes: `PostMeta`, `PostBody`, `PostRepository`.
- Produces: `SearchIndex` with `index_title(post: PostMeta) -> None`, `index_body(post_id: str, selftext: str) -> None`, `remove_body(post_id: str) -> None`, `remove(post_id: str) -> None`, `search(query: str, limit: int = 50) -> list[str]` returning post ids ranked by relevance.

The spec requires the index to follow body lifecycle in both directions: body text is added when a story is tracked and **removed** when untracking or deletion drops the `PostBody` rows, so search never returns hits for text no longer held.

- [ ] **Step 1: Add the FTS5 table to the schema**

Append to the `DDL` string in `reddit_reader/storage/schema.py`, before the closing `"""`:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS post_search USING fts5 (
    post_id UNINDEXED,
    title,
    body
);
```

- [ ] **Step 2: Write the failing test**

Create `tests/storage/test_search.py`:

```python
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reddit_reader.models import PostMeta
from reddit_reader.storage.db import connect
from reddit_reader.storage.search import SearchIndex


def make_post(post_id: str, title: str) -> PostMeta:
    return PostMeta(
        id=post_id,
        subreddit="HFY",
        author="BlueFishcake",
        title=title,
        permalink=f"/r/HFY/comments/{post_id}/x/",
        created_utc=datetime(2026, 1, 1, tzinfo=UTC),
        score=1,
    )


@pytest.fixture
def index(tmp_path: Path) -> SearchIndex:
    return SearchIndex(connect(tmp_path / "t.db"))


def test_title_search_finds_post(index: SearchIndex) -> None:
    index.index_title(make_post("a1", "The Long Road - Chapter 1"))
    assert index.search("Long Road") == ["a1"]


def test_bracket_tags_are_searchable(index: SearchIndex) -> None:
    index.index_title(make_post("a1", "[OC] The Long Road - Chapter 1"))
    assert index.search("OC") == ["a1"]


def test_search_misses_unrelated_titles(index: SearchIndex) -> None:
    index.index_title(make_post("a1", "The Long Road"))
    assert index.search("dragons") == []


def test_body_text_is_searchable_once_indexed(index: SearchIndex) -> None:
    index.index_title(make_post("a1", "The Long Road"))
    index.index_body("a1", "The xenobiologist blinked twice.")
    assert index.search("xenobiologist") == ["a1"]


def test_remove_body_drops_body_hits_but_keeps_title_hits(index: SearchIndex) -> None:
    index.index_title(make_post("a1", "The Long Road"))
    index.index_body("a1", "The xenobiologist blinked twice.")
    index.remove_body("a1")
    assert index.search("xenobiologist") == []
    assert index.search("Long Road") == ["a1"]


def test_remove_drops_the_post_entirely(index: SearchIndex) -> None:
    index.index_title(make_post("a1", "The Long Road"))
    index.remove("a1")
    assert index.search("Long Road") == []


def test_reindexing_a_title_does_not_duplicate_results(index: SearchIndex) -> None:
    post = make_post("a1", "The Long Road")
    index.index_title(post)
    index.index_title(post)
    assert index.search("Long Road") == ["a1"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/storage/test_search.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'reddit_reader.storage.search'`

- [ ] **Step 4: Write the implementation**

Create `reddit_reader/storage/search.py`:

```python
"""FTS5 full-text index over post titles and (for tracked stories) bodies."""

from __future__ import annotations

import re
import sqlite3

from reddit_reader.models import PostMeta

_FTS_SPECIAL = re.compile(r'[^\w\s]')


def _sanitize(query: str) -> str:
    """Strip FTS5 operators so user input can never be a malformed MATCH expression."""
    cleaned = _FTS_SPECIAL.sub(" ", query).strip()
    terms = [t for t in cleaned.split() if t]
    return " ".join(f'"{t}"' for t in terms)


class SearchIndex:
    """Maintains and queries the `post_search` FTS5 table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def _current_body(self, post_id: str) -> str:
        row = self.conn.execute(
            "SELECT body FROM post_search WHERE post_id = ?", (post_id,)
        ).fetchone()
        return row["body"] if row else ""

    def _write(self, post_id: str, title: str, body: str) -> None:
        self.conn.execute("DELETE FROM post_search WHERE post_id = ?", (post_id,))
        self.conn.execute(
            "INSERT INTO post_search (post_id, title, body) VALUES (?, ?, ?)",
            (post_id, title, body),
        )
        self.conn.commit()

    def _current_title(self, post_id: str) -> str:
        row = self.conn.execute(
            "SELECT title FROM post_search WHERE post_id = ?", (post_id,)
        ).fetchone()
        return row["title"] if row else ""

    def index_title(self, post: PostMeta) -> None:
        self._write(post.id, post.title, self._current_body(post.id))

    def index_body(self, post_id: str, selftext: str) -> None:
        self._write(post_id, self._current_title(post_id), selftext)

    def remove_body(self, post_id: str) -> None:
        self._write(post_id, self._current_title(post_id), "")

    def remove(self, post_id: str) -> None:
        self.conn.execute("DELETE FROM post_search WHERE post_id = ?", (post_id,))
        self.conn.commit()

    def search(self, query: str, limit: int = 50) -> list[str]:
        match = _sanitize(query)
        if not match:
            return []
        rows = self.conn.execute(
            """
            SELECT post_id FROM post_search
            WHERE post_search MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (match, limit),
        ).fetchall()
        return [row["post_id"] for row in rows]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/storage/test_search.py -v`
Expected: PASS (7 tests)

- [ ] **Step 6: Commit**

```bash
uv run ruff check . && uv run ruff format . && uv run mypy reddit_reader
git add reddit_reader/storage/search.py reddit_reader/storage/schema.py tests/storage/test_search.py
git commit -m "feat: add FTS5 search index with body lifecycle handling"
```

---

### Task 6: Story repository

**Files:**
- Create: `reddit_reader/storage/stories.py`
- Modify: `reddit_reader/storage/__init__.py`
- Test: `tests/storage/test_stories.py`

**Interfaces:**
- Consumes: `Story`, `StoryPart`, `UnavailablePart`, `CleaningRule`, `CleaningPosition`.
- Produces: `StoryRepository` with `create(story: Story) -> int`, `get(story_id: int) -> Story | None`, `all_stories() -> list[Story]`, `by_series_key(key: str) -> list[Story]`, `find_committed(series_key: str, volume: int | None) -> Story | None`, `update(story: Story) -> None`, `delete(story_id: int) -> None`, `add_part(part: StoryPart) -> None`, `parts(story_id: int) -> list[StoryPart]`, `part_post_ids(story_id: int) -> list[str]`, `clear_newly_filled(story_id: int, post_id: str) -> None`, `add_unavailable(rec: UnavailablePart) -> None`, `unavailable(story_id: int) -> list[UnavailablePart]`, `clear_unavailable(story_id: int, part_number: Decimal) -> None`, `add_cleaning_rule(rule: CleaningRule) -> int`, `cleaning_rules(story_id: int) -> list[CleaningRule]`, `set_rule_decision(rule_id: int, approved: bool) -> None`.
  Also `storage/__init__.py` re-exports `connect`, `PostRepository`, `SearchIndex`, `StoryRepository`.

- [ ] **Step 1: Write the failing test**

Create `tests/storage/test_stories.py`:

```python
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from reddit_reader.models import (
    CleaningPosition,
    CleaningRule,
    PostMeta,
    Story,
    StoryPart,
    UnavailablePart,
)
from reddit_reader.storage.db import connect
from reddit_reader.storage.posts import PostRepository
from reddit_reader.storage.stories import StoryRepository


@pytest.fixture
def repos(tmp_path: Path) -> tuple[StoryRepository, PostRepository]:
    conn = connect(tmp_path / "t.db")
    return StoryRepository(conn), PostRepository(conn)


def a_story(**kwargs: object) -> Story:
    base = {
        "id": 0,
        "series_key": "bluefishcake:the long road",
        "title": "The Long Road",
        "author": "BlueFishcake",
    }
    base.update(kwargs)
    return Story(**base)  # type: ignore[arg-type]


def a_post(post_id: str) -> PostMeta:
    return PostMeta(
        id=post_id,
        subreddit="HFY",
        author="BlueFishcake",
        title="The Long Road",
        permalink=f"/r/HFY/comments/{post_id}/x/",
        created_utc=datetime(2026, 1, 1, tzinfo=UTC),
        score=1,
    )


def test_create_assigns_an_id(repos: tuple[StoryRepository, PostRepository]) -> None:
    stories, _ = repos
    assert stories.create(a_story()) == 1


def test_get_roundtrips(repos: tuple[StoryRepository, PostRepository]) -> None:
    stories, _ = repos
    story_id = stories.create(a_story(volume=2, tracked=True))
    got = stories.get(story_id)
    assert got is not None
    assert got.volume == 2
    assert got.tracked is True


def test_find_committed_matches_on_series_key_and_volume(
    repos: tuple[StoryRepository, PostRepository],
) -> None:
    stories, _ = repos
    stories.create(a_story(volume=1))
    stories.create(a_story(volume=2))
    book_two = stories.find_committed("bluefishcake:the long road", 2)
    assert book_two is not None
    assert book_two.volume == 2


def test_find_committed_returns_none_for_unknown_volume(
    repos: tuple[StoryRepository, PostRepository],
) -> None:
    stories, _ = repos
    stories.create(a_story(volume=1))
    assert stories.find_committed("bluefishcake:the long road", 3) is None


def test_by_series_key_groups_volumes(
    repos: tuple[StoryRepository, PostRepository],
) -> None:
    stories, _ = repos
    stories.create(a_story(volume=1))
    stories.create(a_story(volume=2))
    assert [s.volume for s in stories.by_series_key("bluefishcake:the long road")] == [1, 2]


def test_update_persists_read_position(
    repos: tuple[StoryRepository, PostRepository],
) -> None:
    stories, _ = repos
    story_id = stories.create(a_story())
    story = stories.get(story_id)
    assert story is not None
    story.last_read_part = "a1"
    story.last_read_offset = 0.42
    stories.update(story)
    reloaded = stories.get(story_id)
    assert reloaded is not None
    assert reloaded.last_read_part == "a1"
    assert reloaded.last_read_offset == pytest.approx(0.42)


def test_add_part_and_read_back(repos: tuple[StoryRepository, PostRepository]) -> None:
    stories, posts = repos
    posts.upsert_meta(a_post("a1"))
    story_id = stories.create(a_story())
    stories.add_part(
        StoryPart(
            post_id="a1",
            story_id=story_id,
            part_number=Decimal("4.5"),
            part_label="Part 4.5",
            alternate_post_ids=["b2", "c3"],
        )
    )
    part = stories.parts(story_id)[0]
    assert part.part_number == Decimal("4.5")
    assert part.alternate_post_ids == ["b2", "c3"]


def test_clear_newly_filled(repos: tuple[StoryRepository, PostRepository]) -> None:
    stories, posts = repos
    posts.upsert_meta(a_post("a1"))
    story_id = stories.create(a_story())
    stories.add_part(StoryPart(post_id="a1", story_id=story_id, newly_filled=True))
    stories.clear_newly_filled(story_id, "a1")
    assert stories.parts(story_id)[0].newly_filled is False


def test_unavailable_parts_roundtrip(
    repos: tuple[StoryRepository, PostRepository],
) -> None:
    stories, _ = repos
    story_id = stories.create(a_story())
    stories.add_unavailable(
        UnavailablePart(story_id=story_id, part_number=Decimal("4"), auto_marked=True)
    )
    recs = stories.unavailable(story_id)
    assert recs[0].part_number == Decimal("4")
    assert recs[0].auto_marked is True


def test_clear_unavailable_removes_the_mark(
    repos: tuple[StoryRepository, PostRepository],
) -> None:
    stories, _ = repos
    story_id = stories.create(a_story())
    stories.add_unavailable(UnavailablePart(story_id=story_id, part_number=Decimal("4")))
    stories.clear_unavailable(story_id, Decimal("4"))
    assert stories.unavailable(story_id) == []


def test_cleaning_rule_decision_persists(
    repos: tuple[StoryRepository, PostRepository],
) -> None:
    stories, _ = repos
    story_id = stories.create(a_story())
    rule_id = stories.add_cleaning_rule(
        CleaningRule(
            story_id=story_id,
            position=CleaningPosition.TRAILING,
            block="Support me on Patreon!",
            seen_in_parts=12,
        )
    )
    stories.set_rule_decision(rule_id, approved=False)
    assert stories.cleaning_rules(story_id)[0].approved is False


def test_delete_removes_story_and_its_parts(
    repos: tuple[StoryRepository, PostRepository],
) -> None:
    stories, posts = repos
    posts.upsert_meta(a_post("a1"))
    story_id = stories.create(a_story())
    stories.add_part(StoryPart(post_id="a1", story_id=story_id))
    stories.delete(story_id)
    assert stories.get(story_id) is None
    assert stories.parts(story_id) == []
    assert posts.get_meta("a1") is not None  # PostMeta deliberately survives
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/storage/test_stories.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'reddit_reader.storage.stories'`

- [ ] **Step 3: Write the implementation**

Create `reddit_reader/storage/stories.py`:

```python
"""Repository for stories, their parts, and per-story annotations."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal

from reddit_reader.models import (
    CleaningPosition,
    CleaningRule,
    Story,
    StoryPart,
    UnavailablePart,
)


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _row_to_story(row: sqlite3.Row) -> Story:
    return Story(
        id=row["id"],
        series_key=row["series_key"],
        title=row["title"],
        author=row["author"],
        volume=row["volume"],
        tracked=bool(row["tracked"]),
        last_read_part=row["last_read_part"],
        last_read_offset=row["last_read_offset"],
        exported_markdown_path=row["exported_markdown_path"],
        exported_at=_dt(row["exported_at"]),
        last_updated_at=_dt(row["last_updated_at"]),
    )


def _row_to_part(row: sqlite3.Row) -> StoryPart:
    raw_alternates = row["alternate_post_ids"]
    return StoryPart(
        post_id=row["post_id"],
        story_id=row["story_id"],
        part_number=Decimal(row["part_number"]) if row["part_number"] is not None else None,
        part_label=row["part_label"],
        segment=row["segment"],
        segment_count=row["segment_count"],
        sort_key=row["sort_key"],
        alternate_post_ids=raw_alternates.split(",") if raw_alternates else [],
        newly_filled=bool(row["newly_filled"]),
        match_confidence=row["match_confidence"],
    )


class StoryRepository:
    """Reads and writes `story`, `story_part`, `unavailable_part`, `cleaning_rule`."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(self, story: Story) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO story
                (series_key, title, author, volume, tracked, last_read_part,
                 last_read_offset, exported_markdown_path, exported_at, last_updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                story.series_key,
                story.title,
                story.author,
                story.volume,
                int(story.tracked),
                story.last_read_part,
                story.last_read_offset,
                story.exported_markdown_path,
                story.exported_at.isoformat() if story.exported_at else None,
                story.last_updated_at.isoformat() if story.last_updated_at else None,
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid or 0)

    def get(self, story_id: int) -> Story | None:
        row = self.conn.execute("SELECT * FROM story WHERE id = ?", (story_id,)).fetchone()
        return _row_to_story(row) if row else None

    def all_stories(self) -> list[Story]:
        rows = self.conn.execute("SELECT * FROM story ORDER BY series_key, volume").fetchall()
        return [_row_to_story(row) for row in rows]

    def by_series_key(self, key: str) -> list[Story]:
        rows = self.conn.execute(
            "SELECT * FROM story WHERE series_key = ? ORDER BY volume", (key,)
        ).fetchall()
        return [_row_to_story(row) for row in rows]

    def find_committed(self, series_key: str, volume: int | None) -> Story | None:
        if volume is None:
            row = self.conn.execute(
                "SELECT * FROM story WHERE series_key = ? AND volume IS NULL", (series_key,)
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT * FROM story WHERE series_key = ? AND volume = ?", (series_key, volume)
            ).fetchone()
        return _row_to_story(row) if row else None

    def update(self, story: Story) -> None:
        self.conn.execute(
            """
            UPDATE story SET
                series_key = ?, title = ?, author = ?, volume = ?, tracked = ?,
                last_read_part = ?, last_read_offset = ?, exported_markdown_path = ?,
                exported_at = ?, last_updated_at = ?
            WHERE id = ?
            """,
            (
                story.series_key,
                story.title,
                story.author,
                story.volume,
                int(story.tracked),
                story.last_read_part,
                story.last_read_offset,
                story.exported_markdown_path,
                story.exported_at.isoformat() if story.exported_at else None,
                story.last_updated_at.isoformat() if story.last_updated_at else None,
                story.id,
            ),
        )
        self.conn.commit()

    def delete(self, story_id: int) -> None:
        self.conn.execute("DELETE FROM story WHERE id = ?", (story_id,))
        self.conn.commit()

    def add_part(self, part: StoryPart) -> None:
        self.conn.execute(
            """
            INSERT INTO story_part
                (post_id, story_id, part_number, part_label, segment, segment_count,
                 sort_key, alternate_post_ids, newly_filled, match_confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (story_id, post_id) DO UPDATE SET
                part_number = excluded.part_number,
                part_label = excluded.part_label,
                segment = excluded.segment,
                segment_count = excluded.segment_count,
                sort_key = excluded.sort_key,
                alternate_post_ids = excluded.alternate_post_ids,
                match_confidence = excluded.match_confidence
            """,
            (
                part.post_id,
                part.story_id,
                str(part.part_number) if part.part_number is not None else None,
                part.part_label,
                part.segment,
                part.segment_count,
                part.sort_key,
                ",".join(part.alternate_post_ids),
                int(part.newly_filled),
                part.match_confidence,
            ),
        )
        self.conn.commit()

    def parts(self, story_id: int) -> list[StoryPart]:
        rows = self.conn.execute(
            "SELECT * FROM story_part WHERE story_id = ?", (story_id,)
        ).fetchall()
        return [_row_to_part(row) for row in rows]

    def part_post_ids(self, story_id: int) -> list[str]:
        rows = self.conn.execute(
            "SELECT post_id FROM story_part WHERE story_id = ?", (story_id,)
        ).fetchall()
        return [row["post_id"] for row in rows]

    def clear_newly_filled(self, story_id: int, post_id: str) -> None:
        self.conn.execute(
            "UPDATE story_part SET newly_filled = 0 WHERE story_id = ? AND post_id = ?",
            (story_id, post_id),
        )
        self.conn.commit()

    def add_unavailable(self, rec: UnavailablePart) -> None:
        self.conn.execute(
            """
            INSERT INTO unavailable_part (story_id, part_number, auto_marked)
            VALUES (?, ?, ?)
            ON CONFLICT (story_id, part_number) DO UPDATE SET auto_marked = excluded.auto_marked
            """,
            (rec.story_id, str(rec.part_number), int(rec.auto_marked)),
        )
        self.conn.commit()

    def unavailable(self, story_id: int) -> list[UnavailablePart]:
        rows = self.conn.execute(
            "SELECT * FROM unavailable_part WHERE story_id = ?", (story_id,)
        ).fetchall()
        return [
            UnavailablePart(
                story_id=row["story_id"],
                part_number=Decimal(row["part_number"]),
                auto_marked=bool(row["auto_marked"]),
            )
            for row in rows
        ]

    def clear_unavailable(self, story_id: int, part_number: Decimal) -> None:
        self.conn.execute(
            "DELETE FROM unavailable_part WHERE story_id = ? AND part_number = ?",
            (story_id, str(part_number)),
        )
        self.conn.commit()

    def add_cleaning_rule(self, rule: CleaningRule) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO cleaning_rule (story_id, position, block, seen_in_parts, approved)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                rule.story_id,
                rule.position.value,
                rule.block,
                rule.seen_in_parts,
                None if rule.approved is None else int(rule.approved),
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid or 0)

    def cleaning_rules(self, story_id: int) -> list[CleaningRule]:
        rows = self.conn.execute(
            "SELECT * FROM cleaning_rule WHERE story_id = ?", (story_id,)
        ).fetchall()
        return [
            CleaningRule(
                story_id=row["story_id"],
                position=CleaningPosition(row["position"]),
                block=row["block"],
                seen_in_parts=row["seen_in_parts"],
                approved=None if row["approved"] is None else bool(row["approved"]),
            )
            for row in rows
        ]

    def set_rule_decision(self, rule_id: int, approved: bool) -> None:
        self.conn.execute(
            "UPDATE cleaning_rule SET approved = ? WHERE id = ?", (int(approved), rule_id)
        )
        self.conn.commit()
```

- [ ] **Step 4: Export the public storage surface**

Replace `reddit_reader/storage/__init__.py` with:

```python
"""Persistence layer: SQLite repositories and the full-text index."""

from reddit_reader.storage.db import connect
from reddit_reader.storage.posts import PostRepository
from reddit_reader.storage.search import SearchIndex
from reddit_reader.storage.stories import StoryRepository

__all__ = ["PostRepository", "SearchIndex", "StoryRepository", "connect"]
```

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -v`
Expected: PASS (all tests from Tasks 2-6)

- [ ] **Step 6: Commit**

```bash
uv run ruff check . && uv run ruff format . && uv run mypy reddit_reader
git add reddit_reader/storage tests/storage
git commit -m "feat: add story repository and export storage surface"
```

---

## ✅ Checkpoint A — Storage layer complete

**Verify before continuing:**

```bash
uv run pytest -v
uv run ruff check . && uv run ruff format --check .
uv run mypy reddit_reader
```

All must pass. At this point a database can be created, posts and bodies stored and retrieved, stories and parts committed, and full-text search performed. Nothing talks to Reddit yet.

---

# Layer 2 — Title Parsing and Detection

Everything in this layer is pure: no database, no network. This is the most rule-dense part of the spec, so it gets the most granular tasks.

**Checkpoint B** at the end: given a list of `PostMeta`, the app can group them into candidate stories with confidence scores, order their parts, collapse duplicates, and report gaps.

### Task 7: Title parsing

**Files:**
- Create: `reddit_reader/titles.py`
- Test: `tests/test_titles.py`

**Interfaces:**
- Consumes: nothing (operates on raw title strings).
- Produces: `ParsedTitle` (pydantic model with fields `base_title: str`, `part_number: Decimal | None`, `part_label: str | None`, `volume: int | None`, `segment: int | None`, `segment_count: int | None`, `tags: list[str]`) and `parse_title(raw: str) -> ParsedTitle`.

**Rules from the spec this must implement:**
- Numeric markers: `Part N`, `Chapter N`, `[N/M]`, `(N/M)`, roman numerals (`Part IV`), `cont.`/`continued`.
- Spelled-out numbers via `text2num` (`Chapter One`, `Chapter Eighty Six`).
- Volume markers (`Book Two`, `Volume 3`, `Season 2`, `Arc 4`) extracted into `volume`.
- Bracket tags that are not part-number patterns stripped from the base title but returned in `tags`.
- **Disambiguation:** an `(N/M)`/`[N/M]` group is a **segment** marker when a chapter/part marker is also present, and is the **part number** when it is the only number present.
- Named parts (`Interlude`, `Prologue`, `Epilogue`, `Side Story`) produce `part_number = None` and a `part_label`.
- Decimals (`Part 4.5`) produce a `Decimal` part number.
- The raw title is never mutated — `parse_title` only returns derived values.

- [ ] **Step 1: Write the failing test**

Create `tests/test_titles.py`:

```python
from decimal import Decimal

import pytest

from reddit_reader.titles import parse_title


def test_plain_part_marker() -> None:
    parsed = parse_title("The Long Road - Part 12")
    assert parsed.base_title == "the long road"
    assert parsed.part_number == Decimal("12")


def test_chapter_marker() -> None:
    assert parse_title("The Long Road, Chapter 7").part_number == Decimal("7")


def test_spelled_out_chapter_number() -> None:
    assert parse_title("The Long Road - Chapter One").part_number == Decimal("1")


def test_compound_spelled_out_chapter_number() -> None:
    assert parse_title("The Long Road - Chapter Eighty Six").part_number == Decimal("86")


def test_roman_numeral_part() -> None:
    assert parse_title("The Long Road - Part IV").part_number == Decimal("4")


def test_decimal_part_number() -> None:
    assert parse_title("The Long Road - Part 4.5").part_number == Decimal("4.5")


def test_bare_fraction_is_the_part_number() -> None:
    parsed = parse_title("The Long Road [3/10]")
    assert parsed.part_number == Decimal("3")
    assert parsed.segment is None


def test_fraction_is_a_segment_when_a_chapter_marker_is_present() -> None:
    parsed = parse_title("The Long Road - Chapter 12 (2/2)")
    assert parsed.part_number == Decimal("12")
    assert parsed.segment == 2
    assert parsed.segment_count == 2


def test_topic_tags_are_stripped_but_returned() -> None:
    parsed = parse_title("[OC] The Long Road - Part 3 [Sci-Fi]")
    assert parsed.base_title == "the long road"
    assert set(parsed.tags) == {"OC", "Sci-Fi"}


def test_volume_marker_is_extracted() -> None:
    parsed = parse_title("The Long Road, Book Two, Chapter 1")
    assert parsed.volume == 2
    assert parsed.part_number == Decimal("1")
    assert parsed.base_title == "the long road"


def test_numeric_volume_marker() -> None:
    assert parse_title("The Long Road Volume 3 - Part 5").volume == 3


def test_season_and_arc_are_volume_markers() -> None:
    assert parse_title("The Long Road Season 2 - Part 1").volume == 2
    assert parse_title("The Long Road Arc 4 - Part 1").volume == 4


@pytest.mark.parametrize("label", ["Interlude", "Prologue", "Epilogue"])
def test_named_parts_have_no_number_but_keep_a_label(label: str) -> None:
    parsed = parse_title(f"The Long Road - {label}")
    assert parsed.part_number is None
    assert parsed.part_label == label
    assert parsed.base_title == "the long road"


def test_side_story_is_a_named_part() -> None:
    parsed = parse_title("The Long Road - Side Story: Kevin")
    assert parsed.part_number is None
    assert parsed.part_label is not None
    assert parsed.part_label.startswith("Side Story")


def test_continuation_marker_is_stripped() -> None:
    assert parse_title("The Long Road (cont.)").base_title == "the long road"


def test_title_with_no_marker_yields_no_number() -> None:
    parsed = parse_title("The Long Road")
    assert parsed.part_number is None
    assert parsed.part_label is None
    assert parsed.base_title == "the long road"


def test_base_title_normalizes_whitespace_and_punctuation() -> None:
    assert parse_title("The   Long Road!! -- Part 2").base_title == "the long road"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_titles.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'reddit_reader.titles'`

- [ ] **Step 3: Write the implementation**

Create `reddit_reader/titles.py`:

```python
"""Parse Reddit serial-fiction post titles into structured parts.

The raw title is never modified. Everything here produces derived values used
for grouping comparisons and ordering.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, Field
from text2num import text2num

ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}

NAMED_PART_WORDS = ("interlude", "prologue", "epilogue", "side story", "intermission")

_TAG_RE = re.compile(r"[\[(]([^\]\)]+)[\])]")
_FRACTION_RE = re.compile(r"[\[(](\d+)\s*/\s*(\d+)[\])]")
_VOLUME_RE = re.compile(
    r"\b(?:book|volume|vol\.?|season|arc)\s+([\w.]+)\b",
    re.IGNORECASE,
)
_NUMERIC_PART_RE = re.compile(
    r"\b(?:part|chapter|ch\.?|pt\.?|episode|ep\.?)\s*#?\s*(\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)
_WORD_PART_RE = re.compile(
    r"\b(?:part|chapter)\s+([a-z][a-z\s-]*?)\b(?=\s*(?:[-–—:,.|]|$))",
    re.IGNORECASE,
)
_NAMED_PART_RE = re.compile(
    r"\b(" + "|".join(NAMED_PART_WORDS) + r")\b\s*:?\s*([^\-–—|]*)",
    re.IGNORECASE,
)
_CONT_RE = re.compile(r"\(?\b(?:cont\.?|continued)\b\)?", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


class ParsedTitle(BaseModel):
    """Structured view of a post title."""

    base_title: str
    part_number: Decimal | None = None
    part_label: str | None = None
    volume: int | None = None
    segment: int | None = None
    segment_count: int | None = None
    tags: list[str] = Field(default_factory=list)


def _roman_to_int(text: str) -> int | None:
    lowered = text.lower()
    if not lowered or any(ch not in ROMAN_VALUES for ch in lowered):
        return None
    total = 0
    previous = 0
    for ch in reversed(lowered):
        value = ROMAN_VALUES[ch]
        total = total - value if value < previous else total + value
        previous = max(previous, value)
    return total


def _words_to_int(text: str) -> int | None:
    cleaned = text.strip().replace("-", " ")
    try:
        return int(text2num(cleaned, "en"))
    except (ValueError, TypeError):
        return None


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    return _WS_RE.sub(" ", _PUNCT_RE.sub(" ", text)).strip().lower()


def parse_title(raw: str) -> ParsedTitle:
    """Extract part number, label, volume, segment, and tags from a raw title."""
    working = raw

    volume: int | None = None
    volume_match = _VOLUME_RE.search(working)
    if volume_match:
        token = volume_match.group(1)
        if token.isdigit():
            volume = int(token)
        else:
            volume = _words_to_int(token) or _roman_to_int(token)
        if volume is not None:
            working = working[: volume_match.start()] + " " + working[volume_match.end() :]

    part_number: Decimal | None = None
    part_label: str | None = None
    segment: int | None = None
    segment_count: int | None = None

    numeric_match = _NUMERIC_PART_RE.search(working)
    if numeric_match:
        try:
            part_number = Decimal(numeric_match.group(1))
        except InvalidOperation:
            part_number = None
        part_label = numeric_match.group(0).strip()
        working = working[: numeric_match.start()] + " " + working[numeric_match.end() :]

    if part_number is None:
        word_match = _WORD_PART_RE.search(working)
        if word_match:
            candidate = word_match.group(1).strip()
            value = _words_to_int(candidate) or _roman_to_int(candidate)
            if value is not None:
                part_number = Decimal(value)
                part_label = word_match.group(0).strip()
                working = working[: word_match.start()] + " " + working[word_match.end() :]

    fraction_match = _FRACTION_RE.search(working)
    if fraction_match:
        first, second = int(fraction_match.group(1)), int(fraction_match.group(2))
        if part_number is None:
            # Only number in the title: it *is* the part number.
            part_number = Decimal(first)
        else:
            # A chapter/part marker is also present: this is a segment marker.
            segment, segment_count = first, second
        working = working[: fraction_match.start()] + " " + working[fraction_match.end() :]

    if part_number is None:
        named_match = _NAMED_PART_RE.search(working)
        if named_match:
            part_label = named_match.group(0).strip().rstrip(":").strip()
            working = working[: named_match.start()] + " " + working[named_match.end() :]

    tags: list[str] = []
    for tag_match in _TAG_RE.finditer(working):
        tags.append(tag_match.group(1).strip())
    working = _TAG_RE.sub(" ", working)

    working = _CONT_RE.sub(" ", working)

    return ParsedTitle(
        base_title=_normalize(working),
        part_number=part_number,
        part_label=part_label,
        volume=volume,
        segment=segment,
        segment_count=segment_count,
        tags=tags,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_titles.py -v`
Expected: PASS (all tests, including the 3 parametrized named-part cases)

If any regex proves too greedy against a fixture, adjust the pattern — do not change the assertions. The assertions encode the spec.

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format . && uv run mypy reddit_reader
git add reddit_reader/titles.py tests/test_titles.py
git commit -m "feat: parse serial titles into numbers, labels, volumes, and tags"
```

---

### Task 8: Part ordering and sort keys

**Files:**
- Create: `reddit_reader/ordering.py`
- Test: `tests/test_ordering.py`

**Interfaces:**
- Consumes: `PostMeta`; `ParsedTitle` from Task 7.
- Produces:
  - `OrderedPart` (pydantic model: `post: PostMeta`, `parsed: ParsedTitle`, `anchor: Decimal`, `tiebreak: int`, `sort_key: str`)
  - `resolve_order(items: Sequence[tuple[PostMeta, ParsedTitle]]) -> list[OrderedPart]` — returns items sorted into reading order.
  - `group_segments(parts: Sequence[OrderedPart]) -> list[list[OrderedPart]]` — groups multi-segment parts so each inner list is one logical part in segment order.

**Ordering rules from the spec:** numbered parts sort by number; decimals sort naturally between whole numbers; named/unnumbered parts anchor by `created_utc` relative to their numbered neighbours (they follow the most recent numbered part that precedes them in time); a named part preceding every numbered part sorts before all of them; segments of one part stay together in segment order.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ordering.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ordering.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'reddit_reader.ordering'`

- [ ] **Step 3: Write the implementation**

Create `reddit_reader/ordering.py`:

```python
"""Resolve reading order for a story's parts.

Numbered parts sort by number. Unnumbered/named parts anchor to the most recent
numbered part that precedes them in time, so an Interlude posted between chapters
7 and 8 reads in that position. Segments of one part stay together.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from pydantic import BaseModel

from reddit_reader.models import PostMeta
from reddit_reader.titles import ParsedTitle

# Anchors are rendered into a zero-padded string so sort keys compare correctly
# as text, which lets them be stored in SQLite and sorted by SQL if needed.
_ANCHOR_WIDTH = 8
_ANCHOR_PRECISION = 3


class OrderedPart(BaseModel):
    """A post with its resolved position in a story."""

    post: PostMeta
    parsed: ParsedTitle
    anchor: Decimal
    tiebreak: int
    sort_key: str


def _format_sort_key(anchor: Decimal, tiebreak: int, created: float, segment: int) -> str:
    scaled = int(anchor * (10**_ANCHOR_PRECISION))
    return f"{scaled:0{_ANCHOR_WIDTH}d}|{tiebreak}|{created:015.3f}|{segment:03d}"


def resolve_order(items: Sequence[tuple[PostMeta, ParsedTitle]]) -> list[OrderedPart]:
    """Return the items in reading order with anchors and sort keys resolved."""
    if not items:
        return []

    by_time = sorted(items, key=lambda pair: pair[0].created_utc)
    numbers = [parsed.part_number for _, parsed in by_time if parsed.part_number is not None]
    fallback_anchor = (min(numbers) - 1) if numbers else Decimal(0)

    resolved: list[OrderedPart] = []
    current_anchor = fallback_anchor

    for post, parsed in by_time:
        if parsed.part_number is not None:
            current_anchor = parsed.part_number
            anchor, tiebreak = parsed.part_number, 0
        else:
            anchor, tiebreak = current_anchor, 1

        resolved.append(
            OrderedPart(
                post=post,
                parsed=parsed,
                anchor=anchor,
                tiebreak=tiebreak,
                sort_key=_format_sort_key(
                    anchor,
                    tiebreak,
                    post.created_utc.timestamp(),
                    parsed.segment or 0,
                ),
            )
        )

    return sorted(resolved, key=lambda part: part.sort_key)


def group_segments(parts: Sequence[OrderedPart]) -> list[list[OrderedPart]]:
    """Group consecutive segments of one logical part together."""
    groups: list[list[OrderedPart]] = []
    for part in parts:
        previous = groups[-1][-1] if groups else None
        same_part = (
            previous is not None
            and part.parsed.segment is not None
            and previous.parsed.segment is not None
            and part.parsed.part_number is not None
            and previous.parsed.part_number == part.parsed.part_number
        )
        if same_part:
            groups[-1].append(part)
        else:
            groups.append([part])
    return groups
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ordering.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format . && uv run mypy reddit_reader
git add reddit_reader/ordering.py tests/test_ordering.py
git commit -m "feat: resolve part ordering with anchors, decimals, and segments"
```

---

### Task 9: Duplicate and crosspost collapsing

**Files:**
- Create: `reddit_reader/dedupe.py`
- Test: `tests/test_dedupe.py`

**Interfaces:**
- Consumes: `PostMeta`; `parse_title` from Task 7.
- Produces: `DuplicateGroup` (pydantic model: `canonical: PostMeta`, `alternates: list[PostMeta]`) and `collapse_duplicates(posts: Sequence[PostMeta], subreddit_priority: Sequence[str], window_hours: int = 48) -> list[DuplicateGroup]`.

**Rules from the spec:** `crosspost_parent` is trusted when present. Otherwise a heuristic catches manual re-posts: same author, same normalized base title, same extracted part number, posted within a short time window. The canonical copy is the earliest post from the highest-priority subreddit (config list order sets priority).

- [ ] **Step 1: Write the failing test**

Create `tests/test_dedupe.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dedupe.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'reddit_reader.dedupe'`

- [ ] **Step 3: Write the implementation**

Create `reddit_reader/dedupe.py`:

```python
"""Collapse crossposted and manually mirrored copies of the same part."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from reddit_reader.models import PostMeta
from reddit_reader.titles import parse_title

DEFAULT_WINDOW_HOURS = 48


class DuplicateGroup(BaseModel):
    """One logical post plus any mirrored copies of it."""

    canonical: PostMeta
    alternates: list[PostMeta]


def _priority_rank(subreddit: str, priority: Sequence[str]) -> int:
    lowered = [s.lower() for s in priority]
    try:
        return lowered.index(subreddit.lower())
    except ValueError:
        return len(priority)


def collapse_duplicates(
    posts: Sequence[PostMeta],
    subreddit_priority: Sequence[str],
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> list[DuplicateGroup]:
    """Group mirrored copies of the same part, choosing one canonical post each."""
    by_id = {p.id: p for p in posts}
    parents: dict[str, str] = {}

    # Trust explicit crosspost links first.
    for post in posts:
        if post.crosspost_parent and post.crosspost_parent in by_id:
            parents[post.id] = post.crosspost_parent

    # Then the heuristic: same author, base title, and part number, close in time.
    remaining = [p for p in posts if p.id not in parents]
    buckets: dict[tuple[str, str, str], list[PostMeta]] = {}
    for post in remaining:
        parsed = parse_title(post.title)
        key = (
            post.author.lower(),
            parsed.base_title,
            str(parsed.part_number) if parsed.part_number is not None else "",
        )
        buckets.setdefault(key, []).append(post)

    clusters: list[list[PostMeta]] = []
    for bucket in buckets.values():
        ordered = sorted(bucket, key=lambda p: p.created_utc)
        current: list[PostMeta] = []
        for post in ordered:
            if current:
                elapsed = (post.created_utc - current[0].created_utc).total_seconds() / 3600
                if elapsed > window_hours:
                    clusters.append(current)
                    current = []
            current.append(post)
        if current:
            clusters.append(current)

    # Re-attach explicit crossposts to their parent's cluster.
    for child_id, parent_id in parents.items():
        for cluster in clusters:
            if any(p.id == parent_id for p in cluster):
                cluster.append(by_id[child_id])
                break

    groups: list[DuplicateGroup] = []
    for cluster in clusters:
        ranked = sorted(
            cluster,
            key=lambda p: (_priority_rank(p.subreddit, subreddit_priority), p.created_utc),
        )
        groups.append(DuplicateGroup(canonical=ranked[0], alternates=ranked[1:]))
    return groups
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_dedupe.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format . && uv run mypy reddit_reader
git add reddit_reader/dedupe.py tests/test_dedupe.py
git commit -m "feat: collapse crossposted and mirrored duplicate parts"
```

---

### Task 10: Grouping and confidence scoring

**Files:**
- Create: `reddit_reader/detection.py`
- Test: `tests/test_detection.py`

**Interfaces:**
- Consumes: `PostMeta`, `DetectionMatch`, `Story`; `parse_title`; `resolve_order`; `collapse_duplicates`.
- Produces:
  - `series_key(author: str, base_title: str) -> str`
  - `group_posts(posts: Sequence[PostMeta], subreddit_priority: Sequence[str]) -> list[DetectionMatch]`
  - `DELETED_AUTHOR: str = "[deleted]"`

**Rules from the spec:** grouping key is (normalized base title, author, volume). Author match is required. `[deleted]` never satisfies the author-match requirement — such posts do not group with each other. Confidence combines title similarity, clean part numbering, and posting-interval regularity.

- [ ] **Step 1: Write the failing test**

Create `tests/test_detection.py`:

```python
from datetime import UTC, datetime, timedelta

from reddit_reader.detection import DELETED_AUTHOR, group_posts, series_key
from reddit_reader.models import PostMeta

BASE = datetime(2026, 1, 1, tzinfo=UTC)
PRIORITY = ["HFY"]


def post(
    post_id: str, title: str, *, author: str = "BlueFishcake", days: int = 0
) -> PostMeta:
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_detection.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'reddit_reader.detection'`

- [ ] **Step 3: Write the implementation**

Create `reddit_reader/detection.py`:

```python
"""Group posts into candidate series and score how confident the grouping is."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from difflib import SequenceMatcher

from reddit_reader.dedupe import collapse_duplicates
from reddit_reader.models import DetectionMatch, PostMeta
from reddit_reader.ordering import resolve_order
from reddit_reader.titles import ParsedTitle, parse_title

DELETED_AUTHOR = "[deleted]"

# Confidence weights. Title similarity dominates because it is the primary signal;
# numbering and cadence refine it.
WEIGHT_TITLE = 0.5
WEIGHT_NUMBERING = 0.3
WEIGHT_CADENCE = 0.2

# A serial posting more than this many days apart looks abandoned or mis-grouped.
CADENCE_TOLERANCE_DAYS = 120.0


def series_key(author: str, base_title: str) -> str:
    """Stable identity for a serial across its volumes."""
    return f"{author.lower()}:{base_title}"


def _title_similarity(parsed: Sequence[ParsedTitle]) -> float:
    if len(parsed) < 2:
        return 1.0
    reference = parsed[0].base_title
    ratios = [SequenceMatcher(None, reference, p.base_title).ratio() for p in parsed[1:]]
    return min(ratios)


def _numbering_score(parsed: Sequence[ParsedTitle]) -> float:
    numbers = [p.part_number for p in parsed if p.part_number is not None]
    if not numbers:
        return 0.0
    coverage = len(numbers) / len(parsed)
    unique = len(set(numbers)) == len(numbers)
    return coverage * (1.0 if unique else 0.5)


def _cadence_score(posts: Sequence[PostMeta]) -> float:
    if len(posts) < 2:
        return 1.0
    times = sorted(p.created_utc for p in posts)
    gaps = [
        (later - earlier).total_seconds() / 86400
        for earlier, later in zip(times, times[1:], strict=True)
    ]
    median_gap = statistics.median(gaps)
    if median_gap <= 0:
        return 1.0
    return max(0.0, min(1.0, CADENCE_TOLERANCE_DAYS / (median_gap + CADENCE_TOLERANCE_DAYS) * 2))


def _score(posts: Sequence[PostMeta], parsed: Sequence[ParsedTitle]) -> tuple[float, list[str]]:
    title = _title_similarity(parsed)
    numbering = _numbering_score(parsed)
    cadence = _cadence_score(posts)
    confidence = WEIGHT_TITLE * title + WEIGHT_NUMBERING * numbering + WEIGHT_CADENCE * cadence
    reasons = [
        f"titles {title:.0%} similar",
        f"part numbering score {numbering:.2f}",
        f"posting cadence score {cadence:.2f}",
    ]
    return round(min(1.0, max(0.0, confidence)), 4), reasons


def group_posts(
    posts: Sequence[PostMeta], subreddit_priority: Sequence[str]
) -> list[DetectionMatch]:
    """Collapse duplicates, then group the survivors into candidate series."""
    groups = collapse_duplicates(posts, subreddit_priority)
    canonical = [group.canonical for group in groups]

    buckets: dict[tuple[str, str, int | None], list[tuple[PostMeta, ParsedTitle]]] = {}
    solo: list[tuple[PostMeta, ParsedTitle]] = []

    for post in canonical:
        parsed = parse_title(post.title)
        if post.author == DELETED_AUTHOR:
            # A deleted account is not an identity: never let it satisfy author match.
            solo.append((post, parsed))
            continue
        key = (post.author.lower(), parsed.base_title, parsed.volume)
        buckets.setdefault(key, []).append((post, parsed))

    matches: list[DetectionMatch] = []
    for (_author_key, base_title, volume), items in buckets.items():
        ordered = resolve_order(items)
        group_posts_list = [part.post for part in ordered]
        group_parsed = [part.parsed for part in ordered]
        confidence, reasons = _score(group_posts_list, group_parsed)
        matches.append(
            DetectionMatch(
                base_title=base_title,
                author=group_posts_list[0].author,
                volume=volume,
                post_ids=[p.id for p in group_posts_list],
                confidence=confidence,
                reasons=reasons,
            )
        )

    for post, parsed in solo:
        confidence, reasons = _score([post], [parsed])
        matches.append(
            DetectionMatch(
                base_title=parsed.base_title,
                author=post.author,
                volume=parsed.volume,
                post_ids=[post.id],
                confidence=confidence,
                reasons=[*reasons, "author is [deleted]; grouping requires review"],
            )
        )

    return matches
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_detection.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format . && uv run mypy reddit_reader
git add reddit_reader/detection.py tests/test_detection.py
git commit -m "feat: group posts into candidate series with confidence scoring"
```

---

### Task 11: Gap detection and attach decisions

**Files:**
- Modify: `reddit_reader/detection.py`
- Test: `tests/test_gaps.py`

**Interfaces:**
- Consumes: everything from Task 10, plus `UnavailablePart`, `StoryPart`.
- Produces (added to `detection.py`):
  - `find_gaps(part_numbers: Sequence[Decimal], unavailable: Sequence[Decimal] = ()) -> list[Decimal]`
  - `AttachDecision` (pydantic model: `action: Literal["auto_attach", "curate", "new_series"]`, `story_id: int | None`, `confidence: float`)
  - `decide_attachment(match: DetectionMatch, existing: Story | None, threshold: float) -> AttachDecision`
  - `DEFAULT_ATTACH_THRESHOLD: float = 0.85`

**Rules from the spec:** a gap is an interior missing number or a sequence not starting at 1. Trailing parts are never gaps. Only whole numbers participate; `None` part numbers are excluded; an entirely unnumbered story reports no gaps. `UnavailablePart` numbers are suppressed. Auto-attach applies only to matches against an already-committed story above the threshold; everything else goes to curation.

- [ ] **Step 1: Write the failing test**

Create `tests/test_gaps.py`:

```python
from decimal import Decimal

from reddit_reader.detection import (
    DEFAULT_ATTACH_THRESHOLD,
    decide_attachment,
    find_gaps,
)
from reddit_reader.models import DetectionMatch, Story


def d(*values: str) -> list[Decimal]:
    return [Decimal(v) for v in values]


def test_contiguous_sequence_has_no_gaps() -> None:
    assert find_gaps(d("1", "2", "3")) == []


def test_interior_gap_is_reported() -> None:
    assert find_gaps(d("1", "2", "3", "5", "6")) == d("4")


def test_multiple_interior_gaps_are_reported() -> None:
    assert find_gaps(d("1", "4", "7")) == d("2", "3", "5", "6")


def test_missing_start_is_reported() -> None:
    assert find_gaps(d("5", "6", "7")) == d("1", "2", "3", "4")


def test_trailing_parts_are_never_a_gap() -> None:
    assert find_gaps(d("1", "2", "3")) == []


def test_empty_sequence_has_no_gaps() -> None:
    assert find_gaps([]) == []


def test_decimal_parts_do_not_create_gaps() -> None:
    assert find_gaps(d("1", "1.5", "2")) == []


def test_unavailable_numbers_are_suppressed() -> None:
    assert find_gaps(d("1", "2", "5"), unavailable=d("3", "4")) == []


def test_partially_unavailable_gap_still_reports_the_rest() -> None:
    assert find_gaps(d("1", "5"), unavailable=d("3")) == d("2", "4")


def test_duplicate_numbers_do_not_break_gap_detection() -> None:
    assert find_gaps(d("1", "2", "2", "4")) == d("3")


def test_high_confidence_match_on_existing_story_auto_attaches() -> None:
    match = DetectionMatch(
        base_title="road", author="A", volume=None, post_ids=["x"], confidence=0.95
    )
    story = Story(id=7, series_key="a:road", title="Road", author="A")
    decision = decide_attachment(match, story, DEFAULT_ATTACH_THRESHOLD)
    assert decision.action == "auto_attach"
    assert decision.story_id == 7


def test_low_confidence_match_on_existing_story_goes_to_curation() -> None:
    match = DetectionMatch(
        base_title="road", author="A", volume=None, post_ids=["x"], confidence=0.4
    )
    story = Story(id=7, series_key="a:road", title="Road", author="A")
    decision = decide_attachment(match, story, DEFAULT_ATTACH_THRESHOLD)
    assert decision.action == "curate"
    assert decision.story_id == 7


def test_match_with_no_existing_story_is_a_new_series() -> None:
    match = DetectionMatch(
        base_title="road", author="A", volume=None, post_ids=["x"], confidence=0.99
    )
    decision = decide_attachment(match, None, DEFAULT_ATTACH_THRESHOLD)
    assert decision.action == "new_series"
    assert decision.story_id is None


def test_threshold_boundary_is_inclusive() -> None:
    match = DetectionMatch(
        base_title="road", author="A", volume=None, post_ids=["x"], confidence=0.85
    )
    story = Story(id=1, series_key="a:road", title="Road", author="A")
    assert decide_attachment(match, story, 0.85).action == "auto_attach"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_gaps.py -v`
Expected: FAIL with `ImportError: cannot import name 'find_gaps'`

- [ ] **Step 3: Append the implementation to `detection.py`**

Add these imports at the top of `reddit_reader/detection.py`. Note the models import already exists from Task 10 — **merge `Story` into that line** rather than adding a second `from reddit_reader.models import ...`, which ruff would flag:

```python
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

# existing line becomes:
from reddit_reader.models import DetectionMatch, PostMeta, Story
```

`Sequence` is already imported from `collections.abc` in Task 10 and is reused by `find_gaps`.

Append to the end of `reddit_reader/detection.py`:

```python
DEFAULT_ATTACH_THRESHOLD = 0.85


class AttachDecision(BaseModel):
    """What to do with a detection match: attach silently, curate, or treat as new."""

    action: Literal["auto_attach", "curate", "new_series"]
    story_id: int | None
    confidence: float


def find_gaps(
    part_numbers: Sequence[Decimal], unavailable: Sequence[Decimal] = ()
) -> list[Decimal]:
    """Return whole-number parts missing from the start of, or inside, the sequence.

    Trailing parts are deliberately not gaps: newer installments arrive via an
    ordinary refresh and need no author-history lookup.
    """
    whole = sorted({n for n in part_numbers if n == n.to_integral_value()})
    if not whole:
        return []

    suppressed = set(unavailable)
    highest = max(whole)
    present = set(whole)

    missing = [
        Decimal(candidate)
        for candidate in range(1, int(highest))
        if Decimal(candidate) not in present and Decimal(candidate) not in suppressed
    ]
    return missing


def decide_attachment(
    match: DetectionMatch, existing: Story | None, threshold: float
) -> AttachDecision:
    """Decide whether a match attaches silently, needs curation, or is a new series."""
    if existing is None:
        return AttachDecision(action="new_series", story_id=None, confidence=match.confidence)
    if match.confidence >= threshold:
        return AttachDecision(
            action="auto_attach", story_id=existing.id, confidence=match.confidence
        )
    return AttachDecision(action="curate", story_id=existing.id, confidence=match.confidence)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_gaps.py -v`
Expected: PASS (14 tests)

- [ ] **Step 5: Run the whole suite and commit**

```bash
uv run pytest -v
uv run ruff check . && uv run ruff format . && uv run mypy reddit_reader
git add reddit_reader/detection.py tests/test_gaps.py
git commit -m "feat: add gap detection and attach decisions"
```

---

### Task 12: Navigation link parsing

**Files:**
- Create: `reddit_reader/navlinks.py`
- Test: `tests/test_navlinks.py`

**Interfaces:**
- Consumes: nothing (operates on raw body text).
- Produces: `NavLinks` (pydantic model: `first: str | None`, `previous: str | None`, `next: str | None`) and `parse_nav_links(selftext: str) -> NavLinks`, plus `extract_post_id(url: str) -> str | None`.

**Rules from the spec:** parse `First`/`Prev`/`Previous`/`Next` links out of a cached body and resolve them to Reddit post ids.

- [ ] **Step 1: Write the failing test**

Create `tests/test_navlinks.py`:

```python
from reddit_reader.navlinks import extract_post_id, parse_nav_links

NAV_BLOCK = """
Some story text here.

[First](https://www.reddit.com/r/HFY/comments/aaa111/road_part_1/) |
[Prev](https://www.reddit.com/r/HFY/comments/bbb222/road_part_11/) |
[Next](https://www.reddit.com/r/HFY/comments/ccc333/road_part_13/)
"""


def test_extract_post_id_from_full_url() -> None:
    url = "https://www.reddit.com/r/HFY/comments/abc123/some_title/"
    assert extract_post_id(url) == "abc123"


def test_extract_post_id_from_short_url() -> None:
    assert extract_post_id("https://redd.it/abc123") == "abc123"


def test_extract_post_id_returns_none_for_unrelated_url() -> None:
    assert extract_post_id("https://patreon.com/bluefishcake") is None


def test_parses_all_three_links() -> None:
    links = parse_nav_links(NAV_BLOCK)
    assert links.first == "aaa111"
    assert links.previous == "bbb222"
    assert links.next == "ccc333"


def test_previous_spelled_out_is_recognized() -> None:
    text = "[Previous](https://www.reddit.com/r/HFY/comments/bbb222/x/)"
    assert parse_nav_links(text).previous == "bbb222"


def test_missing_links_are_none() -> None:
    links = parse_nav_links("Just a story with no navigation.")
    assert links.first is None
    assert links.previous is None
    assert links.next is None


def test_link_labels_are_case_insensitive() -> None:
    text = "[NEXT](https://www.reddit.com/r/HFY/comments/ccc333/x/)"
    assert parse_nav_links(text).next == "ccc333"


def test_non_reddit_link_is_ignored() -> None:
    text = "[Next](https://royalroad.com/fiction/1)"
    assert parse_nav_links(text).next is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_navlinks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'reddit_reader.navlinks'`

- [ ] **Step 3: Write the implementation**

Create `reddit_reader/navlinks.py`:

```python
"""Parse First/Prev/Next navigation links out of a cached post body."""

from __future__ import annotations

import re

from pydantic import BaseModel

_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_COMMENTS_URL_RE = re.compile(r"reddit\.com/r/[^/]+/comments/([a-z0-9]+)", re.IGNORECASE)
_SHORT_URL_RE = re.compile(r"redd\.it/([a-z0-9]+)", re.IGNORECASE)

_FIRST_LABELS = ("first",)
_PREV_LABELS = ("prev", "previous")
_NEXT_LABELS = ("next",)


class NavLinks(BaseModel):
    """Post ids referenced by a body's navigation links."""

    first: str | None = None
    previous: str | None = None
    next: str | None = None


def extract_post_id(url: str) -> str | None:
    """Return the Reddit post id in `url`, or None if it isn't a Reddit post link."""
    match = _COMMENTS_URL_RE.search(url) or _SHORT_URL_RE.search(url)
    return match.group(1) if match else None


def parse_nav_links(selftext: str) -> NavLinks:
    """Find First/Prev/Next navigation links and resolve them to post ids."""
    links = NavLinks()
    for label, url in _MARKDOWN_LINK_RE.findall(selftext):
        post_id = extract_post_id(url)
        if post_id is None:
            continue
        normalized = label.strip().lower().strip("[]<> ")
        if links.first is None and any(w == normalized for w in _FIRST_LABELS):
            links.first = post_id
        elif links.previous is None and any(w == normalized for w in _PREV_LABELS):
            links.previous = post_id
        elif links.next is None and any(w == normalized for w in _NEXT_LABELS):
            links.next = post_id
    return links
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_navlinks.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format . && uv run mypy reddit_reader
git add reddit_reader/navlinks.py tests/test_navlinks.py
git commit -m "feat: parse First/Prev/Next navigation links from bodies"
```

---

## ✅ Checkpoint B — Detection logic complete

**Verify before continuing:**

```bash
uv run pytest -v
uv run ruff check . && uv run ruff format --check .
uv run mypy reddit_reader
```

All must pass. Given a list of `PostMeta`, the app can now parse titles (numbers, decimals, named parts, volumes, segments, tags), collapse duplicates, group posts into scored candidate series, resolve reading order, find gaps, decide attachment, and read navigation links. Still no network and no UI.

---

# Layer 3 — Reddit Client

**Checkpoint C** at the end: the app can fetch listings, search, and pull author history — all against a fake PRAW, with no real network calls in tests.

### Task 13: PRAW wrapper with typed errors

**Files:**
- Create: `reddit_reader/reddit_client.py`
- Create: `tests/fakes.py`
- Test: `tests/test_reddit_client.py`

**Interfaces:**
- Consumes: `PostMeta`, `PostBody`.
- Produces:
  - Exceptions `RedditError` (base), `RedditFetchError`, `RedditAuthError`.
  - `ListingType` (`Literal["new", "hot", "top"]`), `TimeWindow` (`Literal["day", "week", "month", "year", "all"]`).
  - `RedditClient` with `fetch_listing(subreddit, listing, limit, time_window) -> list[PostMeta]`, `search(query, subreddit=None, limit=50) -> list[PostMeta]`, `author_submissions(author, limit=None) -> list[PostMeta]`, `fetch_bodies(post_ids) -> list[PostBody]`, `check_available(post_id) -> bool`.
  - `to_post_meta(submission: object) -> PostMeta` — the single conversion boundary.
- `tests/fakes.py` produces `FakeSubmission`, `FakeReddit`, and `make_submission(...)` for use by later test files too.

**Rules from the spec:** PRAW exceptions are caught here and re-raised as typed exceptions; nothing downstream touches PRAW types. Raw PRAW objects convert to `PostMeta`/`PostBody` immediately. Availability is updated opportunistically when a fetch happens to touch a post and finds it gone.

- [ ] **Step 1: Write the fake PRAW**

Create `tests/fakes.py`:

```python
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

    def top(
        self, time_filter: str = "all", limit: int | None = None
    ) -> list[FakeSubmission]:
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
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_reddit_client.py`:

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_reddit_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'reddit_reader.reddit_client'`

- [ ] **Step 4: Write the implementation**

Create `reddit_reader/reddit_client.py`:

```python
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
        except Exception as exc:  # noqa: BLE001 - deliberately broad at the boundary
            raise RedditFetchError(f"failed to fetch r/{subreddit} ({listing})") from exc

    def search(
        self, query: str, subreddit: str | None = None, limit: int = 50
    ) -> list[PostMeta]:
        target = subreddit or "all"
        try:
            source = self._reddit.subreddit(target)
            return [to_post_meta(s) for s in source.search(query, limit=limit)]
        except Exception as exc:  # noqa: BLE001
            raise RedditFetchError(f"search failed in r/{target}") from exc

    def author_submissions(self, author: str, limit: int | None = None) -> list[PostMeta]:
        try:
            redditor = self._reddit.redditor(author)
            return [to_post_meta(s) for s in redditor.submissions.new(limit=limit)]
        except Exception as exc:  # noqa: BLE001
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

    def check_available(self, post_id: str) -> bool:
        """Report whether a post still exists upstream."""
        try:
            self._reddit.submission(id=post_id)
        except Exception:  # noqa: BLE001
            return False
        return True
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_reddit_client.py -v`
Expected: PASS (13 tests)

- [ ] **Step 6: Commit**

```bash
uv run ruff check . && uv run ruff format . && uv run mypy reddit_reader
git add reddit_reader/reddit_client.py tests/fakes.py tests/test_reddit_client.py
git commit -m "feat: add PRAW wrapper with typed errors and model conversion"
```

---

## ✅ Checkpoint C — Reddit client complete

Run `uv run pytest -v`, `uv run ruff check .`, `uv run mypy reddit_reader`. All must pass.

---

# Layer 4 — Cleaning and Export

**Checkpoint D** at the end: story text can be cleaned of boilerplate and written out as Markdown or a links index.

### Task 14: Pattern-based boilerplate stripping

**Files:**
- Create: `reddit_reader/cleaning.py`
- Test: `tests/test_cleaning.py`

**Interfaces:**
- Consumes: nothing (operates on raw body text).
- Produces: `strip_patterns(selftext: str) -> str`.

**Rules from the spec:** strip navigation link blocks, known external-support plugs (Patreon, RoyalRoad, Ko-fi and similar), and generic sign-offs. The raw body is never modified in storage — this is applied at render time.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cleaning.py`:

```python
from reddit_reader.cleaning import strip_patterns

STORY = "The xenobiologist blinked twice.\n\nShe had not expected the humans to sing."


def test_story_text_survives_untouched() -> None:
    assert strip_patterns(STORY).strip() == STORY


def test_nav_link_block_is_removed() -> None:
    text = (
        f"{STORY}\n\n"
        "[First](https://www.reddit.com/r/HFY/comments/a/x/) | "
        "[Prev](https://www.reddit.com/r/HFY/comments/b/x/) | "
        "[Next](https://www.reddit.com/r/HFY/comments/c/x/)\n"
    )
    cleaned = strip_patterns(text)
    assert "Next" not in cleaned
    assert "xenobiologist" in cleaned


def test_patreon_plug_is_removed() -> None:
    text = f"{STORY}\n\nSupport me on [Patreon](https://patreon.com/bluefishcake)!"
    cleaned = strip_patterns(text)
    assert "patreon" not in cleaned.lower()
    assert "xenobiologist" in cleaned


def test_royalroad_plug_is_removed() -> None:
    text = f"{STORY}\n\nRead ahead on [RoyalRoad](https://royalroad.com/fiction/1)."
    assert "royalroad" not in strip_patterns(text).lower()


def test_kofi_plug_is_removed() -> None:
    text = f"{STORY}\n\n[Ko-fi](https://ko-fi.com/bluefishcake)"
    assert "ko-fi" not in strip_patterns(text).lower()


def test_generic_signoff_is_removed() -> None:
    text = f"{STORY}\n\nHope you enjoyed! Comments welcome."
    cleaned = strip_patterns(text)
    assert "Hope you enjoyed" not in cleaned
    assert "xenobiologist" in cleaned


def test_prose_mentioning_next_is_not_stripped() -> None:
    text = "She wondered what the next day would bring."
    assert "next day" in strip_patterns(text)


def test_blank_input_stays_blank() -> None:
    assert strip_patterns("") == ""


def test_excess_blank_lines_are_collapsed() -> None:
    text = "Line one.\n\n\n\n\nLine two."
    assert "\n\n\n" not in strip_patterns(text)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cleaning.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'reddit_reader.cleaning'`

- [ ] **Step 3: Write the implementation**

Create `reddit_reader/cleaning.py`:

```python
"""Remove recurring boilerplate from post bodies at render time.

Nothing here mutates stored text. `PostBody.selftext` always holds the raw post,
so patterns can improve and decisions can be revoked without re-fetching.
"""

from __future__ import annotations

import re

_NAV_LABELS = r"(?:first|prev|previous|next|index|wiki)"
_NAV_LINE_RE = re.compile(
    rf"^\s*(?:\[{_NAV_LABELS}\]\([^)]*\)\s*[|\-–—]?\s*)+$",
    re.IGNORECASE | re.MULTILINE,
)

_PLUG_HOSTS = r"(?:patreon|royalroad|ko-?fi|subscribestar|buymeacoffee|topwebfiction)"
_PLUG_LINE_RE = re.compile(rf"^.*{_PLUG_HOSTS}.*$", re.IGNORECASE | re.MULTILINE)

_SIGNOFF_RE = re.compile(
    r"^\s*(?:"
    r"hope you (?:enjoyed|liked)"
    r"|thanks for reading"
    r"|comments? (?:and criticism )?(?:are )?welcome"
    r"|let me know what you think"
    r"|as always[,.]? (?:thanks|thank you)"
    r").*$",
    re.IGNORECASE | re.MULTILINE,
)

_BLANK_RUN_RE = re.compile(r"\n{3,}")


def strip_patterns(selftext: str) -> str:
    """Remove nav blocks, support plugs, and generic sign-offs."""
    text = _NAV_LINE_RE.sub("", selftext)
    text = _PLUG_LINE_RE.sub("", text)
    text = _SIGNOFF_RE.sub("", text)
    return _BLANK_RUN_RE.sub("\n\n", text).strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cleaning.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format . && uv run mypy reddit_reader
git add reddit_reader/cleaning.py tests/test_cleaning.py
git commit -m "feat: strip nav blocks, support plugs, and sign-offs from bodies"
```

---

### Task 15: Learned header/footer detection

**Files:**
- Modify: `reddit_reader/cleaning.py`
- Test: `tests/test_learned_cleaning.py`

**Interfaces:**
- Consumes: `CleaningRule`, `CleaningPosition`; `strip_patterns` from Task 14.
- Produces (added to `cleaning.py`):
  - `LearnedBlock` (pydantic model: `position: CleaningPosition`, `block: str`, `seen_in_parts: int`)
  - `detect_boilerplate(bodies: Sequence[str], *, window: int = 12, majority: float = 0.6, min_parts: int = 3) -> list[LearnedBlock]`
  - `apply_rules(selftext: str, rules: Sequence[CleaningRule]) -> str`
  - `clean(selftext: str, rules: Sequence[CleaningRule], *, strip_known_patterns: bool = True) -> str`

**Rules from the spec:** take the leading and trailing runs of lines from each part within a bounded window; compare with fuzzy line matching so a header embedding the chapter number still matches; find the longest leading and trailing block present in at least a configurable majority of parts; skip stories with too few parts. Never strip silently — only rules with `approved is True` are applied.

- [ ] **Step 1: Write the failing test**

Create `tests/test_learned_cleaning.py`:

```python
from reddit_reader.cleaning import apply_rules, clean, detect_boilerplate
from reddit_reader.models import CleaningPosition, CleaningRule


def body(chapter: int) -> str:
    return (
        f"*The Long Road, Chapter {chapter}*\n"
        "A Blue Fishcake production.\n"
        "\n"
        f"Story content unique to chapter {chapter} goes here.\n"
        "\n"
        "---\n"
        "Posted weekly. See you next time."
    )


BODIES = [body(n) for n in range(1, 8)]


def test_detects_a_leading_block() -> None:
    blocks = detect_boilerplate(BODIES)
    leading = [b for b in blocks if b.position == CleaningPosition.LEADING]
    assert leading
    assert "Blue Fishcake production" in leading[0].block


def test_detects_a_trailing_block() -> None:
    blocks = detect_boilerplate(BODIES)
    trailing = [b for b in blocks if b.position == CleaningPosition.TRAILING]
    assert trailing
    assert "See you next time" in trailing[0].block


def test_reports_how_many_parts_a_block_appears_in() -> None:
    blocks = detect_boilerplate(BODIES)
    assert blocks[0].seen_in_parts == len(BODIES)


def test_header_varying_by_chapter_number_still_matches() -> None:
    blocks = detect_boilerplate(BODIES)
    leading = [b for b in blocks if b.position == CleaningPosition.LEADING]
    # The chapter number differs in every part, yet the block is still detected.
    assert leading and leading[0].seen_in_parts >= 6


def test_too_few_parts_yields_nothing() -> None:
    assert detect_boilerplate(BODIES[:2], min_parts=3) == []


def test_unique_bodies_yield_nothing() -> None:
    unique = [f"Completely different text number {n}." for n in range(6)]
    assert detect_boilerplate(unique) == []


def test_story_content_is_never_proposed_as_boilerplate() -> None:
    blocks = detect_boilerplate(BODIES)
    assert all("unique to chapter" not in b.block for b in blocks)


def test_apply_rules_only_strips_approved_blocks() -> None:
    rules = [
        CleaningRule(
            story_id=1,
            position=CleaningPosition.TRAILING,
            block="Posted weekly. See you next time.",
            seen_in_parts=7,
            approved=True,
        ),
        CleaningRule(
            story_id=1,
            position=CleaningPosition.LEADING,
            block="A Blue Fishcake production.",
            seen_in_parts=7,
            approved=False,
        ),
    ]
    result = apply_rules(body(3), rules)
    assert "See you next time" not in result
    assert "Blue Fishcake production" in result


def test_undecided_rules_are_not_applied() -> None:
    rules = [
        CleaningRule(
            story_id=1,
            position=CleaningPosition.TRAILING,
            block="Posted weekly. See you next time.",
            seen_in_parts=7,
            approved=None,
        )
    ]
    assert "See you next time" in apply_rules(body(3), rules)


def test_clean_combines_patterns_and_rules() -> None:
    text = body(3) + "\n\nSupport me on [Patreon](https://patreon.com/x)!"
    rules = [
        CleaningRule(
            story_id=1,
            position=CleaningPosition.TRAILING,
            block="Posted weekly. See you next time.",
            seen_in_parts=7,
            approved=True,
        )
    ]
    result = clean(text, rules)
    assert "patreon" not in result.lower()
    assert "See you next time" not in result
    assert "unique to chapter 3" in result


def test_clean_can_skip_pattern_stripping() -> None:
    text = body(3) + "\n\nSupport me on [Patreon](https://patreon.com/x)!"
    result = clean(text, [], strip_known_patterns=False)
    assert "patreon" in result.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_learned_cleaning.py -v`
Expected: FAIL with `ImportError: cannot import name 'detect_boilerplate'`

- [ ] **Step 3: Append the implementation to `cleaning.py`**

Add these imports at the top of `reddit_reader/cleaning.py`:

```python
from collections.abc import Sequence
from difflib import SequenceMatcher

from pydantic import BaseModel

from reddit_reader.models import CleaningPosition, CleaningRule
```

Append to the end of `reddit_reader/cleaning.py`:

```python
DEFAULT_WINDOW = 12
DEFAULT_MAJORITY = 0.6
DEFAULT_MIN_PARTS = 3

# Two lines count as "the same" boilerplate line above this similarity, which lets a
# header embedding a chapter number still match its counterparts in other parts.
LINE_MATCH_THRESHOLD = 0.7


class LearnedBlock(BaseModel):
    """A repeated header or footer discovered across a story's parts."""

    position: CleaningPosition
    block: str
    seen_in_parts: int


def _similar(left: str, right: str) -> bool:
    if not left.strip() and not right.strip():
        return True
    return SequenceMatcher(None, left.strip(), right.strip()).ratio() >= LINE_MATCH_THRESHOLD


def _edge_lines(text: str, window: int, *, trailing: bool) -> list[str]:
    lines = text.splitlines()
    return lines[-window:][::-1] if trailing else lines[:window]


def _longest_common_run(
    edges: Sequence[list[str]], majority: float
) -> tuple[list[str], int]:
    """Find the longest run of leading lines shared by at least `majority` of parts."""
    if not edges:
        return [], 0

    reference = edges[0]
    best_block: list[str] = []
    best_count = 0

    for length in range(len(reference), 0, -1):
        candidate = reference[:length]
        if not any(line.strip() for line in candidate):
            continue
        count = sum(
            1
            for other in edges
            if len(other) >= length
            and all(_similar(a, b) for a, b in zip(candidate, other[:length], strict=True))
        )
        if count / len(edges) >= majority:
            best_block, best_count = candidate, count
            break

    return best_block, best_count


def detect_boilerplate(
    bodies: Sequence[str],
    *,
    window: int = DEFAULT_WINDOW,
    majority: float = DEFAULT_MAJORITY,
    min_parts: int = DEFAULT_MIN_PARTS,
) -> list[LearnedBlock]:
    """Find repeated leading/trailing blocks across a story's parts.

    Repetition across two samples means nothing, so stories below `min_parts`
    return no suggestions at all.
    """
    if len(bodies) < min_parts:
        return []

    blocks: list[LearnedBlock] = []

    leading_edges = [_edge_lines(b, window, trailing=False) for b in bodies]
    leading_block, leading_count = _longest_common_run(leading_edges, majority)
    if leading_block:
        blocks.append(
            LearnedBlock(
                position=CleaningPosition.LEADING,
                block="\n".join(leading_block).strip(),
                seen_in_parts=leading_count,
            )
        )

    trailing_edges = [_edge_lines(b, window, trailing=True) for b in bodies]
    trailing_block, trailing_count = _longest_common_run(trailing_edges, majority)
    if trailing_block:
        blocks.append(
            LearnedBlock(
                position=CleaningPosition.TRAILING,
                block="\n".join(reversed(trailing_block)).strip(),
                seen_in_parts=trailing_count,
            )
        )

    return blocks


def apply_rules(selftext: str, rules: Sequence[CleaningRule]) -> str:
    """Remove blocks the user has explicitly approved. Never strips silently."""
    lines = selftext.splitlines()

    for rule in rules:
        if rule.approved is not True:
            continue
        block_lines = rule.block.splitlines()
        if not block_lines:
            continue

        if rule.position == CleaningPosition.LEADING:
            head = lines[: len(block_lines)]
            if len(head) == len(block_lines) and all(
                _similar(a, b) for a, b in zip(block_lines, head, strict=True)
            ):
                lines = lines[len(block_lines) :]
        else:
            tail = lines[-len(block_lines) :] if len(lines) >= len(block_lines) else []
            if tail and all(
                _similar(a, b) for a, b in zip(block_lines, tail, strict=True)
            ):
                lines = lines[: -len(block_lines)]

    return _BLANK_RUN_RE.sub("\n\n", "\n".join(lines)).strip()


def clean(
    selftext: str,
    rules: Sequence[CleaningRule],
    *,
    strip_known_patterns: bool = True,
) -> str:
    """Full render-time cleaning: approved learned rules, then pattern stripping."""
    text = apply_rules(selftext, rules)
    return strip_patterns(text) if strip_known_patterns else text
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_learned_cleaning.py -v`
Expected: PASS (11 tests)

If `_longest_common_run` proves too aggressive and captures a story line, raise `LINE_MATCH_THRESHOLD` — do not weaken the assertion in `test_story_content_is_never_proposed_as_boilerplate`.

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format . && uv run mypy reddit_reader
git add reddit_reader/cleaning.py tests/test_learned_cleaning.py
git commit -m "feat: learn per-story header/footer boilerplate by cross-part repetition"
```

---

### Task 16: Markdown and links export

**Files:**
- Create: `reddit_reader/export.py`
- Test: `tests/test_export.py`

**Interfaces:**
- Consumes: `Story`, `PostMeta`, `CleaningRule`; `OrderedPart`, `group_segments` from Task 8; `clean` from Task 15.
- Produces:
  - `export_filename(story: Story) -> str`
  - `part_heading(group: Sequence[OrderedPart]) -> str`
  - `render_markdown(story: Story, groups: Sequence[Sequence[OrderedPart]], bodies: Mapping[str, str], rules: Sequence[CleaningRule]) -> str`
  - `render_links(story: Story, groups: Sequence[Sequence[OrderedPart]]) -> str`
  - `write_export(path: Path, content: str) -> None`

**Rules from the spec:** regenerate the full file every time. Story title as H1. Boundary heading uses the part number when it has one and `part_label` otherwise, so unnumbered parts are never `Part None`. A part assembled from multiple segments gets one boundary and cites each segment's permalink. Filename is `<author>-<sanitized-title>[-<volume>].md`. The links export notes dead permalinks.

- [ ] **Step 1: Write the failing test**

Create `tests/test_export.py`:

```python
from datetime import UTC, datetime, timedelta
from pathlib import Path

from reddit_reader.export import (
    export_filename,
    part_heading,
    render_links,
    render_markdown,
    write_export,
)
from reddit_reader.models import PostMeta, Story
from reddit_reader.ordering import group_segments, resolve_order
from reddit_reader.titles import parse_title

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def post(post_id: str, title: str, *, days: int = 0, available: bool = True) -> PostMeta:
    return PostMeta(
        id=post_id,
        subreddit="HFY",
        author="BlueFishcake",
        title=title,
        permalink=f"/r/HFY/comments/{post_id}/x/",
        created_utc=BASE + timedelta(days=days),
        score=1,
        available=available,
    )


def a_story(**kwargs: object) -> Story:
    base: dict[str, object] = {
        "id": 1,
        "series_key": "bluefishcake:the long road",
        "title": "The Long Road",
        "author": "BlueFishcake",
    }
    base.update(kwargs)
    return Story(**base)  # type: ignore[arg-type]


def groups_for(*posts: PostMeta) -> list[list[object]]:
    ordered = resolve_order([(p, parse_title(p.title)) for p in posts])
    return group_segments(ordered)  # type: ignore[return-value]


def test_export_filename_includes_author_and_title() -> None:
    assert export_filename(a_story()) == "BlueFishcake-The-Long-Road.md"


def test_export_filename_includes_volume_when_present() -> None:
    assert export_filename(a_story(volume=2)) == "BlueFishcake-The-Long-Road-vol2.md"


def test_export_filename_sanitizes_unsafe_characters() -> None:
    name = export_filename(a_story(title="Road/Home: A Tale?"))
    assert "/" not in name
    assert ":" not in name
    assert "?" not in name


def test_numbered_part_heading_uses_the_number() -> None:
    heading = part_heading(groups_for(post("a", "Road - Part 12"))[0])  # type: ignore[arg-type]
    assert heading.startswith("## Part 12")


def test_named_part_heading_uses_the_label_not_part_none() -> None:
    heading = part_heading(groups_for(post("i", "Road - Interlude"))[0])  # type: ignore[arg-type]
    assert "Interlude" in heading
    assert "None" not in heading


def test_segmented_part_gets_one_heading_citing_both_sources() -> None:
    groups = groups_for(
        post("a", "Road - Chapter 12 (1/2)", days=0),
        post("b", "Road - Chapter 12 (2/2)", days=1),
    )
    assert len(groups) == 1
    heading = part_heading(groups[0])  # type: ignore[arg-type]
    assert heading.count("https://reddit.com") == 2


def test_markdown_has_story_title_as_h1() -> None:
    md = render_markdown(a_story(), groups_for(post("a", "Road - Part 1")), {"a": "Text."}, [])  # type: ignore[arg-type]
    assert md.startswith("# The Long Road")


def test_markdown_includes_body_text_in_order() -> None:
    groups = groups_for(post("b", "Road - Part 2", days=1), post("a", "Road - Part 1"))
    md = render_markdown(a_story(), groups, {"a": "First part.", "b": "Second part."}, [])  # type: ignore[arg-type]
    assert md.index("First part.") < md.index("Second part.")


def test_markdown_concatenates_segments_under_one_heading() -> None:
    groups = groups_for(
        post("a", "Road - Chapter 12 (1/2)", days=0),
        post("b", "Road - Chapter 12 (2/2)", days=1),
    )
    md = render_markdown(a_story(), groups, {"a": "Front half.", "b": "Back half."}, [])  # type: ignore[arg-type]
    assert md.count("## Part 12") == 1
    assert "Front half." in md and "Back half." in md


def test_markdown_applies_cleaning() -> None:
    body = "Story text.\n\nSupport me on [Patreon](https://patreon.com/x)!"
    md = render_markdown(a_story(), groups_for(post("a", "Road - Part 1")), {"a": body}, [])  # type: ignore[arg-type]
    assert "patreon" not in md.lower()
    assert "Story text." in md


def test_links_export_lists_permalinks_in_order() -> None:
    groups = groups_for(post("b", "Road - Part 2", days=1), post("a", "Road - Part 1"))
    links = render_links(a_story(), groups)  # type: ignore[arg-type]
    assert links.index("/comments/a/") < links.index("/comments/b/")


def test_links_export_flags_dead_permalinks() -> None:
    groups = groups_for(post("a", "Road - Part 1", available=False))
    assert "unavailable" in render_links(a_story(), groups).lower()  # type: ignore[arg-type]


def test_write_export_creates_parent_directories(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "out.md"
    write_export(target, "# Hello")
    assert target.read_text() == "# Hello"


def test_write_export_overwrites_in_place(tmp_path: Path) -> None:
    target = tmp_path / "out.md"
    write_export(target, "old")
    write_export(target, "new")
    assert target.read_text() == "new"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_export.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'reddit_reader.export'`

- [ ] **Step 3: Write the implementation**

Create `reddit_reader/export.py`:

```python
"""Render assembled stories to Markdown or a links index."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from reddit_reader.cleaning import clean
from reddit_reader.models import CleaningRule, Story
from reddit_reader.ordering import OrderedPart

_UNSAFE_RE = re.compile(r"[^\w\s-]")
_WS_RE = re.compile(r"\s+")


def _slug(text: str) -> str:
    return _WS_RE.sub("-", _UNSAFE_RE.sub("", text).strip())


def export_filename(story: Story) -> str:
    """`<author>-<sanitized-title>[-vol<N>].md`, qualified so same-named serials never collide."""
    parts = [_slug(story.author), _slug(story.title)]
    name = "-".join(p for p in parts if p)
    if story.volume is not None:
        name = f"{name}-vol{story.volume}"
    return f"{name}.md"


def _label(group: Sequence[OrderedPart]) -> str:
    lead = group[0]
    if lead.parsed.part_number is not None:
        number = lead.parsed.part_number.normalize()
        return f"Part {number}"
    if lead.parsed.part_label:
        return lead.parsed.part_label
    return lead.post.title


def part_heading(group: Sequence[OrderedPart]) -> str:
    """A boundary heading naming the part and citing every source post."""
    sources = " ".join(f"[source]({part.post.url})" for part in group)
    posted = group[0].post.created_utc.date().isoformat()
    return f"## {_label(group)} — {sources} — posted {posted}"


def render_markdown(
    story: Story,
    groups: Sequence[Sequence[OrderedPart]],
    bodies: Mapping[str, str],
    rules: Sequence[CleaningRule],
) -> str:
    """Regenerate the complete story file from scratch."""
    chunks: list[str] = [f"# {story.title}", f"*by {story.author}*"]

    for group in groups:
        chunks.append(part_heading(group))
        segment_texts = [
            clean(bodies.get(part.post.id, ""), rules)
            for part in group
        ]
        chunks.append("\n\n".join(t for t in segment_texts if t))

    return "\n\n".join(chunk for chunk in chunks if chunk).strip() + "\n"


def render_links(story: Story, groups: Sequence[Sequence[OrderedPart]]) -> str:
    """A lightweight reading index of permalinks, flagging any that are dead."""
    lines: list[str] = [f"# {story.title}", f"*by {story.author}*", ""]

    for group in groups:
        for part in group:
            note = "" if part.post.available else "  *(unavailable — post removed)*"
            lines.append(f"- {_label(group)}: [{part.post.title}]({part.post.url}){note}")

    return "\n".join(lines).strip() + "\n"


def write_export(path: Path, content: str) -> None:
    """Write `content` to `path`, creating parents and overwriting in place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_export.py -v`
Expected: PASS (14 tests)

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format . && uv run mypy reddit_reader
git add reddit_reader/export.py tests/test_export.py
git commit -m "feat: render stories to markdown and links exports"
```

---

## ✅ Checkpoint D — Cleaning and export complete

Run `uv run pytest -v`, `uv run ruff check .`, `uv run mypy reddit_reader`. All must pass.

---

# Layer 5 — Config, Service Layer, and CLI

The service layer is what binds storage, detection, and the Reddit client into application operations. Both the CLI and the TUI call it, so neither contains business logic.

**Checkpoint E** at the end: a fully working non-interactive tool — fetch, list, export — with no TUI yet.

### Task 17: Layered configuration

**Files:**
- Create: `reddit_reader/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Settings` (pydantic-settings model) and `load_settings(cli_overrides: Mapping[str, object] | None = None, config_path: Path | None = None) -> Settings`, plus `build_reddit(settings: Settings) -> praw.Reddit`.

**Settings fields (all overridable at every layer):** `subreddits: list[str]`, `praw_site: str`, `database_path: Path`, `export_dir: Path`, `listing: ListingType`, `time_window: TimeWindow`, `fetch_limit: int`, `cleaning_enabled: bool`, `cleaning_window: int`, `cleaning_majority: float`, `cleaning_min_parts: int`, `stale_after_days: int`, `attach_threshold: float`, `dedupe_window_hours: int`.

**Rules from the spec:** precedence is **CLI flags > config file > environment variables**. `praw.ini` supplies credentials and `praw_site` selects the named section. Subreddit list order also sets canonical-copy priority for duplicate collapsing.

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
from pathlib import Path

import pytest

from reddit_reader.config import Settings, load_settings


def write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(body)
    return path


def test_defaults_are_usable_with_no_config() -> None:
    settings = load_settings()
    assert settings.listing == "new"
    assert settings.fetch_limit > 0
    assert settings.attach_threshold == pytest.approx(0.85)


def test_config_file_overrides_defaults(tmp_path: Path) -> None:
    path = write_config(tmp_path, 'subreddits = ["HFY", "Sexyspacebabes"]\nfetch_limit = 25\n')
    settings = load_settings(config_path=path)
    assert settings.subreddits == ["HFY", "Sexyspacebabes"]
    assert settings.fetch_limit == 25


def test_env_var_is_used_when_config_file_is_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REDDIT_READER_FETCH_LIMIT", "77")
    assert load_settings().fetch_limit == 77


def test_config_file_beats_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDDIT_READER_FETCH_LIMIT", "77")
    path = write_config(tmp_path, "fetch_limit = 25\n")
    assert load_settings(config_path=path).fetch_limit == 25


def test_cli_override_beats_config_file(tmp_path: Path) -> None:
    path = write_config(tmp_path, "fetch_limit = 25\n")
    settings = load_settings({"fetch_limit": 5}, config_path=path)
    assert settings.fetch_limit == 5


def test_cli_override_beats_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDDIT_READER_FETCH_LIMIT", "77")
    assert load_settings({"fetch_limit": 5}).fetch_limit == 5


def test_none_cli_overrides_are_ignored(tmp_path: Path) -> None:
    path = write_config(tmp_path, "fetch_limit = 25\n")
    settings = load_settings({"fetch_limit": None}, config_path=path)
    assert settings.fetch_limit == 25


def test_subreddits_accept_a_comma_separated_string() -> None:
    settings = Settings(subreddits="HFY, Sexyspacebabes")  # type: ignore[arg-type]
    assert settings.subreddits == ["HFY", "Sexyspacebabes"]


def test_subreddit_order_is_preserved_for_dedupe_priority() -> None:
    settings = Settings(subreddits=["First", "Second"])
    assert settings.subreddits[0] == "First"


def test_paths_expand_user(tmp_path: Path) -> None:
    settings = Settings(database_path="~/rr.db")  # type: ignore[arg-type]
    assert "~" not in str(settings.database_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'reddit_reader.config'`

- [ ] **Step 3: Write the implementation**

Create `reddit_reader/config.py`:

```python
"""Layered configuration: CLI flags > config file > environment variables."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from reddit_reader.reddit_client import ListingType, TimeWindow

DEFAULT_CONFIG_PATH = Path("~/.config/reddit-reader/config.toml").expanduser()


class Settings(BaseSettings):
    """Every user-facing option, resolved once at startup."""

    model_config = SettingsConfigDict(
        env_prefix="REDDIT_READER_",
        extra="ignore",
    )

    subreddits: list[str] = Field(default_factory=lambda: ["HFY"])
    praw_site: str = "default"
    database_path: Path = Path("~/.local/share/reddit-reader/library.db")
    export_dir: Path = Path("~/reddit-reader-exports")

    listing: ListingType = "new"
    time_window: TimeWindow = "all"
    fetch_limit: int = 100

    cleaning_enabled: bool = True
    cleaning_window: int = 12
    cleaning_majority: float = 0.6
    cleaning_min_parts: int = 3

    stale_after_days: int = 180
    attach_threshold: float = 0.85
    dedupe_window_hours: int = 48

    @field_validator("subreddits", mode="before")
    @classmethod
    def _split_subreddits(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("database_path", "export_dir", mode="after")
    @classmethod
    def _expand(cls, value: Path) -> Path:
        return value.expanduser()


def _read_config_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def load_settings(
    cli_overrides: Mapping[str, object] | None = None,
    config_path: Path | None = None,
) -> Settings:
    """Resolve settings with CLI flags winning over the config file, which wins over env."""
    file_values = _read_config_file(config_path or DEFAULT_CONFIG_PATH)
    cli_values = {k: v for k, v in (cli_overrides or {}).items() if v is not None}

    # BaseSettings reads env vars for anything not passed explicitly, so passing
    # file and CLI values as kwargs gives exactly the required precedence.
    return Settings(**{**file_values, **cli_values})


def build_reddit(settings: Settings) -> Any:
    """Construct a PRAW client from the selected praw.ini profile."""
    import praw

    return praw.Reddit(site_name=settings.praw_site)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format . && uv run mypy reddit_reader
git add reddit_reader/config.py tests/test_config.py
git commit -m "feat: add layered settings with CLI > file > env precedence"
```

---

### Task 18: Service layer — fetch, detect, track

**Files:**
- Create: `reddit_reader/service.py`
- Test: `tests/test_service_fetch.py`

**Interfaces:**
- Consumes: everything from Layers 1-4.
- Produces:
  - `FetchResult` (pydantic model: `fetched: int`, `auto_attached: int`, `candidates: list[DetectionMatch]`)
  - `ReaderService(settings, posts, stories, search, client)` with:
    - `fetch(subreddits: Sequence[str] | None = None) -> FetchResult`
    - `commit_match(match: DetectionMatch) -> int`
    - `track(story_id: int) -> int` (returns bodies fetched)
    - `untrack(story_id: int) -> int` (returns bodies dropped)
    - `story_status(story: Story) -> StoryStatus`
    - `unread_count(story_id: int) -> int`
    - `newly_filled(story_id: int) -> list[StoryPart]`
    - `mark_read(story_id: int, post_id: str, offset: float) -> None`
    - `nav_link_expansion(story_id: int) -> list[str]` — the spec's nav-link verification pass, which runs **only on tracked stories** (bodies are already local, so it costs no API calls) automatically when a story is first tracked and again whenever new parts attach. Returns post ids the nav chain references that aren't in the story yet; they are surfaced as candidates, never silently added.

- [ ] **Step 1: Write the failing test**

Create `tests/test_service_fetch.py`:

```python
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from reddit_reader.config import Settings
from reddit_reader.models import StoryStatus
from reddit_reader.reddit_client import RedditClient
from reddit_reader.service import ReaderService
from reddit_reader.storage import PostRepository, SearchIndex, StoryRepository, connect
from tests.fakes import FakeReddit, make_submission


@pytest.fixture
def service(tmp_path: Path) -> ReaderService:
    conn = connect(tmp_path / "t.db")
    reddit = FakeReddit(
        submissions=[
            make_submission("a1", "The Long Road - Part 1", created_days=0),
            make_submission("a2", "The Long Road - Part 2", created_days=7),
            make_submission("a3", "The Long Road - Part 3", created_days=14),
        ]
    )
    return ReaderService(
        settings=Settings(subreddits=["HFY"], export_dir=tmp_path / "out"),
        posts=PostRepository(conn),
        stories=StoryRepository(conn),
        search=SearchIndex(conn),
        client=RedditClient(reddit),
    )


def test_fetch_stores_post_metadata(service: ReaderService) -> None:
    result = service.fetch()
    assert result.fetched == 3
    assert service.posts.get_meta("a1") is not None


def test_fetch_does_not_store_bodies(service: ReaderService) -> None:
    service.fetch()
    assert service.posts.get_body("a1") is None


def test_fetch_indexes_titles_for_search(service: ReaderService) -> None:
    service.fetch()
    assert service.search.search("Long Road")


def test_fetch_produces_a_candidate_series(service: ReaderService) -> None:
    result = service.fetch()
    assert len(result.candidates) == 1
    assert len(result.candidates[0].post_ids) == 3


def test_commit_match_creates_a_story_with_parts(service: ReaderService) -> None:
    match = service.fetch().candidates[0]
    story_id = service.commit_match(match)
    assert service.stories.get(story_id) is not None
    assert len(service.stories.parts(story_id)) == 3


def test_committed_story_records_series_key_and_author(service: ReaderService) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    story = service.stories.get(story_id)
    assert story is not None
    assert story.author == "BlueFishcake"
    assert story.series_key.startswith("bluefishcake:")


def test_second_fetch_auto_attaches_a_new_part(service: ReaderService) -> None:
    service.commit_match(service.fetch().candidates[0])
    service.client._reddit.submissions.append(  # type: ignore[attr-defined]
        make_submission("a4", "The Long Road - Part 4", created_days=21)
    )
    result = service.fetch()
    assert result.auto_attached == 1


def test_auto_attached_part_joins_the_existing_story(service: ReaderService) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    service.client._reddit.submissions.append(  # type: ignore[attr-defined]
        make_submission("a4", "The Long Road - Part 4", created_days=21)
    )
    service.fetch()
    assert len(service.stories.parts(story_id)) == 4


def test_new_volume_does_not_attach_to_the_previous_book(service: ReaderService) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    service.client._reddit.submissions.append(  # type: ignore[attr-defined]
        make_submission("b1", "The Long Road, Book Two, Chapter 1", created_days=30)
    )
    result = service.fetch()
    assert result.auto_attached == 0
    assert len(service.stories.parts(story_id)) == 3


def test_track_fetches_bodies_and_indexes_them(service: ReaderService) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    assert service.track(story_id) == 3
    assert service.posts.get_body("a1") is not None
    story = service.stories.get(story_id)
    assert story is not None
    assert story.tracked is True


def test_untrack_drops_bodies_and_search_entries(service: ReaderService) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)
    assert service.untrack(story_id) == 3
    assert service.posts.get_body("a1") is None
    story = service.stories.get(story_id)
    assert story is not None
    assert story.tracked is False


def test_untrack_keeps_the_story_and_read_position(service: ReaderService) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)
    service.mark_read(story_id, "a2", 0.5)
    service.untrack(story_id)
    story = service.stories.get(story_id)
    assert story is not None
    assert story.last_read_part == "a2"


def test_unread_count_is_derived_from_read_position(service: ReaderService) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    service.mark_read(story_id, "a1", 1.0)
    assert service.unread_count(story_id) == 2


def test_unread_count_is_everything_when_nothing_read(service: ReaderService) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    assert service.unread_count(story_id) == 3


def test_story_status_is_stale_for_old_serials(service: ReaderService) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    story = service.stories.get(story_id)
    assert story is not None
    service.settings.stale_after_days = 1
    assert service.story_status(story) == StoryStatus.STALE


def test_story_status_is_ongoing_for_recent_serials(
    service: ReaderService, tmp_path: Path
) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    story = service.stories.get(story_id)
    assert story is not None
    service.settings.stale_after_days = 100_000
    assert service.story_status(story) == StoryStatus.ONGOING


def test_story_status_is_complete_when_a_title_says_so(service: ReaderService) -> None:
    service.client._reddit.submissions.append(  # type: ignore[attr-defined]
        make_submission("z9", "The Long Road - Part 4 [Complete]", created_days=21)
    )
    story_id = service.commit_match(service.fetch().candidates[0])
    story = service.stories.get(story_id)
    assert story is not None
    assert service.story_status(story) == StoryStatus.COMPLETE


def test_nav_expansion_finds_a_part_the_titles_missed(service: ReaderService) -> None:
    # An inconsistently titled chapter that title matching cannot group,
    # but which part 3's Next link points at.
    service.client._reddit.submissions.append(  # type: ignore[attr-defined]
        make_submission("odd1", "A Detour", created_days=21)
    )
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)
    service.posts.set_body(
        __import__("reddit_reader.models", fromlist=["PostBody"]).PostBody(
            post_id="a3",
            selftext="End of chapter.\n\n[Next](https://www.reddit.com/r/HFY/comments/odd1/x/)",
        )
    )
    assert service.nav_link_expansion(story_id) == ["odd1"]


def test_nav_expansion_ignores_parts_already_in_the_story(service: ReaderService) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)
    service.posts.set_body(
        __import__("reddit_reader.models", fromlist=["PostBody"]).PostBody(
            post_id="a1",
            selftext="[Next](https://www.reddit.com/r/HFY/comments/a2/x/)",
        )
    )
    assert service.nav_link_expansion(story_id) == []


def test_nav_expansion_is_empty_for_untracked_stories(service: ReaderService) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    assert service.nav_link_expansion(story_id) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_service_fetch.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'reddit_reader.service'`

- [ ] **Step 3: Write the implementation**

Create `reddit_reader/service.py`:

```python
"""Application operations binding storage, detection, and the Reddit client.

Both the CLI and the TUI call into here, so neither holds business logic.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import BaseModel

from reddit_reader.config import Settings
from reddit_reader.detection import (
    decide_attachment,
    group_posts,
    series_key,
)
from reddit_reader.models import (
    DetectionMatch,
    PostMeta,
    Story,
    StoryPart,
    StoryStatus,
)
from reddit_reader.navlinks import parse_nav_links
from reddit_reader.ordering import OrderedPart, group_segments, resolve_order
from reddit_reader.reddit_client import RedditClient
from reddit_reader.storage import PostRepository, SearchIndex, StoryRepository
from reddit_reader.titles import parse_title

COMPLETION_MARKERS = ("[complete]", "[final]", "[fin]", "the end")


class FetchResult(BaseModel):
    """What a fetch produced: raw counts plus candidates needing curation."""

    fetched: int
    auto_attached: int
    candidates: list[DetectionMatch]


class ReaderService:
    """Every operation the UI layers need."""

    def __init__(
        self,
        settings: Settings,
        posts: PostRepository,
        stories: StoryRepository,
        search: SearchIndex,
        client: RedditClient,
    ) -> None:
        self.settings = settings
        self.posts = posts
        self.stories = stories
        self.search = search
        self.client = client

    # ---- fetching and detection -------------------------------------------------

    def fetch(self, subreddits: Sequence[str] | None = None) -> FetchResult:
        """Fetch listings, store metadata, auto-attach known parts, return candidates."""
        targets = list(subreddits or self.settings.subreddits)
        collected: list[PostMeta] = []

        for subreddit in targets:
            collected.extend(
                self.client.fetch_listing(
                    subreddit,
                    self.settings.listing,
                    self.settings.fetch_limit,
                    self.settings.time_window,
                )
            )

        self.posts.upsert_many(collected)
        for post in collected:
            self.search.index_title(post)

        matches = group_posts(collected, self.settings.subreddits)

        auto_attached = 0
        candidates: list[DetectionMatch] = []

        for match in matches:
            existing = self.stories.find_committed(
                series_key(match.author, match.base_title), match.volume
            )
            decision = decide_attachment(match, existing, self.settings.attach_threshold)

            if decision.action == "auto_attach" and decision.story_id is not None:
                auto_attached += self.attach_parts(decision.story_id, match)
            else:
                match.existing_story_id = decision.story_id
                candidates.append(match)

        return FetchResult(
            fetched=len(collected), auto_attached=auto_attached, candidates=candidates
        )

    def attach_parts(self, story_id: int, match: DetectionMatch) -> int:
        """Add any of `match`'s posts not already in the story. Returns how many."""
        known = set(self.stories.part_post_ids(story_id))
        new_ids = [post_id for post_id in match.post_ids if post_id not in known]
        if not new_ids:
            return 0

        story = self.stories.get(story_id)
        read_key = self._read_sort_key(story_id) if story else None

        for part in self._build_parts(story_id, match.post_ids, match.confidence):
            if part.post_id not in new_ids:
                continue
            # A part landing behind the read position can never be flagged unread by
            # derivation, so mark it explicitly.
            if read_key is not None and part.sort_key is not None and part.sort_key < read_key:
                part.newly_filled = True
            self.stories.add_part(part)
            if story and story.tracked:
                self._cache_body(part.post_id)

        if story:
            story.last_updated_at = datetime.now(UTC)
            self.stories.update(story)
            if story.tracked:
                # New parts arrived: re-run the nav pass over the enlarged story.
                self.nav_link_expansion(story_id)

        return len(new_ids)

    def _build_parts(
        self, story_id: int, post_ids: Sequence[str], confidence: float
    ) -> list[StoryPart]:
        metas = self.posts.get_many(list(post_ids))
        ordered = resolve_order([(m, parse_title(m.title)) for m in metas])
        return [
            StoryPart(
                post_id=item.post.id,
                story_id=story_id,
                part_number=item.parsed.part_number,
                part_label=item.parsed.part_label,
                segment=item.parsed.segment,
                segment_count=item.parsed.segment_count,
                sort_key=item.sort_key,
                match_confidence=confidence,
            )
            for item in ordered
        ]

    def commit_match(self, match: DetectionMatch) -> int:
        """Turn a curated candidate into a committed story."""
        story_id = self.stories.create(
            Story(
                id=0,
                series_key=series_key(match.author, match.base_title),
                title=match.base_title.title(),
                author=match.author,
                volume=match.volume,
                last_updated_at=datetime.now(UTC),
            )
        )
        for part in self._build_parts(story_id, match.post_ids, match.confidence):
            self.stories.add_part(part)
        return story_id

    # ---- tracking ---------------------------------------------------------------

    def _cache_body(self, post_id: str) -> None:
        for body in self.client.fetch_bodies([post_id]):
            self.posts.set_body(body)
            self.search.index_body(body.post_id, body.selftext)

    def track(self, story_id: int) -> int:
        """Track a story: eagerly cache every known part's body."""
        story = self.stories.get(story_id)
        if story is None:
            return 0

        post_ids = self.stories.part_post_ids(story_id)
        bodies = self.client.fetch_bodies(post_ids)
        for body in bodies:
            self.posts.set_body(body)
            self.search.index_body(body.post_id, body.selftext)

        # Anything we asked for and did not get back is gone upstream.
        returned = {b.post_id for b in bodies}
        for post_id in post_ids:
            if post_id not in returned:
                self.posts.mark_unavailable(post_id)

        story.tracked = True
        self.stories.update(story)

        # Bodies are local now, so the nav-link pass costs nothing but CPU.
        self.nav_link_expansion(story_id)
        return len(bodies)

    def nav_link_expansion(self, story_id: int) -> list[str]:
        """Follow First/Prev/Next chains in cached bodies to find parts titles missed.

        Runs only on tracked stories, where bodies are already cached. Returns
        candidate post ids — they are never silently added to the story.
        """
        story = self.stories.get(story_id)
        if story is None or not story.tracked:
            return []

        known = set(self.stories.part_post_ids(story_id))
        referenced: list[str] = []

        for post_id in known:
            body = self.posts.get_body(post_id)
            if body is None:
                continue
            links = parse_nav_links(body.selftext)
            for candidate in (links.first, links.previous, links.next):
                if candidate and candidate not in known and candidate not in referenced:
                    referenced.append(candidate)

        # Pull metadata for anything not already cached so it can be reviewed.
        for candidate in referenced:
            if self.posts.get_meta(candidate) is None:
                for meta in self.client.search(candidate, limit=1):
                    self.posts.upsert_meta(meta)
                    self.search.index_title(meta)

        return referenced

    def untrack(self, story_id: int) -> int:
        """Stop tracking: drop cached bodies and their search entries, keep the story."""
        post_ids = self.stories.part_post_ids(story_id)
        dropped = self.posts.delete_bodies(post_ids)
        for post_id in post_ids:
            self.search.remove_body(post_id)

        story = self.stories.get(story_id)
        if story:
            story.tracked = False
            self.stories.update(story)
        return dropped

    # ---- reading state ----------------------------------------------------------

    def ordered_parts(self, story_id: int) -> list[OrderedPart]:
        metas = self.posts.get_many(self.stories.part_post_ids(story_id))
        return resolve_order([(m, parse_title(m.title)) for m in metas])

    def ordered_groups(self, story_id: int) -> list[list[OrderedPart]]:
        return group_segments(self.ordered_parts(story_id))

    def _read_sort_key(self, story_id: int) -> str | None:
        story = self.stories.get(story_id)
        if story is None or story.last_read_part is None:
            return None
        for part in self.ordered_parts(story_id):
            if part.post.id == story.last_read_part:
                return part.sort_key
        return None

    def unread_count(self, story_id: int) -> int:
        """Parts ordering after the read position. Derived, never stored."""
        parts = self.ordered_parts(story_id)
        read_key = self._read_sort_key(story_id)
        if read_key is None:
            return len(parts)
        return sum(1 for part in parts if part.sort_key > read_key)

    def newly_filled(self, story_id: int) -> list[StoryPart]:
        """Backfilled parts sitting behind the read position, which unread can't catch."""
        return [part for part in self.stories.parts(story_id) if part.newly_filled]

    def mark_read(self, story_id: int, post_id: str, offset: float) -> None:
        story = self.stories.get(story_id)
        if story is None:
            return
        story.last_read_part = post_id
        story.last_read_offset = offset
        self.stories.update(story)
        self.stories.clear_newly_filled(story_id, post_id)

    # ---- status -----------------------------------------------------------------

    def story_status(self, story: Story) -> StoryStatus:
        """Derived from explicit completion markers, else the newest part's age."""
        metas = self.posts.get_many(self.stories.part_post_ids(story.id))
        if not metas:
            return StoryStatus.STALE

        for meta in metas:
            lowered = meta.title.lower()
            if any(marker in lowered for marker in COMPLETION_MARKERS):
                return StoryStatus.COMPLETE

        newest = max(meta.created_utc for meta in metas)
        age_days = (datetime.now(UTC) - newest).days
        return (
            StoryStatus.STALE
            if age_days > self.settings.stale_after_days
            else StoryStatus.ONGOING
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_service_fetch.py -v`
Expected: PASS (20 tests)

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format . && uv run mypy reddit_reader
git add reddit_reader/service.py tests/test_service_fetch.py
git commit -m "feat: add service layer for fetch, detection, tracking, and read state"
```

---

### Task 19: Service layer — gaps, backfill, export, storage management

**Files:**
- Modify: `reddit_reader/service.py`
- Test: `tests/test_service_ops.py`

**Interfaces:**
- Consumes: Task 18's `ReaderService`.
- Produces (added to `ReaderService`):
  - `gaps(story_id: int) -> list[Decimal]`
  - `find_missing_parts(story_id: int) -> list[DetectionMatch]`
  - `mark_unavailable(story_id: int, part_number: Decimal, auto: bool = False) -> None`
  - `clear_unavailable(story_id: int, part_number: Decimal) -> None`
  - `export_story(story_id: int) -> Path`
  - `export_links_file(story_id: int) -> Path`
  - `search_local(query: str, limit: int = 50) -> list[PostMeta]`
  - `search_live(query: str, subreddit: str | None = None, limit: int = 50) -> list[PostMeta]`
  - `delete_story(story_id: int) -> None`
  - `prune_orphans() -> int`
  - `StorageUsage` (pydantic model: `total_bytes: int`, `body_bytes: int`, `post_count: int`, `body_count: int`) and `storage_usage() -> StorageUsage`
  - `propose_cleaning_rules(story_id: int) -> list[CleaningRule]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_service_ops.py`:

```python
from decimal import Decimal
from pathlib import Path

import pytest

from reddit_reader.config import Settings
from reddit_reader.reddit_client import RedditClient
from reddit_reader.service import ReaderService
from reddit_reader.storage import PostRepository, SearchIndex, StoryRepository, connect
from tests.fakes import FakeReddit, make_submission


def build(tmp_path: Path, *submissions: object) -> ReaderService:
    conn = connect(tmp_path / "t.db")
    return ReaderService(
        settings=Settings(subreddits=["HFY"], export_dir=tmp_path / "out"),
        posts=PostRepository(conn),
        stories=StoryRepository(conn),
        search=SearchIndex(conn),
        client=RedditClient(FakeReddit(submissions=list(submissions))),  # type: ignore[arg-type]
    )


@pytest.fixture
def gapped(tmp_path: Path) -> ReaderService:
    return build(
        tmp_path,
        make_submission("a1", "Road - Part 1", created_days=0),
        make_submission("a3", "Road - Part 3", created_days=14),
    )


def test_gaps_reports_the_missing_number(gapped: ReaderService) -> None:
    story_id = gapped.commit_match(gapped.fetch().candidates[0])
    assert gapped.gaps(story_id) == [Decimal("2")]


def test_marking_unavailable_suppresses_the_gap(gapped: ReaderService) -> None:
    story_id = gapped.commit_match(gapped.fetch().candidates[0])
    gapped.mark_unavailable(story_id, Decimal("2"))
    assert gapped.gaps(story_id) == []


def test_clearing_the_mark_restores_the_gap(gapped: ReaderService) -> None:
    story_id = gapped.commit_match(gapped.fetch().candidates[0])
    gapped.mark_unavailable(story_id, Decimal("2"))
    gapped.clear_unavailable(story_id, Decimal("2"))
    assert gapped.gaps(story_id) == [Decimal("2")]


def test_find_missing_parts_recovers_a_part_from_author_history(tmp_path: Path) -> None:
    service = build(
        tmp_path,
        make_submission("a1", "Road - Part 1", created_days=0),
        make_submission("a3", "Road - Part 3", created_days=14),
    )
    story_id = service.commit_match(service.fetch().candidates[0])
    # Part 2 exists on Reddit but was outside the fetch window.
    service.client._reddit.submissions.append(  # type: ignore[attr-defined]
        make_submission("a2", "Road - Part 2", created_days=7)
    )
    matches = service.find_missing_parts(story_id)
    assert any("a2" in m.post_ids for m in matches)


def test_failed_backfill_auto_marks_the_gap_unavailable(gapped: ReaderService) -> None:
    story_id = gapped.commit_match(gapped.fetch().candidates[0])
    gapped.find_missing_parts(story_id)
    assert gapped.gaps(story_id) == []


def test_export_story_writes_a_markdown_file(tmp_path: Path) -> None:
    service = build(tmp_path, make_submission("a1", "Road - Part 1"))
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)
    path = service.export_story(story_id)
    assert path.exists()
    assert path.read_text().startswith("# ")


def test_export_records_the_path_on_the_story(tmp_path: Path) -> None:
    service = build(tmp_path, make_submission("a1", "Road - Part 1"))
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)
    path = service.export_story(story_id)
    story = service.stories.get(story_id)
    assert story is not None
    assert story.exported_markdown_path == str(path)
    assert story.exported_at is not None


def test_reexport_overwrites_the_same_file(tmp_path: Path) -> None:
    service = build(tmp_path, make_submission("a1", "Road - Part 1"))
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)
    first = service.export_story(story_id)
    second = service.export_story(story_id)
    assert first == second


def test_export_links_writes_a_links_file(tmp_path: Path) -> None:
    service = build(tmp_path, make_submission("a1", "Road - Part 1"))
    story_id = service.commit_match(service.fetch().candidates[0])
    path = service.export_links_file(story_id)
    assert "reddit.com" in path.read_text()


def test_search_local_finds_cached_titles(tmp_path: Path) -> None:
    service = build(tmp_path, make_submission("a1", "The Long Road - Part 1"))
    service.fetch()
    assert [p.id for p in service.search_local("Long Road")] == ["a1"]


def test_search_live_returns_and_caches_results(tmp_path: Path) -> None:
    service = build(tmp_path, make_submission("a1", "The Long Road - Part 1"))
    found = service.search_live("Long Road", subreddit="HFY")
    assert [p.id for p in found] == ["a1"]
    assert service.posts.get_meta("a1") is not None


def test_delete_story_removes_it_but_keeps_post_metadata(tmp_path: Path) -> None:
    service = build(tmp_path, make_submission("a1", "Road - Part 1"))
    story_id = service.commit_match(service.fetch().candidates[0])
    service.delete_story(story_id)
    assert service.stories.get(story_id) is None
    assert service.posts.get_meta("a1") is not None


def test_prune_orphans_clears_ungrouped_metadata(tmp_path: Path) -> None:
    service = build(
        tmp_path,
        make_submission("a1", "Road - Part 1"),
        make_submission("z9", "Unrelated one-shot", created_days=1),
    )
    result = service.fetch()
    match = next(m for m in result.candidates if "a1" in m.post_ids)
    service.commit_match(match)
    assert service.prune_orphans() == 1
    assert service.posts.get_meta("z9") is None
    assert service.posts.get_meta("a1") is not None


def test_storage_usage_reports_counts(tmp_path: Path) -> None:
    service = build(tmp_path, make_submission("a1", "Road - Part 1"))
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)
    usage = service.storage_usage()
    assert usage.post_count == 1
    assert usage.body_count == 1
    assert usage.total_bytes > 0


def test_propose_cleaning_rules_needs_enough_parts(tmp_path: Path) -> None:
    service = build(tmp_path, make_submission("a1", "Road - Part 1"))
    story_id = service.commit_match(service.fetch().candidates[0])
    service.track(story_id)
    assert service.propose_cleaning_rules(story_id) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_service_ops.py -v`
Expected: FAIL with `AttributeError: 'ReaderService' object has no attribute 'gaps'`

- [ ] **Step 3: Append the implementation to `service.py`**

Add these imports at the top of `reddit_reader/service.py`:

```python
from decimal import Decimal
from pathlib import Path

from reddit_reader.cleaning import detect_boilerplate
from reddit_reader.detection import find_gaps
from reddit_reader.export import (
    export_filename,
    render_links,
    render_markdown,
    write_export,
)
from reddit_reader.models import CleaningRule, UnavailablePart
```

Append this class to the end of `reddit_reader/service.py`:

```python
class StorageUsage(BaseModel):
    """How much disk the local cache is using."""

    total_bytes: int
    body_bytes: int
    post_count: int
    body_count: int
```

Append these methods to `ReaderService` (same indentation as `story_status`):

```python
    # ---- gaps and backfill ------------------------------------------------------

    def gaps(self, story_id: int) -> list[Decimal]:
        """Interior gaps and a missing start, minus anything known unavailable."""
        numbers = [
            part.part_number
            for part in self.stories.parts(story_id)
            if part.part_number is not None
        ]
        unavailable = [rec.part_number for rec in self.stories.unavailable(story_id)]
        return find_gaps(numbers, unavailable)

    def mark_unavailable(
        self, story_id: int, part_number: Decimal, auto: bool = False
    ) -> None:
        self.stories.add_unavailable(
            UnavailablePart(story_id=story_id, part_number=part_number, auto_marked=auto)
        )

    def clear_unavailable(self, story_id: int, part_number: Decimal) -> None:
        self.stories.clear_unavailable(story_id, part_number)

    def find_missing_parts(self, story_id: int) -> list[DetectionMatch]:
        """Pull author history to backfill gaps. Only meaningful when gaps exist."""
        missing = self.gaps(story_id)
        if not missing:
            return []

        story = self.stories.get(story_id)
        if story is None:
            return []

        history = self.client.author_submissions(story.author)
        self.posts.upsert_many(history)
        for post in history:
            self.search.index_title(post)

        known = set(self.stories.part_post_ids(story_id))
        target_key = series_key(story.author, story.title.lower())

        candidates: list[DetectionMatch] = []
        found_numbers: set[Decimal] = set()

        for match in group_posts(history, self.settings.subreddits):
            if series_key(match.author, match.base_title) != target_key:
                continue
            if match.volume != story.volume:
                continue
            new_ids = [pid for pid in match.post_ids if pid not in known]
            if not new_ids:
                continue
            match.post_ids = new_ids
            match.existing_story_id = story_id
            candidates.append(match)
            for meta in self.posts.get_many(new_ids):
                parsed = parse_title(meta.title)
                if parsed.part_number is not None:
                    found_numbers.add(parsed.part_number)

        # Anything the author's full history could not produce is unfillable.
        for number in missing:
            if number not in found_numbers:
                self.mark_unavailable(story_id, number, auto=True)

        return candidates

    # ---- export -----------------------------------------------------------------

    def _rules_for(self, story_id: int) -> list[CleaningRule]:
        if not self.settings.cleaning_enabled:
            return []
        return self.stories.cleaning_rules(story_id)

    def export_story(self, story_id: int) -> Path:
        """Regenerate the story's full markdown file, overwriting in place."""
        story = self.stories.get(story_id)
        if story is None:
            raise ValueError(f"no story with id {story_id}")

        groups = self.ordered_groups(story_id)
        bodies = {
            post_id: body.selftext
            for post_id in self.stories.part_post_ids(story_id)
            if (body := self.posts.get_body(post_id)) is not None
        }

        content = render_markdown(story, groups, bodies, self._rules_for(story_id))
        path = self.settings.export_dir / export_filename(story)
        write_export(path, content)

        story.exported_markdown_path = str(path)
        story.exported_at = datetime.now(UTC)
        self.stories.update(story)
        return path

    def export_links_file(self, story_id: int) -> Path:
        story = self.stories.get(story_id)
        if story is None:
            raise ValueError(f"no story with id {story_id}")

        content = render_links(story, self.ordered_groups(story_id))
        path = self.settings.export_dir / export_filename(story).replace(".md", "-links.md")
        write_export(path, content)
        return path

    # ---- search -----------------------------------------------------------------

    def search_local(self, query: str, limit: int = 50) -> list[PostMeta]:
        return self.posts.get_many(self.search.search(query, limit))

    def search_live(
        self, query: str, subreddit: str | None = None, limit: int = 50
    ) -> list[PostMeta]:
        """Search Reddit directly, merging results into the local cache."""
        found = self.client.search(query, subreddit, limit)
        self.posts.upsert_many(found)
        for post in found:
            self.search.index_title(post)
        return found

    # ---- storage management -----------------------------------------------------

    def delete_story(self, story_id: int) -> None:
        """Remove a story and its annotations; PostMeta survives for re-detection."""
        post_ids = self.stories.part_post_ids(story_id)
        self.posts.delete_bodies(post_ids)
        for post_id in post_ids:
            self.search.remove_body(post_id)
        self.stories.delete(story_id)

    def prune_orphans(self) -> int:
        """Clear cached metadata belonging to no story."""
        orphans = self.posts.orphaned_ids()
        for post_id in orphans:
            self.search.remove(post_id)
        return self.posts.delete_meta(orphans)

    def storage_usage(self) -> StorageUsage:
        counts = self.posts.conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM post_meta) AS posts,
                (SELECT COUNT(*) FROM post_body) AS bodies,
                (SELECT COALESCE(SUM(LENGTH(selftext)), 0) FROM post_body) AS body_bytes
            """
        ).fetchone()
        page_info = self.posts.conn.execute(
            "SELECT page_count * page_size AS total FROM pragma_page_count(), pragma_page_size()"
        ).fetchone()
        return StorageUsage(
            total_bytes=page_info["total"],
            body_bytes=counts["body_bytes"],
            post_count=counts["posts"],
            body_count=counts["bodies"],
        )

    # ---- learned cleaning -------------------------------------------------------

    def propose_cleaning_rules(self, story_id: int) -> list[CleaningRule]:
        """Detect repeated headers/footers. Returns proposals only — never applied."""
        bodies = [
            body.selftext
            for post_id in self.stories.part_post_ids(story_id)
            if (body := self.posts.get_body(post_id)) is not None
        ]
        blocks = detect_boilerplate(
            bodies,
            window=self.settings.cleaning_window,
            majority=self.settings.cleaning_majority,
            min_parts=self.settings.cleaning_min_parts,
        )
        return [
            CleaningRule(
                story_id=story_id,
                position=block.position,
                block=block.block,
                seen_in_parts=block.seen_in_parts,
            )
            for block in blocks
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_service_ops.py -v`
Expected: PASS (15 tests)

- [ ] **Step 5: Run the whole suite and commit**

```bash
uv run pytest -v
uv run ruff check . && uv run ruff format . && uv run mypy reddit_reader
git add reddit_reader/service.py tests/test_service_ops.py
git commit -m "feat: add gap backfill, export, search, and storage management operations"
```

---

### Task 20: CLI

**Files:**
- Create: `reddit_reader/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `load_settings`, `build_reddit`, `ReaderService`, storage constructors.
- Produces: a `typer.Typer` app named `app` with commands `tui`, `fetch`, `list`, `export`; plus `build_service(settings: Settings) -> ReaderService` and `resolve_story(service: ReaderService, reference: str) -> Story | None`.

**Rules from the spec:** `tui` is the default when no subcommand is given. `list` prints stories with ids, part counts, and status. `export` accepts either a story id or an `author/title` slug.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli.py`:

```python
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reddit_reader.cli import app, resolve_story
from reddit_reader.config import Settings
from reddit_reader.reddit_client import RedditClient
from reddit_reader.service import ReaderService
from reddit_reader.storage import PostRepository, SearchIndex, StoryRepository, connect
from tests.fakes import FakeReddit, make_submission

runner = CliRunner()


@pytest.fixture
def service(tmp_path: Path) -> ReaderService:
    conn = connect(tmp_path / "t.db")
    return ReaderService(
        settings=Settings(subreddits=["HFY"], export_dir=tmp_path / "out"),
        posts=PostRepository(conn),
        stories=StoryRepository(conn),
        search=SearchIndex(conn),
        client=RedditClient(
            FakeReddit(submissions=[make_submission("a1", "The Long Road - Part 1")])
        ),
    )


def test_resolve_story_by_id(service: ReaderService) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    found = resolve_story(service, str(story_id))
    assert found is not None
    assert found.id == story_id


def test_resolve_story_by_slug(service: ReaderService) -> None:
    service.commit_match(service.fetch().candidates[0])
    found = resolve_story(service, "BlueFishcake/the long road")
    assert found is not None
    assert found.author == "BlueFishcake"


def test_resolve_story_slug_is_case_insensitive(service: ReaderService) -> None:
    service.commit_match(service.fetch().candidates[0])
    assert resolve_story(service, "bluefishcake/THE LONG ROAD") is not None


def test_resolve_story_returns_none_for_unknown(service: ReaderService) -> None:
    assert resolve_story(service, "999") is None


def test_help_lists_every_command() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("tui", "fetch", "list", "export"):
        assert command in result.stdout


def test_fetch_command_help_mentions_subreddits() -> None:
    result = runner.invoke(app, ["fetch", "--help"])
    assert result.exit_code == 0
    assert "subreddit" in result.stdout.lower()


def test_export_command_help_mentions_story() -> None:
    result = runner.invoke(app, ["export", "--help"])
    assert result.exit_code == 0
    assert "story" in result.stdout.lower()


def test_list_command_help_runs() -> None:
    assert runner.invoke(app, ["list", "--help"]).exit_code == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'reddit_reader.cli'`

- [ ] **Step 3: Write the implementation**

Create `reddit_reader/cli.py`:

```python
"""Command line entry point."""

from __future__ import annotations

from pathlib import Path

import typer

from reddit_reader.config import Settings, build_reddit, load_settings
from reddit_reader.models import Story
from reddit_reader.reddit_client import RedditClient
from reddit_reader.service import ReaderService
from reddit_reader.storage import PostRepository, SearchIndex, StoryRepository, connect

app = typer.Typer(
    help="Find, assemble, and read multi-part serial fiction from Reddit.",
    no_args_is_help=False,
)


def build_service(settings: Settings) -> ReaderService:
    """Wire storage, the Reddit client, and the service together."""
    conn = connect(settings.database_path)
    return ReaderService(
        settings=settings,
        posts=PostRepository(conn),
        stories=StoryRepository(conn),
        search=SearchIndex(conn),
        client=RedditClient(build_reddit(settings)),
    )


def resolve_story(service: ReaderService, reference: str) -> Story | None:
    """Look a story up by numeric id or by `author/title` slug."""
    if reference.isdigit():
        return service.stories.get(int(reference))

    if "/" in reference:
        author, _, title = reference.partition("/")
        for story in service.stories.all_stories():
            if (
                story.author.lower() == author.strip().lower()
                and story.title.lower() == title.strip().lower()
            ):
                return story
    return None


def _settings(config: Path | None, **overrides: object) -> Settings:
    return load_settings(overrides, config_path=config)


@app.command()
def fetch(
    subreddit: list[str] = typer.Option(  # noqa: B008 - typer's declaration style
        [], "--subreddit", "-s", help="Subreddit to fetch (repeatable)."
    ),
    listing: str | None = typer.Option(None, help="Listing type: new, hot, or top."),
    limit: int | None = typer.Option(None, help="Maximum posts to fetch per subreddit."),
    config: Path | None = typer.Option(None, help="Path to a config file."),
) -> None:
    """Fetch posts into the local cache without opening the TUI."""
    settings = _settings(
        config,
        subreddits=subreddit or None,
        listing=listing,
        fetch_limit=limit,
    )
    service = build_service(settings)
    result = service.fetch()
    typer.echo(
        f"Fetched {result.fetched} posts. "
        f"Auto-attached {result.auto_attached} new parts. "
        f"{len(result.candidates)} candidates awaiting curation."
    )


@app.command("list")
def list_stories(config: Path | None = typer.Option(None, help="Path to a config file.")) -> None:
    """Print committed stories with their ids, part counts, and status."""
    service = build_service(_settings(config))
    stories = service.stories.all_stories()
    if not stories:
        typer.echo("No stories yet. Run `reddit-reader fetch` first.")
        return

    for story in stories:
        parts = len(service.stories.parts(story.id))
        status = service.story_status(story).value
        tracked = "tracked" if story.tracked else "untracked"
        volume = f" vol{story.volume}" if story.volume is not None else ""
        typer.echo(
            f"{story.id:>4}  {story.author}/{story.title}{volume}  "
            f"[{parts} parts, {status}, {tracked}]"
        )


@app.command()
def export(
    story: str = typer.Argument(..., help="Story id or `author/title` slug."),
    links: bool = typer.Option(False, "--links", help="Export a links index instead."),
    config: Path | None = typer.Option(None, help="Path to a config file."),
) -> None:
    """Export a story outside the TUI."""
    service = build_service(_settings(config))
    found = resolve_story(service, story)
    if found is None:
        typer.echo(f"No story matching {story!r}. Try `reddit-reader list`.", err=True)
        raise typer.Exit(code=1)

    path = service.export_links_file(found.id) if links else service.export_story(found.id)
    typer.echo(f"Wrote {path}")


@app.command()
def tui(config: Path | None = typer.Option(None, help="Path to a config file.")) -> None:
    """Launch the interactive reader."""
    from reddit_reader.tui.app import RedditReaderApp

    service = build_service(_settings(config))
    RedditReaderApp(service).run()


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Launch the TUI when no subcommand is given."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(tui)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS (8 tests). The `tui` command's import of `reddit_reader.tui.app` is inside the function, so it does not break before Layer 6 exists — only invoking `tui` would.

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format . && uv run mypy reddit_reader
git add reddit_reader/cli.py tests/test_cli.py
git commit -m "feat: add CLI with fetch, list, export, and tui commands"
```

---

## ✅ Checkpoint E — Working non-interactive tool

**Verify:**

```bash
uv run pytest -v
uv run ruff check . && uv run ruff format --check .
uv run mypy reddit_reader
uv run reddit-reader --help
uv run reddit-reader list --help
```

At this point the tool works end-to-end without a UI: it can fetch from multiple subreddits, detect and auto-attach parts, track stories, find gaps, backfill from author history, clean boilerplate, and export Markdown and links files. Only the interactive layer remains.

---

# Layer 6 — Textual TUI

Screens call `ReaderService` and hold no business logic. Every screen gets a Pilot smoke test.

**Checkpoint F** at the end: the full application.

### Task 21: App shell and Story List screen

**Files:**
- Create: `reddit_reader/tui/__init__.py`, `reddit_reader/tui/app.py`, `reddit_reader/tui/screens/__init__.py`, `reddit_reader/tui/screens/story_list.py`
- Test: `tests/tui/__init__.py`, `tests/tui/conftest.py`, `tests/tui/test_story_list.py`

**Interfaces:**
- Consumes: `ReaderService`, `Story`, `StoryStatus`.
- Produces: `RedditReaderApp(service)` (a `textual.app.App`) and `StoryListScreen`, which exposes `visible_stories() -> list[Story]`, `set_sort(key: str) -> None`, `set_filter(name: str, value: str | None) -> None`.

**Rules from the spec:** Story List shows **every committed story**, tracked or not, with tracked state shown and filterable — this is what gives an untracked story a route to Story Detail. Volumes of one serial group by `series_key`. Sort by score, part count, or recency of newest part. Filter by tracked state, read state, and completion status.

- [ ] **Step 1: Write the shared TUI test fixture**

Create `tests/tui/__init__.py` (empty) and `tests/tui/conftest.py`:

```python
from pathlib import Path

import pytest

from reddit_reader.config import Settings
from reddit_reader.reddit_client import RedditClient
from reddit_reader.service import ReaderService
from reddit_reader.storage import PostRepository, SearchIndex, StoryRepository, connect
from tests.fakes import FakeReddit, make_submission


@pytest.fixture
def service(tmp_path: Path) -> ReaderService:
    conn = connect(tmp_path / "t.db")
    reddit = FakeReddit(
        submissions=[
            make_submission("a1", "The Long Road - Part 1", created_days=0),
            make_submission("a2", "The Long Road - Part 2", created_days=7),
            make_submission("b1", "Second Wind - Part 1", created_days=1),
        ]
    )
    return ReaderService(
        settings=Settings(subreddits=["HFY"], export_dir=tmp_path / "out"),
        posts=PostRepository(conn),
        stories=StoryRepository(conn),
        search=SearchIndex(conn),
        client=RedditClient(reddit),
    )


@pytest.fixture
def populated(service: ReaderService) -> ReaderService:
    for match in service.fetch().candidates:
        service.commit_match(match)
    return service


@pytest.fixture
def multi_part_story_id(populated: ReaderService) -> int:
    """The multi-part serial, not the one-shot.

    `all_stories()` sorts by series_key, so index 0 is "Second Wind" (one part)
    rather than "The Long Road" (two). Tests that need several parts must ask
    for this fixture instead of guessing an index.
    """
    return max(
        populated.stories.all_stories(),
        key=lambda s: len(populated.stories.parts(s.id)),
    ).id
```

- [ ] **Step 2: Write the failing test**

Create `tests/tui/test_story_list.py`:

```python
import pytest

from reddit_reader.service import ReaderService
from reddit_reader.tui.app import RedditReaderApp
from reddit_reader.tui.screens.story_list import StoryListScreen


@pytest.mark.asyncio
async def test_app_starts_on_the_story_list(populated: ReaderService) -> None:
    app = RedditReaderApp(populated)
    async with app.run_test():
        assert isinstance(app.screen, StoryListScreen)


@pytest.mark.asyncio
async def test_story_list_shows_untracked_stories(populated: ReaderService) -> None:
    app = RedditReaderApp(populated)
    async with app.run_test():
        screen = app.screen
        assert isinstance(screen, StoryListScreen)
        assert len(screen.visible_stories()) == 2
        assert all(not s.tracked for s in screen.visible_stories())


@pytest.mark.asyncio
async def test_filter_by_tracked_state(populated: ReaderService) -> None:
    stories = populated.stories.all_stories()
    populated.track(stories[0].id)
    app = RedditReaderApp(populated)
    async with app.run_test():
        screen = app.screen
        assert isinstance(screen, StoryListScreen)
        screen.set_filter("tracked", "tracked")
        assert len(screen.visible_stories()) == 1


def test_sort_by_part_count(populated: ReaderService) -> None:
    screen = StoryListScreen(populated)
    screen.set_sort("parts")
    counts = [len(populated.stories.parts(s.id)) for s in screen.visible_stories()]
    assert counts == sorted(counts, reverse=True)


def test_sort_by_recency(populated: ReaderService) -> None:
    screen = StoryListScreen(populated)
    screen.set_sort("recent")
    assert screen.visible_stories()


def test_filter_by_read_state_unstarted(populated: ReaderService) -> None:
    screen = StoryListScreen(populated)
    screen.set_filter("read", "unstarted")
    assert len(screen.visible_stories()) == 2


def test_filter_by_read_state_in_progress(populated: ReaderService) -> None:
    story = populated.stories.all_stories()[0]
    populated.mark_read(story.id, populated.stories.part_post_ids(story.id)[0], 0.5)
    screen = StoryListScreen(populated)
    screen.set_filter("read", "in_progress")
    assert len(screen.visible_stories()) == 1


def test_filter_by_status(populated: ReaderService) -> None:
    populated.settings.stale_after_days = 1
    screen = StoryListScreen(populated)
    screen.set_filter("status", "stale")
    assert screen.visible_stories()


def test_clearing_a_filter_restores_everything(populated: ReaderService) -> None:
    screen = StoryListScreen(populated)
    screen.set_filter("tracked", "tracked")
    screen.set_filter("tracked", None)
    assert len(screen.visible_stories()) == 2


def test_volumes_of_one_serial_sort_together(populated: ReaderService) -> None:
    screen = StoryListScreen(populated)
    screen.set_sort("series")
    keys = [s.series_key for s in screen.visible_stories()]
    assert keys == sorted(keys)
```

Add `pytest-asyncio` to the dev dependency group in `pyproject.toml` and configure it:

```toml
[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "ruff>=0.4",
    "mypy>=1.10",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

Then run `uv sync`.

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/tui/test_story_list.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'reddit_reader.tui'`

- [ ] **Step 4: Write the app shell**

Create `reddit_reader/tui/__init__.py` (empty), `reddit_reader/tui/screens/__init__.py` (empty), and `reddit_reader/tui/app.py`:

```python
"""Textual application shell."""

from __future__ import annotations

from textual.app import App

from reddit_reader.service import ReaderService
from reddit_reader.tui.screens.story_list import StoryListScreen


class RedditReaderApp(App[None]):
    """The interactive reader. Story List is home."""

    CSS = """
    Screen { layout: vertical; }
    DataTable { height: 1fr; }
    #status { dock: bottom; height: 1; background: $panel; color: $text-muted; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "back", "Back"),
    ]

    def __init__(self, service: ReaderService) -> None:
        super().__init__()
        self.service = service

    def on_mount(self) -> None:
        self.push_screen(StoryListScreen(self.service))

    def action_back(self) -> None:
        if len(self.screen_stack) > 1:
            self.pop_screen()
```

- [ ] **Step 5: Write the Story List screen**

Create `reddit_reader/tui/screens/story_list.py`:

```python
"""Story List — every committed story, tracked or not."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from reddit_reader.models import Story
from reddit_reader.service import ReaderService

SORT_KEYS = ("series", "score", "parts", "recent")


class StoryListScreen(Screen[None]):
    """Home screen. Untracked stories appear here so they have a route to detail."""

    BINDINGS = [
        ("enter", "open", "Open"),
        ("s", "cycle_sort", "Sort"),
        ("t", "toggle_tracked_filter", "Tracked filter"),
        ("b", "browse", "Browse"),
        ("/", "search", "Search"),
        ("g", "storage", "Storage"),
    ]

    def __init__(self, service: ReaderService) -> None:
        super().__init__()
        self.service = service
        self._sort = "series"
        self._filters: dict[str, str | None] = {
            "tracked": None,
            "read": None,
            "status": None,
        }

    # ---- data -------------------------------------------------------------------

    def set_sort(self, key: str) -> None:
        if key in SORT_KEYS:
            self._sort = key

    def set_filter(self, name: str, value: str | None) -> None:
        self._filters[name] = value

    def _passes_filters(self, story: Story) -> bool:
        tracked = self._filters["tracked"]
        if tracked == "tracked" and not story.tracked:
            return False
        if tracked == "untracked" and story.tracked:
            return False

        read = self._filters["read"]
        if read is not None:
            unread = self.service.unread_count(story.id)
            total = len(self.service.stories.parts(story.id))
            if read == "unstarted" and story.last_read_part is not None:
                return False
            if read == "in_progress" and (story.last_read_part is None or unread == 0):
                return False
            if read == "has_unread" and (unread == 0 or unread == total):
                return False

        status = self._filters["status"]
        if status is not None and self.service.story_status(story).value != status:
            return False

        return True

    def _sort_value(self, story: Story) -> tuple[object, ...]:
        metas = self.service.posts.get_many(self.service.stories.part_post_ids(story.id))
        if self._sort == "score":
            return (-max((m.score for m in metas), default=0),)
        if self._sort == "parts":
            return (-len(self.service.stories.parts(story.id)),)
        if self._sort == "recent":
            newest = max((m.created_utc for m in metas), default=None)
            return (0 if newest is None else -newest.timestamp(),)
        return (story.series_key, story.volume or 0)

    def visible_stories(self) -> list[Story]:
        stories = [s for s in self.service.stories.all_stories() if self._passes_filters(s)]
        return sorted(stories, key=self._sort_value)

    # ---- rendering --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="stories")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#stories", DataTable)
        table.cursor_type = "row"
        table.add_columns(
            "Title", "Author", "Parts", "Status", "Tracked", "Unread", "Gaps", "New"
        )
        self.refresh_rows()

    def refresh_rows(self) -> None:
        table = self.query_one("#stories", DataTable)
        table.clear()
        for story in self.visible_stories():
            parts = len(self.service.stories.parts(story.id))
            gaps = self.service.gaps(story.id)
            filled = self.service.newly_filled(story.id)
            volume = f" (vol {story.volume})" if story.volume is not None else ""
            table.add_row(
                f"{story.title}{volume}",
                story.author,
                str(parts),
                self.service.story_status(story).value,
                "yes" if story.tracked else "no",
                str(self.service.unread_count(story.id)),
                ", ".join(str(g) for g in gaps) if gaps else "-",
                str(len(filled)) if filled else "-",
                key=str(story.id),
            )
        self._set_status(f"{len(self.visible_stories())} stories — sort: {self._sort}")

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    # ---- actions ----------------------------------------------------------------

    def _selected_story_id(self) -> int | None:
        table = self.query_one("#stories", DataTable)
        if table.row_count == 0:
            return None
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        return int(row_key.value) if row_key.value else None

    def action_cycle_sort(self) -> None:
        current = SORT_KEYS.index(self._sort)
        self._sort = SORT_KEYS[(current + 1) % len(SORT_KEYS)]
        self.refresh_rows()

    def action_toggle_tracked_filter(self) -> None:
        cycle = {None: "tracked", "tracked": "untracked", "untracked": None}
        self._filters["tracked"] = cycle[self._filters["tracked"]]
        self.refresh_rows()

    def action_open(self) -> None:
        from reddit_reader.tui.screens.story_detail import StoryDetailScreen

        story_id = self._selected_story_id()
        if story_id is not None:
            self.app.push_screen(StoryDetailScreen(self.service, story_id))

    def action_browse(self) -> None:
        from reddit_reader.tui.screens.browse import BrowseScreen

        self.app.push_screen(BrowseScreen(self.service))

    def action_search(self) -> None:
        from reddit_reader.tui.screens.search import SearchScreen

        self.app.push_screen(SearchScreen(self.service))

    def action_storage(self) -> None:
        from reddit_reader.tui.screens.storage_admin import StorageAdminScreen

        self.app.push_screen(StorageAdminScreen(self.service))
```

The screen imports its neighbours lazily inside actions so this task's tests pass before Tasks 22-25 exist.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/tui/test_story_list.py -v`
Expected: PASS (10 tests)

- [ ] **Step 7: Commit**

```bash
uv run ruff check . && uv run ruff format . && uv run mypy reddit_reader
git add reddit_reader/tui tests/tui pyproject.toml uv.lock
git commit -m "feat: add Textual app shell and Story List screen"
```

---

### Task 22: Reddit markdown rendering helper

**Files:**
- Create: `reddit_reader/tui/markdown.py`
- Test: `tests/tui/test_markdown.py`

**Interfaces:**
- Consumes: nothing (pure text transformation).
- Produces: `to_display_markdown(text: str, *, reveal_spoilers: bool = False) -> str`.

**Rules from the spec:** `>!text!<` renders concealed and toggles open on a keypress — this matters more for fiction than anywhere else, since authors use spoiler tags deliberately. `^text` and `^(text)` superscript is common in asides. Tables, quotes, and emphasis render normally.

- [ ] **Step 1: Write the failing test**

Create `tests/tui/test_markdown.py`:

```python
from reddit_reader.tui.markdown import to_display_markdown


def test_spoiler_is_concealed_by_default() -> None:
    result = to_display_markdown("She was >!the traitor!< all along.")
    assert "the traitor" not in result
    assert "all along" in result


def test_spoiler_is_revealed_when_asked() -> None:
    result = to_display_markdown("She was >!the traitor!< all along.", reveal_spoilers=True)
    assert "the traitor" in result


def test_concealed_spoiler_keeps_a_visible_placeholder() -> None:
    result = to_display_markdown(">!secret!<")
    assert result.strip() != ""


def test_multiple_spoilers_are_all_concealed() -> None:
    result = to_display_markdown(">!one!< and >!two!<")
    assert "one" not in result
    assert "two" not in result


def test_parenthesized_superscript_is_converted() -> None:
    assert "^" not in to_display_markdown("Note^(this bit)")


def test_bare_superscript_is_converted() -> None:
    assert "^" not in to_display_markdown("Note^this")


def test_ordinary_markdown_is_untouched() -> None:
    text = "# Heading\n\n**bold** and *italic*\n\n> a quote"
    assert to_display_markdown(text) == text


def test_empty_text_stays_empty() -> None:
    assert to_display_markdown("") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tui/test_markdown.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'reddit_reader.tui.markdown'`

- [ ] **Step 3: Write the implementation**

Create `reddit_reader/tui/markdown.py`:

```python
"""Convert Reddit-flavoured markdown into something Textual's renderer understands."""

from __future__ import annotations

import re

_SPOILER_RE = re.compile(r">!(.+?)!<", re.DOTALL)
_SUPERSCRIPT_PAREN_RE = re.compile(r"\^\(([^)]*)\)")
_SUPERSCRIPT_BARE_RE = re.compile(r"\^(\S+)")

SPOILER_MASK = "████████"


def to_display_markdown(text: str, *, reveal_spoilers: bool = False) -> str:
    """Mask spoilers unless revealed, and flatten Reddit's superscript syntax."""
    if reveal_spoilers:
        rendered = _SPOILER_RE.sub(lambda m: m.group(1), text)
    else:
        rendered = _SPOILER_RE.sub(SPOILER_MASK, text)

    rendered = _SUPERSCRIPT_PAREN_RE.sub(lambda m: m.group(1), rendered)
    return _SUPERSCRIPT_BARE_RE.sub(lambda m: m.group(1), rendered)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/tui/test_markdown.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format . && uv run mypy reddit_reader
git add reddit_reader/tui/markdown.py tests/tui/test_markdown.py
git commit -m "feat: render reddit markdown with concealed spoilers"
```

---

### Task 23: Story Detail screen

**Files:**
- Create: `reddit_reader/tui/screens/story_detail.py`
- Test: `tests/tui/test_story_detail.py`

**Interfaces:**
- Consumes: `ReaderService`.
- Produces: `StoryDetailScreen(service, story_id)` exposing `part_rows() -> list[tuple[str, str, str]]`, `gap_summary() -> str`, `can_find_missing() -> bool`, `pending_rules() -> list[CleaningRule]`, `approve_rule(index: int, approved: bool) -> None`.

**Rules from the spec:** part list with any missing parts called out explicitly; "select/track" triggers eager body fetch; **"find missing parts" is enabled only when gaps are detected** — a complete story has nothing to backfill, so the action is disabled and no API calls are made; export actions; and when cross-part detection finds a candidate header/footer block it's previewed here for one-time approval.

- [ ] **Step 1: Write the failing test**

Create `tests/tui/test_story_detail.py`:

```python
from decimal import Decimal

from reddit_reader.service import ReaderService
from reddit_reader.tui.screens.story_detail import StoryDetailScreen


def test_part_rows_list_every_part(
    populated: ReaderService, multi_part_story_id: int
) -> None:
    screen = StoryDetailScreen(populated, multi_part_story_id)
    assert len(screen.part_rows()) == len(populated.stories.parts(multi_part_story_id))


def test_find_missing_is_disabled_for_a_complete_story(
    populated: ReaderService, multi_part_story_id: int
) -> None:
    screen = StoryDetailScreen(populated, multi_part_story_id)
    assert screen.can_find_missing() is False


def test_gap_summary_says_complete_when_there_are_no_gaps(
    populated: ReaderService, multi_part_story_id: int
) -> None:
    screen = StoryDetailScreen(populated, multi_part_story_id)
    assert "no gaps" in screen.gap_summary().lower()


def test_find_missing_is_enabled_when_a_gap_exists(
    populated: ReaderService, multi_part_story_id: int
) -> None:
    story_id = multi_part_story_id
    # Drop part 1 so the sequence starts at 2, creating a missing start.
    parts = populated.stories.parts(story_id)
    target = next(p for p in parts if p.part_number == Decimal("1"))
    populated.stories.conn.execute(
        "DELETE FROM story_part WHERE story_id = ? AND post_id = ?",
        (story_id, target.post_id),
    )
    populated.stories.conn.commit()
    screen = StoryDetailScreen(populated, story_id)
    assert screen.can_find_missing() is True
    assert "1" in screen.gap_summary()


def test_tracking_marks_the_story_tracked(
    populated: ReaderService, multi_part_story_id: int
) -> None:
    screen = StoryDetailScreen(populated, multi_part_story_id)
    screen.do_track()
    story = populated.stories.get(multi_part_story_id)
    assert story is not None
    assert story.tracked is True


def test_untracking_reverses_it(
    populated: ReaderService, multi_part_story_id: int
) -> None:
    screen = StoryDetailScreen(populated, multi_part_story_id)
    screen.do_track()
    screen.do_untrack()
    story = populated.stories.get(multi_part_story_id)
    assert story is not None
    assert story.tracked is False


def test_export_returns_a_written_path(
    populated: ReaderService, multi_part_story_id: int
) -> None:
    screen = StoryDetailScreen(populated, multi_part_story_id)
    screen.do_track()
    path = screen.do_export()
    assert path.exists()


def test_no_cleaning_rules_proposed_for_short_stories(
    populated: ReaderService, multi_part_story_id: int
) -> None:
    screen = StoryDetailScreen(populated, multi_part_story_id)
    screen.do_track()
    assert screen.pending_rules() == []


def test_part_rows_flag_newly_filled_parts(
    populated: ReaderService, multi_part_story_id: int
) -> None:
    story_id = multi_part_story_id
    parts = populated.stories.parts(story_id)
    populated.stories.conn.execute(
        "UPDATE story_part SET newly_filled = 1 WHERE story_id = ? AND post_id = ?",
        (story_id, parts[0].post_id),
    )
    populated.stories.conn.commit()
    screen = StoryDetailScreen(populated, story_id)
    assert any("new" in row[2].lower() for row in screen.part_rows())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tui/test_story_detail.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'reddit_reader.tui.screens.story_detail'`

- [ ] **Step 3: Write the implementation**

Create `reddit_reader/tui/screens/story_detail.py`:

```python
"""Story Detail — parts, gaps, tracking, backfill, cleaning approval, export."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from reddit_reader.models import CleaningRule
from reddit_reader.service import ReaderService


class StoryDetailScreen(Screen[None]):
    """Everything you can do to one story."""

    BINDINGS = [
        ("r", "read", "Read"),
        ("t", "track", "Track"),
        ("u", "untrack", "Untrack"),
        ("f", "find_missing", "Find missing"),
        ("e", "export", "Export"),
        ("l", "export_links", "Export links"),
        ("c", "propose_cleaning", "Detect boilerplate"),
        ("escape", "app.back", "Back"),
    ]

    def __init__(self, service: ReaderService, story_id: int) -> None:
        super().__init__()
        self.service = service
        self.story_id = story_id
        self._pending: list[CleaningRule] = []

    # ---- data -------------------------------------------------------------------

    def part_rows(self) -> list[tuple[str, str, str]]:
        """(label, posted date, flags) for each part, in reading order."""
        flags_by_id = {
            part.post_id: part for part in self.service.stories.parts(self.story_id)
        }
        rows: list[tuple[str, str, str]] = []

        for group in self.service.ordered_groups(self.story_id):
            lead = group[0]
            if lead.parsed.part_number is not None:
                label = f"Part {lead.parsed.part_number.normalize()}"
            elif lead.parsed.part_label:
                label = lead.parsed.part_label
            else:
                label = lead.post.title

            flags: list[str] = []
            part = flags_by_id.get(lead.post.id)
            if part is not None and part.newly_filled:
                flags.append("NEW (backfilled)")
            if not lead.post.available:
                flags.append("unavailable upstream")
            if len(group) > 1:
                flags.append(f"{len(group)} segments")

            rows.append((label, lead.post.created_utc.date().isoformat(), ", ".join(flags)))

        return rows

    def gap_summary(self) -> str:
        gaps = self.service.gaps(self.story_id)
        if not gaps:
            return "No gaps detected."
        return "Missing parts: " + ", ".join(str(g.normalize()) for g in gaps)

    def can_find_missing(self) -> bool:
        """Only meaningful when gaps exist — otherwise no API calls are made at all."""
        return bool(self.service.gaps(self.story_id))

    def pending_rules(self) -> list[CleaningRule]:
        return self._pending

    # ---- operations -------------------------------------------------------------

    def do_track(self) -> int:
        count = self.service.track(self.story_id)
        self._pending = self.service.propose_cleaning_rules(self.story_id)
        return count

    def do_untrack(self) -> int:
        return self.service.untrack(self.story_id)

    def do_export(self) -> Path:
        return self.service.export_story(self.story_id)

    def do_export_links(self) -> Path:
        return self.service.export_links_file(self.story_id)

    def approve_rule(self, index: int, approved: bool) -> None:
        rule = self._pending[index]
        rule.approved = approved
        rule_id = self.service.stories.add_cleaning_rule(rule)
        self.service.stories.set_rule_decision(rule_id, approved)
        self._pending.pop(index)

    # ---- rendering --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="summary")
        yield DataTable(id="parts")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#parts", DataTable)
        table.cursor_type = "row"
        table.add_columns("Part", "Posted", "Flags")
        self.refresh_view()

    def refresh_view(self) -> None:
        story = self.service.stories.get(self.story_id)
        if story is None:
            return

        tracked = "tracked" if story.tracked else "untracked"
        status = self.service.story_status(story).value
        self.query_one("#summary", Static).update(
            f"{story.title} by {story.author} — {status}, {tracked}\n{self.gap_summary()}"
        )

        table = self.query_one("#parts", DataTable)
        table.clear()
        for label, posted, flags in self.part_rows():
            table.add_row(label, posted, flags or "-")

        if self._pending:
            preview = self._pending[0]
            self._status(
                f"Detected boilerplate in {preview.seen_in_parts} parts — "
                "press 'y' to strip it, 'n' to keep it."
            )

    def _status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    # ---- actions ----------------------------------------------------------------

    def action_read(self) -> None:
        from reddit_reader.tui.screens.reader import ReaderScreen

        story = self.service.stories.get(self.story_id)
        if story is None or not story.tracked:
            self._status("Track this story first (t) to cache its text.")
            return
        self.app.push_screen(ReaderScreen(self.service, self.story_id))

    def action_track(self) -> None:
        count = self.do_track()
        self._status(f"Tracked. Cached {count} bodies.")
        self.refresh_view()

    def action_untrack(self) -> None:
        count = self.do_untrack()
        self._status(f"Untracked. Dropped {count} cached bodies.")
        self.refresh_view()

    def action_find_missing(self) -> None:
        if not self.can_find_missing():
            self._status("No gaps — nothing to find.")
            return
        matches = self.service.find_missing_parts(self.story_id)
        self._status(f"Found {len(matches)} candidate groups from author history.")
        self.refresh_view()

    def action_export(self) -> None:
        self._status(f"Wrote {self.do_export()}")

    def action_export_links(self) -> None:
        self._status(f"Wrote {self.do_export_links()}")

    def action_propose_cleaning(self) -> None:
        self._pending = self.service.propose_cleaning_rules(self.story_id)
        self._status(
            f"{len(self._pending)} boilerplate blocks detected."
            if self._pending
            else "No repeated boilerplate found."
        )
        self.refresh_view()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/tui/test_story_detail.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format . && uv run mypy reddit_reader
git add reddit_reader/tui/screens/story_detail.py tests/tui/test_story_detail.py
git commit -m "feat: add Story Detail screen with tracking, gaps, and export"
```

---

### Task 24: Reader screen

**Files:**
- Create: `reddit_reader/tui/screens/reader.py`
- Test: `tests/tui/test_reader.py`

**Interfaces:**
- Consumes: `ReaderService`, `to_display_markdown`, `clean`.
- Produces: `ReaderScreen(service, story_id)` exposing `part_index: int`, `rendered_text() -> str`, `heading() -> str`, `next_part() -> bool`, `previous_part() -> bool`, `jump_to(index: int) -> None`, `save_position(offset: float) -> None`, `toggle_spoilers() -> None`.

**Rules from the spec:** parts render in order with a boundary heading using the number when present and `part_label` otherwise; resume from the saved position by default; manual jump to any part (e.g. to read only newly added installments); position saved as part + fractional offset so quitting mid-chapter resumes where you stopped.

- [ ] **Step 1: Write the failing test**

Create `tests/tui/test_reader.py`:

```python
import pytest

from reddit_reader.service import ReaderService
from reddit_reader.tui.screens.reader import ReaderScreen


@pytest.fixture
def tracked_story(populated: ReaderService, multi_part_story_id: int) -> int:
    """The multi-part serial, tracked so its bodies are cached."""
    populated.track(multi_part_story_id)
    return multi_part_story_id


def test_reader_starts_at_the_first_part_when_nothing_read(
    populated: ReaderService, tracked_story: int
) -> None:
    screen = ReaderScreen(populated, tracked_story)
    assert screen.part_index == 0


def test_reader_resumes_from_the_saved_position(
    populated: ReaderService, tracked_story: int
) -> None:
    story_id = tracked_story
    second = populated.ordered_parts(story_id)[1].post.id
    populated.mark_read(story_id, second, 0.5)
    screen = ReaderScreen(populated, story_id)
    assert screen.part_index == 1


def test_rendered_text_contains_the_body(
    populated: ReaderService, tracked_story: int
) -> None:
    screen = ReaderScreen(populated, tracked_story)
    assert "Story text." in screen.rendered_text()


def test_heading_names_the_part(populated: ReaderService, tracked_story: int) -> None:
    screen = ReaderScreen(populated, tracked_story)
    assert "Part 1" in screen.heading()


def test_next_part_advances(populated: ReaderService, tracked_story: int) -> None:
    screen = ReaderScreen(populated, tracked_story)
    assert screen.next_part() is True
    assert screen.part_index == 1


def test_next_part_stops_at_the_end(
    populated: ReaderService, tracked_story: int
) -> None:
    screen = ReaderScreen(populated, tracked_story)
    total = len(populated.ordered_groups(tracked_story))
    screen.jump_to(total - 1)
    assert screen.next_part() is False


def test_previous_part_goes_back(populated: ReaderService, tracked_story: int) -> None:
    screen = ReaderScreen(populated, tracked_story)
    screen.next_part()
    assert screen.previous_part() is True
    assert screen.part_index == 0


def test_previous_part_stops_at_the_start(
    populated: ReaderService, tracked_story: int
) -> None:
    screen = ReaderScreen(populated, tracked_story)
    assert screen.previous_part() is False


def test_advancing_saves_the_read_position(
    populated: ReaderService, tracked_story: int
) -> None:
    screen = ReaderScreen(populated, tracked_story)
    screen.next_part()
    story = populated.stories.get(tracked_story)
    assert story is not None
    assert story.last_read_part == populated.ordered_parts(tracked_story)[1].post.id


def test_save_position_records_the_offset(
    populated: ReaderService, tracked_story: int
) -> None:
    screen = ReaderScreen(populated, tracked_story)
    screen.save_position(0.75)
    story = populated.stories.get(tracked_story)
    assert story is not None
    assert story.last_read_offset == 0.75


def test_spoilers_are_concealed_until_toggled(
    populated: ReaderService, tracked_story: int
) -> None:
    story_id = tracked_story
    post_id = populated.ordered_parts(story_id)[0].post.id
    from reddit_reader.models import PostBody

    populated.posts.set_body(
        PostBody(post_id=post_id, selftext="She was >!the traitor!< all along.")
    )
    screen = ReaderScreen(populated, story_id)
    assert "the traitor" not in screen.rendered_text()
    screen.toggle_spoilers()
    assert "the traitor" in screen.rendered_text()


def test_jumping_to_a_part_updates_the_index(
    populated: ReaderService, tracked_story: int
) -> None:
    screen = ReaderScreen(populated, tracked_story)
    screen.jump_to(1)
    assert screen.part_index == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tui/test_reader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'reddit_reader.tui.screens.reader'`

- [ ] **Step 3: Write the implementation**

Create `reddit_reader/tui/screens/reader.py`:

```python
"""Reader — renders one part at a time and remembers where you stopped."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Markdown, Static

from reddit_reader.cleaning import clean
from reddit_reader.service import ReaderService
from reddit_reader.tui.markdown import to_display_markdown


class ReaderScreen(Screen[None]):
    """One part at a time, resuming from the saved position."""

    BINDINGS = [
        ("n", "next", "Next part"),
        ("p", "previous", "Previous part"),
        ("s", "toggle_spoilers", "Toggle spoilers"),
        ("escape", "app.back", "Back"),
    ]

    def __init__(self, service: ReaderService, story_id: int) -> None:
        super().__init__()
        self.service = service
        self.story_id = story_id
        self.groups = service.ordered_groups(story_id)
        self.reveal_spoilers = False
        self.part_index = self._starting_index()

    def _starting_index(self) -> int:
        story = self.service.stories.get(self.story_id)
        if story is None or story.last_read_part is None:
            return 0
        for index, group in enumerate(self.groups):
            if any(part.post.id == story.last_read_part for part in group):
                return index
        return 0

    # ---- content ----------------------------------------------------------------

    def heading(self) -> str:
        group = self.groups[self.part_index]
        lead = group[0]
        if lead.parsed.part_number is not None:
            return f"Part {lead.parsed.part_number.normalize()}"
        if lead.parsed.part_label:
            return lead.parsed.part_label
        return lead.post.title

    def rendered_text(self) -> str:
        """Cleaned, spoiler-masked text for the current part (all its segments)."""
        rules = self.service.stories.cleaning_rules(self.story_id)
        chunks: list[str] = []

        for part in self.groups[self.part_index]:
            body = self.service.posts.get_body(part.post.id)
            if body is None:
                continue
            cleaned = clean(
                body.selftext,
                rules,
                strip_known_patterns=self.service.settings.cleaning_enabled,
            )
            chunks.append(to_display_markdown(cleaned, reveal_spoilers=self.reveal_spoilers))

        return "\n\n".join(chunks)

    # ---- navigation -------------------------------------------------------------

    def _current_post_id(self) -> str:
        return self.groups[self.part_index][0].post.id

    def save_position(self, offset: float) -> None:
        self.service.mark_read(self.story_id, self._current_post_id(), offset)

    def jump_to(self, index: int) -> None:
        if 0 <= index < len(self.groups):
            self.part_index = index
            self.save_position(0.0)

    def next_part(self) -> bool:
        if self.part_index + 1 >= len(self.groups):
            return False
        self.part_index += 1
        self.save_position(0.0)
        return True

    def previous_part(self) -> bool:
        if self.part_index == 0:
            return False
        self.part_index -= 1
        self.save_position(0.0)
        return True

    def toggle_spoilers(self) -> None:
        self.reveal_spoilers = not self.reveal_spoilers

    # ---- rendering --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="heading")
        with VerticalScroll(id="body-scroll"):
            yield Markdown("", id="body")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_view()

    def refresh_view(self) -> None:
        self.query_one("#heading", Static).update(
            f"{self.heading()}  ({self.part_index + 1}/{len(self.groups)})"
        )
        self.query_one("#body", Markdown).update(self.rendered_text())

    def action_next(self) -> None:
        if self.next_part():
            self.refresh_view()

    def action_previous(self) -> None:
        if self.previous_part():
            self.refresh_view()

    def action_toggle_spoilers(self) -> None:
        self.toggle_spoilers()
        self.refresh_view()

    def on_unmount(self) -> None:
        """Persist how far through the part the reader had scrolled."""
        try:
            scroll = self.query_one("#body-scroll", VerticalScroll)
        except Exception:  # noqa: BLE001 - screen may be torn down before mount completes
            return
        maximum = max(scroll.max_scroll_y, 1)
        self.save_position(min(1.0, scroll.scroll_y / maximum))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/tui/test_reader.py -v`
Expected: PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run ruff format . && uv run mypy reddit_reader
git add reddit_reader/tui/screens/reader.py tests/tui/test_reader.py
git commit -m "feat: add Reader screen with resume, spoilers, and segment merging"
```

---

### Task 25: Browse, Search, Curation, and Storage screens

**Files:**
- Create: `reddit_reader/tui/screens/browse.py`, `reddit_reader/tui/screens/search.py`, `reddit_reader/tui/screens/curation.py`, `reddit_reader/tui/screens/storage_admin.py`
- Test: `tests/tui/test_remaining_screens.py`

**Interfaces:**
- Consumes: `ReaderService`.
- Produces:
  - `BrowseScreen(service)` with `do_fetch() -> FetchResult`, `set_listing(listing: str) -> None`, `rows() -> list[tuple[str, str, str, str]]`
  - `SearchScreen(service)` with `do_local_search(query: str) -> list[PostMeta]`, `do_live_search(query: str, subreddit: str | None) -> list[PostMeta]`, `open_for_post(post_id: str) -> None`
  - `CurationScreen(service, candidates)` with `accept(index: int) -> int`, `drop(index: int) -> None`, `merge(a: int, b: int) -> None`, `split(index: int, post_ids: list[str]) -> None`
  - `StorageAdminScreen(service)` with `usage_lines() -> list[str]`, `do_prune() -> int`, `do_delete(story_id: int) -> None`

**Rules from the spec:** Browse is a merged list with a subreddit column, filterable to a single sub, with switchable listing type. Search queries the local cache first with an explicit live-search action taking a scope; **search results link directly into the curation screen for a detected series, or straight to Story Detail if already committed**. Curation offers accept, merge, split, drop, reorder. Storage offers untrack, delete, prune, and usage; deletions prompt for confirmation and report what was removed.

- [ ] **Step 1: Write the failing test**

Create `tests/tui/test_remaining_screens.py`:

```python
import pytest

from reddit_reader.service import ReaderService
from reddit_reader.tui.screens.browse import BrowseScreen
from reddit_reader.tui.screens.curation import CurationScreen
from reddit_reader.tui.screens.search import SearchScreen
from reddit_reader.tui.screens.storage_admin import StorageAdminScreen


def test_browse_fetch_returns_a_result(service: ReaderService) -> None:
    screen = BrowseScreen(service)
    assert screen.do_fetch().fetched == 3


def test_browse_rows_include_the_subreddit_column(service: ReaderService) -> None:
    screen = BrowseScreen(service)
    screen.do_fetch()
    assert all(row[1] == "HFY" for row in screen.rows())


def test_browse_can_switch_listing_type(service: ReaderService) -> None:
    screen = BrowseScreen(service)
    screen.set_listing("top")
    assert service.settings.listing == "top"


def test_browse_filter_narrows_to_one_subreddit(service: ReaderService) -> None:
    screen = BrowseScreen(service)
    screen.do_fetch()
    screen.set_subreddit_filter("Nonexistent")
    assert screen.rows() == []


def test_local_search_finds_cached_posts(service: ReaderService) -> None:
    service.fetch()
    screen = SearchScreen(service)
    assert [p.id for p in screen.do_local_search("Long Road")] == ["a1", "a2"]


def test_local_search_returns_nothing_for_a_miss(service: ReaderService) -> None:
    service.fetch()
    screen = SearchScreen(service)
    assert screen.do_local_search("dragons") == []


def test_live_search_caches_what_it_finds(service: ReaderService) -> None:
    screen = SearchScreen(service)
    found = screen.do_live_search("Second Wind", "HFY")
    assert [p.id for p in found] == ["b1"]
    assert service.posts.get_meta("b1") is not None


def test_curation_accept_commits_a_story(service: ReaderService) -> None:
    candidates = service.fetch().candidates
    screen = CurationScreen(service, candidates)
    story_id = screen.accept(0)
    assert service.stories.get(story_id) is not None


def test_curation_drop_removes_a_candidate(service: ReaderService) -> None:
    candidates = service.fetch().candidates
    screen = CurationScreen(service, candidates)
    before = len(screen.candidates)
    screen.drop(0)
    assert len(screen.candidates) == before - 1


def test_curation_merge_combines_two_candidates(service: ReaderService) -> None:
    candidates = service.fetch().candidates
    assert len(candidates) >= 2
    screen = CurationScreen(service, candidates)
    total = len(candidates[0].post_ids) + len(candidates[1].post_ids)
    screen.merge(0, 1)
    assert len(screen.candidates[0].post_ids) == total


def test_curation_split_extracts_posts_into_a_new_candidate(
    service: ReaderService,
) -> None:
    candidates = service.fetch().candidates
    target = next(c for c in candidates if len(c.post_ids) > 1)
    index = candidates.index(target)
    screen = CurationScreen(service, candidates)
    moved = [target.post_ids[0]]
    screen.split(index, moved)
    assert any(c.post_ids == moved for c in screen.candidates)


def test_storage_usage_lines_are_human_readable(service: ReaderService) -> None:
    service.fetch()
    screen = StorageAdminScreen(service)
    lines = screen.usage_lines()
    assert any("post" in line.lower() for line in lines)


def test_storage_prune_reports_a_count(service: ReaderService) -> None:
    service.fetch()
    screen = StorageAdminScreen(service)
    assert screen.do_prune() == 3


def test_storage_delete_removes_the_story(service: ReaderService) -> None:
    story_id = service.commit_match(service.fetch().candidates[0])
    screen = StorageAdminScreen(service)
    screen.do_delete(story_id)
    assert service.stories.get(story_id) is None


@pytest.mark.asyncio
async def test_every_screen_mounts_without_error(populated: ReaderService) -> None:
    from reddit_reader.tui.app import RedditReaderApp

    app = RedditReaderApp(populated)
    async with app.run_test() as pilot:
        app.push_screen(BrowseScreen(populated))
        await pilot.pause()
        app.pop_screen()
        app.push_screen(SearchScreen(populated))
        await pilot.pause()
        app.pop_screen()
        app.push_screen(StorageAdminScreen(populated))
        await pilot.pause()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tui/test_remaining_screens.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'reddit_reader.tui.screens.browse'`

- [ ] **Step 3: Write the Browse screen**

Create `reddit_reader/tui/screens/browse.py`:

```python
"""Browse — a merged listing across every configured subreddit."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from reddit_reader.service import FetchResult, ReaderService

LISTINGS = ("new", "hot", "top")


class BrowseScreen(Screen[None]):
    """Fetch and inspect raw posts before they become stories."""

    BINDINGS = [
        ("f", "fetch", "Fetch"),
        ("l", "cycle_listing", "Listing type"),
        ("escape", "app.back", "Back"),
    ]

    def __init__(self, service: ReaderService) -> None:
        super().__init__()
        self.service = service
        self._subreddit_filter: str | None = None
        self._last_result: FetchResult | None = None

    # ---- data -------------------------------------------------------------------

    def set_listing(self, listing: str) -> None:
        if listing in LISTINGS:
            self.service.settings.listing = listing  # type: ignore[assignment]

    def set_subreddit_filter(self, subreddit: str | None) -> None:
        self._subreddit_filter = subreddit

    def do_fetch(self) -> FetchResult:
        self._last_result = self.service.fetch()
        return self._last_result

    def rows(self) -> list[tuple[str, str, str, str]]:
        """(title, subreddit, author, grouped?) for every cached post."""
        grouped = {
            post_id
            for story in self.service.stories.all_stories()
            for post_id in self.service.stories.part_post_ids(story.id)
        }
        rows: list[tuple[str, str, str, str]] = []
        for post_id in self.service.posts.orphaned_ids() + sorted(grouped):
            meta = self.service.posts.get_meta(post_id)
            if meta is None:
                continue
            if self._subreddit_filter and meta.subreddit.lower() != self._subreddit_filter.lower():
                continue
            rows.append(
                (meta.title, meta.subreddit, meta.author, "yes" if meta.id in grouped else "no")
            )
        return rows

    # ---- rendering --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="posts")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#posts", DataTable)
        table.cursor_type = "row"
        table.add_columns("Title", "Subreddit", "Author", "Grouped")
        self.refresh_rows()

    def refresh_rows(self) -> None:
        table = self.query_one("#posts", DataTable)
        table.clear()
        for row in self.rows():
            table.add_row(*row)
        self.query_one("#status", Static).update(
            f"listing: {self.service.settings.listing} — {len(self.rows())} posts cached"
        )

    def action_fetch(self) -> None:
        result = self.do_fetch()
        self.refresh_rows()
        self.query_one("#status", Static).update(
            f"Fetched {result.fetched}, auto-attached {result.auto_attached}, "
            f"{len(result.candidates)} candidates."
        )
        if result.candidates:
            from reddit_reader.tui.screens.curation import CurationScreen

            self.app.push_screen(CurationScreen(self.service, result.candidates))

    def action_cycle_listing(self) -> None:
        current = LISTINGS.index(self.service.settings.listing)
        self.set_listing(LISTINGS[(current + 1) % len(LISTINGS)])
        self.refresh_rows()
```

- [ ] **Step 4: Write the Search screen**

Create `reddit_reader/tui/screens/search.py`:

```python
"""Search — local cache first, with an explicit live Reddit search."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Static

from reddit_reader.models import PostMeta
from reddit_reader.service import ReaderService


class SearchScreen(Screen[None]):
    """Keyword search over cached posts, escalating to Reddit on request."""

    BINDINGS = [
        ("enter", "search_local", "Search cache"),
        ("ctrl+r", "search_live", "Search Reddit"),
        ("escape", "app.back", "Back"),
    ]

    def __init__(self, service: ReaderService) -> None:
        super().__init__()
        self.service = service
        self.results: list[PostMeta] = []

    # ---- data -------------------------------------------------------------------

    def do_local_search(self, query: str) -> list[PostMeta]:
        self.results = self.service.search_local(query)
        return self.results

    def do_live_search(self, query: str, subreddit: str | None = None) -> list[PostMeta]:
        self.results = self.service.search_live(query, subreddit)
        return self.results

    def open_for_post(self, post_id: str) -> None:
        """Jump to the story containing this post, or curate its detected series."""
        for story in self.service.stories.all_stories():
            if post_id in self.service.stories.part_post_ids(story.id):
                from reddit_reader.tui.screens.story_detail import StoryDetailScreen

                self.app.push_screen(StoryDetailScreen(self.service, story.id))
                return

        meta = self.service.posts.get_meta(post_id)
        if meta is None:
            return

        from reddit_reader.detection import group_posts
        from reddit_reader.tui.screens.curation import CurationScreen

        author_posts = self.service.posts.by_author(meta.author)
        candidates = [
            match
            for match in group_posts(author_posts, self.service.settings.subreddits)
            if post_id in match.post_ids
        ]
        if candidates:
            self.app.push_screen(CurationScreen(self.service, candidates))

    # ---- rendering --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Search titles (and bodies of tracked stories)…", id="query")
        yield DataTable(id="results")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results", DataTable)
        table.cursor_type = "row"
        table.add_columns("Title", "Subreddit", "Author")

    def _query(self) -> str:
        return self.query_one("#query", Input).value

    def refresh_rows(self) -> None:
        table = self.query_one("#results", DataTable)
        table.clear()
        for meta in self.results:
            table.add_row(meta.title, meta.subreddit, meta.author, key=meta.id)
        self.query_one("#status", Static).update(f"{len(self.results)} results")

    def action_search_local(self) -> None:
        self.do_local_search(self._query())
        self.refresh_rows()

    def action_search_live(self) -> None:
        self.do_live_search(self._query())
        self.refresh_rows()
```

- [ ] **Step 5: Write the Curation screen**

Create `reddit_reader/tui/screens/curation.py`:

```python
"""Curation — review candidate series before they become stories."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from reddit_reader.models import DetectionMatch
from reddit_reader.service import ReaderService


class CurationScreen(Screen[None]):
    """Accept, merge, split, or drop detected candidates."""

    BINDINGS = [
        ("a", "accept", "Accept"),
        ("d", "drop", "Drop"),
        ("m", "mark_merge", "Mark/merge"),
        ("escape", "app.back", "Back"),
    ]

    def __init__(self, service: ReaderService, candidates: list[DetectionMatch]) -> None:
        super().__init__()
        self.service = service
        self.candidates = list(candidates)
        self._merge_anchor: int | None = None

    # ---- operations -------------------------------------------------------------

    def accept(self, index: int) -> int:
        """Commit a candidate, attaching to its existing story when it has one."""
        match = self.candidates[index]
        if match.existing_story_id is not None:
            story_id = match.existing_story_id
            self.service.attach_parts(story_id, match)
        else:
            story_id = self.service.commit_match(match)
        self.candidates.pop(index)
        return story_id

    def drop(self, index: int) -> None:
        self.candidates.pop(index)

    def merge(self, a: int, b: int) -> None:
        """Fold candidate `b` into candidate `a`."""
        first, second = self.candidates[a], self.candidates[b]
        combined = list(dict.fromkeys([*first.post_ids, *second.post_ids]))
        first.post_ids = combined
        first.confidence = min(first.confidence, second.confidence)
        first.reasons = [*first.reasons, "merged by hand"]
        self.candidates.pop(b)

    def split(self, index: int, post_ids: list[str]) -> None:
        """Move `post_ids` out of a candidate into a new one."""
        source = self.candidates[index]
        moved = [pid for pid in post_ids if pid in source.post_ids]
        if not moved:
            return
        source.post_ids = [pid for pid in source.post_ids if pid not in moved]
        self.candidates.append(
            DetectionMatch(
                base_title=source.base_title,
                author=source.author,
                volume=source.volume,
                post_ids=moved,
                confidence=source.confidence,
                reasons=["split by hand"],
            )
        )

    # ---- rendering --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="candidates")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#candidates", DataTable)
        table.cursor_type = "row"
        table.add_columns("Title", "Author", "Volume", "Parts", "Confidence", "Existing")
        self.refresh_rows()

    def refresh_rows(self) -> None:
        table = self.query_one("#candidates", DataTable)
        table.clear()
        for match in self.candidates:
            table.add_row(
                match.base_title,
                match.author,
                str(match.volume) if match.volume is not None else "-",
                str(len(match.post_ids)),
                f"{match.confidence:.2f}",
                str(match.existing_story_id) if match.existing_story_id else "-",
            )
        self.query_one("#status", Static).update(f"{len(self.candidates)} candidates")

    def _cursor(self) -> int:
        return self.query_one("#candidates", DataTable).cursor_row

    def action_accept(self) -> None:
        if self.candidates:
            self.accept(self._cursor())
            self.refresh_rows()

    def action_drop(self) -> None:
        if self.candidates:
            self.drop(self._cursor())
            self.refresh_rows()

    def action_mark_merge(self) -> None:
        current = self._cursor()
        if self._merge_anchor is None:
            self._merge_anchor = current
            self.query_one("#status", Static).update("Merge anchor set — pick the second.")
            return
        if self._merge_anchor != current:
            self.merge(self._merge_anchor, current)
        self._merge_anchor = None
        self.refresh_rows()
```

- [ ] **Step 6: Write the Storage screen**

Create `reddit_reader/tui/screens/storage_admin.py`:

```python
"""Storage management — usage, untracking, deletion, and pruning."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from reddit_reader.service import ReaderService


def _mb(value: int) -> str:
    return f"{value / 1_048_576:.2f} MB"


class StorageAdminScreen(Screen[None]):
    """What the cache is costing, and how to reclaim it."""

    BINDINGS = [
        ("p", "prune", "Prune orphans"),
        ("u", "untrack", "Untrack story"),
        ("d", "delete", "Delete story"),
        ("escape", "app.back", "Back"),
    ]

    def __init__(self, service: ReaderService) -> None:
        super().__init__()
        self.service = service
        self._confirming: int | None = None

    # ---- data -------------------------------------------------------------------

    def usage_lines(self) -> list[str]:
        usage = self.service.storage_usage()
        return [
            f"Database total: {_mb(usage.total_bytes)}",
            f"Cached bodies: {_mb(usage.body_bytes)} across {usage.body_count} posts",
            f"Post metadata: {usage.post_count} posts",
        ]

    def do_prune(self) -> int:
        return self.service.prune_orphans()

    def do_delete(self, story_id: int) -> None:
        self.service.delete_story(story_id)

    def do_untrack(self, story_id: int) -> int:
        return self.service.untrack(story_id)

    # ---- rendering --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="usage")
        yield DataTable(id="stories")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#stories", DataTable)
        table.cursor_type = "row"
        table.add_columns("Story", "Author", "Parts", "Tracked")
        self.refresh_view()

    def refresh_view(self) -> None:
        self.query_one("#usage", Static).update("\n".join(self.usage_lines()))
        table = self.query_one("#stories", DataTable)
        table.clear()
        for story in self.service.stories.all_stories():
            table.add_row(
                story.title,
                story.author,
                str(len(self.service.stories.parts(story.id))),
                "yes" if story.tracked else "no",
                key=str(story.id),
            )

    def _selected_story_id(self) -> int | None:
        table = self.query_one("#stories", DataTable)
        if table.row_count == 0:
            return None
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        return int(row_key.value) if row_key.value else None

    def _status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def action_prune(self) -> None:
        removed = self.do_prune()
        self.refresh_view()
        self._status(f"Pruned {removed} orphaned posts.")

    def action_untrack(self) -> None:
        story_id = self._selected_story_id()
        if story_id is None:
            return
        dropped = self.do_untrack(story_id)
        self.refresh_view()
        self._status(f"Untracked story {story_id}; dropped {dropped} cached bodies.")

    def action_delete(self) -> None:
        story_id = self._selected_story_id()
        if story_id is None:
            return
        if self._confirming != story_id:
            self._confirming = story_id
            self._status(f"Press 'd' again to delete story {story_id}. Post metadata is kept.")
            return
        self.do_delete(story_id)
        self._confirming = None
        self.refresh_view()
        self._status(f"Deleted story {story_id}.")
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/tui/test_remaining_screens.py -v`
Expected: PASS (15 tests)

- [ ] **Step 8: Run the whole suite and commit**

```bash
uv run pytest -v
uv run ruff check . && uv run ruff format . && uv run mypy reddit_reader
git add reddit_reader/tui/screens tests/tui/test_remaining_screens.py
git commit -m "feat: add Browse, Search, Curation, and Storage screens"
```

---

## ✅ Checkpoint F — Application complete

**Verify:**

```bash
uv run pytest -v
uv run ruff check . && uv run ruff format --check .
uv run mypy reddit_reader
uv run reddit-reader --help
```

All must pass. The full v1 from the spec is implemented.

**Manual smoke test** (requires real credentials in `praw.ini`):

```bash
uv run reddit-reader fetch --subreddit HFY --limit 25
uv run reddit-reader list
uv run reddit-reader export <id>
uv run reddit-reader tui
```

---

## Spec Coverage Map

| Spec section | Tasks |
|---|---|
| Scope: multiple subreddits | 17 (config list), 18 (fetch loop), 9 (priority), 25 (browse column) |
| Data Model (all 7 models) | 2, 3, 6 |
| Search index + body lifecycle | 5, 18 (index on track), 19 (remove on untrack/delete) |
| Title normalization, numbers, volumes, tags | 7 |
| Segment vs part-number disambiguation | 7, 8 (grouping), 16 (one heading) |
| Non-integer and named parts | 7, 8, 16 (`part_label` heading) |
| Grouping, author match, `[deleted]` | 10 |
| Confidence scoring | 10 |
| Crosspost/mirror dedupe + canonical priority | 9 |
| Volumes as separate stories, `series_key` | 7, 10, 18, 21 (grouping in list) |
| Nav-link parsing | 12 |
| Nav-link expansion pass (on track + on new parts) | 18 (`nav_link_expansion`) |
| Attaching new parts / auto-attach threshold | 11, 18 |
| Unread derived; `newly_filled` for backfill | 18 |
| Gap detection (interior, missing start, suppression) | 11, 19 |
| Find missing parts (gap-gated) | 19, 23 (`can_find_missing`) |
| Unavailable parts (auto + manual) | 19 |
| Opportunistic availability updates | 13, 18 (`track`) |
| TUI screens | 21, 23, 24, 25 |
| CLI + config layering + praw.ini | 17, 20 |
| Reader rendering (spoilers, superscript) | 22, 24 |
| Reading position (part + offset) | 18, 24 |
| Story status (markers + staleness) | 18 |
| Boilerplate cleaning (patterns) | 14 |
| Learned header/footer + approval | 15, 19, 23 |
| Export (markdown, links, filename) | 16, 19 |
| Storage management | 19, 25 |
| Error handling (typed at PRAW boundary) | 13 |
| Testing strategy | every task |

