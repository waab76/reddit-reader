# reddit-reader Design

## Purpose

A Python/PRAW-based interactive tool for finding, assembling, and reading multi-part
stories posted across multiple submissions to a subreddit (e.g. r/FHY), where a single
"story" is split across many posts ("parts"/"chapters") over time.

## Scope (v1)

- Single subreddit per run.
- Local SQLite cache; no background processes — all fetching/refreshing is a manual,
  explicit action.
- Interactive TUI as the primary interface, with a few one-shot CLI subcommands for
  scripting/automation.

## Architecture

Layered modules, each with one job, communicating only through pydantic models:

```
reddit_reader/
  config.py       # layered settings: CLI flags > config file > env vars (pydantic-settings)
  models.py       # pydantic models: PostMeta, PostBody, Story, StoryPart, DetectionMatch
  reddit_client.py# PRAW wrapper — subreddit listing fetch, live search, author submission history
  storage.py      # sqlite3 + pydantic — post/story cache, curation state, FTS5 full-text index
  detection.py    # series-detection heuristics + on-demand "find all parts" (author-history expansion)
  export.py       # Markdown story export + links-file export
  tui/            # Textual app: browse, search, series list, reader, curation, "find all parts" action
  cli.py          # entry point — parses config, launches TUI or runs one-shot commands
```

`detection.py` doesn't know about SQLite. `storage.py` doesn't know about PRAW. `tui/`
doesn't know how detection works internally. This keeps each piece independently
testable, which matters given the mypy/ruff strictness goals — clean interfaces make
strict typing far less painful.

## Data Model

Bodies are only cached for stories you've explicitly chosen to track, to avoid
unbounded local storage growth from every post ever seen in a subreddit.

- **`PostMeta`** — always cached for every fetched/searched post, lightweight: `id`,
  `subreddit`, `author`, `title` (raw, unmodified), `permalink`, `created_utc`, `score`.
  No body. This is what detection, browsing, and title-search operate on.
- **`PostBody`** — body text (`selftext`), stored *only* for posts belonging to a
  **tracked** `Story`. Fetched in one eager batch (all currently-known parts at once)
  when you select/track a story, and again for any newly discovered parts.
- **`StoryPart`** — links a `PostMeta` to a `Story`: `post_id` (FK), `story_id` (FK),
  `part_number` (nullable — some posts have no extractable number), `match_confidence`.
- **`Story`** — `id`, `title` (normalized base title), `author`, `tracked` (bool — gates
  body caching), `last_read_part`, `exported_markdown_path` (nullable), `exported_at`
  (nullable), `last_updated_at`.
- **`DetectionMatch`** — transient candidate grouping + confidence + reasoning, shown
  during curation before becoming a real `Story`/`StoryPart` pair. Never auto-committed.

### Search index

A SQLite FTS5 virtual table (`post_search`) indexes **raw `title` text only** for every
cached `PostMeta` (bracket tags like `[OC]` are part of the raw title and thus already
token-matchable — no separate tag extraction needed). Body text is additionally indexed
only for posts with a `PostBody` row (i.e. tracked stories), so deeper body-text search
naturally covers stories you already care about without forcing eager body storage for
everything else.

## Detection Algorithm

Given a batch of `PostMeta` from a subreddit fetch:

1. **Title normalization** — strip series markers to produce a "base title" used only
   for grouping comparisons (the stored raw title is never mutated):
   - Numeric part markers: `Part N`, `[N/M]`, `(N/M)`, roman numerals (`Part IV`),
     `cont.`/`continued`.
   - Spelled-out chapter numbers: `Chapter One`, `Chapter Eighty Six` — matched via a
     "Chapter/Part <word-number>" regex, converted to an integer using the `text2num`
     library (handles compound number words correctly).
   - Topic/genre bracket tags that aren't part-number patterns (e.g. `[Sci-Fi]`,
     `[OC]`, `[Completed]`) are stripped from the base title used for grouping, but
     remain in the raw stored/searched title untouched.
2. **Part number extraction** — pulled from the same markers matched above. Posts with
   no extractable number keep `part_number = None`.
3. **Grouping** — posts with the same (normalized base title, author) form a candidate
   `DetectionMatch`. Author match is required, not just a confidence booster — it
   sharply cuts false-positive grouping between unrelated authors with similar titles.
4. **Confidence score** — combination of title-similarity ratio (e.g.
   `difflib.SequenceMatcher` over normalized base titles), whether part numbers form a
   clean ascending sequence, and time spacing between posts (serials post at roughly
   regular intervals; large gaps lower confidence).
5. **Ordering** — parts ordered by `part_number` when available; posts lacking a number
   are slotted by `created_utc` relative to numbered neighbors.
6. **Output** — a list of `DetectionMatch` candidates, always reviewed in the curation
   screen (merge, split, drop, reorder) before becoming committed `Story`/`StoryPart`
   records.

### Find all parts (author-history expansion)

On-demand, per story (not automatic on every detection pass, to avoid unnecessary API
calls): given a selected story, pull the author's full submission history via
`reddit_client.py`, re-run the title-pattern matching above against that expanded set,
and surface any newly found candidate parts through the same curation flow for
confirm/merge. Used both for backfilling old parts missed by the initial subreddit
fetch window, and for finding new installments (e.g. parts 31-33 added to a
previously-tracked 30-part story).

## TUI Screens & Flow

- **Subreddit Browse** — fetch/list posts from the configured subreddit (manual fetch
  action); shows raw posts plus which ones detection has already grouped.
- **Search** — keyword/phrase box; queries the local FTS cache first, with an explicit
  "search Reddit live" action for broader `subreddit.search()` results (merged into
  cache on return). Search results link directly into the curation screen for a
  detected series, or straight to Story Detail if already committed.
- **Detected Series (curation)** — list of `DetectionMatch` candidates with confidence
  scores; actions to accept (commit as `Story`), merge two candidates, split a bad
  grouping, drop a false match, or manually reorder parts.
- **Story List** — tracked `Story` records: title, author, part count, last-read
  position, and whether new parts are available since last fetch.
- **Story Detail** — a selected story: part list; "select/track" action (triggers
  eager `PostBody` fetch for all known parts); "find all parts" action (author-history
  expansion); export actions.
- **Reader** — renders a tracked story's parts in order with a `## Part N` boundary
  notation between parts; resumes from `last_read_part` by default, with a manual jump
  to any part (e.g. to read only newly added installments).

Navigation is a standard Textual screen stack (push/pop); Story List is the home screen
after initial subreddit selection.

## CLI & Config

`pydantic-settings`-based layered configuration. Precedence for **every** user-facing
option (not just credentials): **CLI flags > config file > environment variables**.

- **`praw.ini`** — standard PRAW multi-profile credentials file; a `--praw-site` flag /
  config value / env var selects which named section (PRAW's own `site_name`
  mechanism) to use.
- **App config file** — e.g. `~/.config/reddit-reader/config.toml` (or `--config path`)
  for defaults: subreddit, database path, export directory, praw profile name, etc.
- **CLI (`cli.py`, built with `typer`)** subcommands:
  - `reddit-reader tui` — launch the interactive app (default if no subcommand given).
  - `reddit-reader fetch` — one-shot fetch into the cache without opening the TUI.
  - `reddit-reader export <story-id>` — one-shot export outside the TUI.
- All options resolve once at startup into a single `Settings` pydantic model, passed
  down to the rest of the app.

## Export

- **Story export (Markdown)** — regenerates the full file every time (simplest,
  always-consistent behavior, no drift risk from partial updates): all parts in order,
  each prefixed with a `## Part N — [source](url) — posted <date>` boundary, story
  title as an H1. Written to `exported_markdown_path` (default
  `<export-dir>/<sanitized-title>.md`), overwritten in place on re-export.
- **Links export** — a plain text/markdown file listing each part's title + original
  Reddit permalink in order, for a lightweight reading index instead of full text.
- Both actions live on Story Detail; the export path/state is recorded on the `Story`
  record so re-export knows what to overwrite.

## Error Handling

- Reddit API errors (rate limiting, auth failure, deleted/removed posts, network
  errors) are caught at the `reddit_client.py` boundary and re-raised as typed
  exceptions (e.g. `RedditFetchError`). The TUI catches these and shows a status
  message rather than crashing; no other module needs to know about PRAW's exception
  types.
- Detection ambiguity is not an error — low-confidence matches simply surface in
  curation for a human decision.

## Testing Strategy

- `pytest` throughout.
- `reddit_client.py` is mocked/faked at the PRAW boundary — no real network calls in
  tests.
- `detection.py` and `export.py` are pure-ish functions over pydantic models — unit
  tested directly with fixture titles, including bracket-tag stripping and
  spelled-out-chapter-number cases.
- `storage.py` is tested against a real temporary SQLite file (fast; no need to mock
  SQLite itself).
- TUI screens get lighter smoke-test coverage via Textual's built-in test harness
  (`Pilot`).

## Tooling Conventions

- **`uv`** for environment/dependency management (`uv sync`, `uv run`); `pyproject.toml`
  as the single source of truth for dependencies/metadata.
- **`ruff`** for both linting and formatting.
- **`mypy`** run strict (or close to it); pydantic models give near-free coverage across
  module boundaries.
- **`pydantic`** for all data models, settings, and PRAW response validation at the
  boundary — raw PRAW objects are converted into `PostMeta`/`PostBody` immediately, so
  nothing downstream touches PRAW types directly.
