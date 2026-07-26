# reddit-reader Design

## Purpose

A Python/PRAW-based interactive tool for finding, assembling, and reading multi-part
stories posted across multiple submissions to a subreddit (e.g. r/HFY), where a single
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
  detection.py    # series-detection heuristics, gap detection, gap-driven author-history expansion
  cleaning.py     # boilerplate stripping (nav links, plugs) — shared by reader and export
  export.py       # Markdown story export + links-file export
  tui/            # Textual app: browse, search, series list, reader, curation, "find missing parts" action
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
  `part_number` (nullable `Decimal` — supports `4.5`; `None` for named parts like
  `Interlude` and for posts with no extractable marker), `part_label` (the raw marker
  text, e.g. `Interlude`, for display), `segment` / `segment_count` (nullable — set when
  one part is split across posts by Reddit's character limit), `sort_key` (resolved
  ordering position), `match_confidence`.
- **`Story`** — `id`, `series_key` (shared across volumes of one serial), `title`
  (normalized base title), `volume` (nullable — Book/Season/Arc number when present),
  `author`, `tracked` (bool — gates body caching), `last_read_part`,
  `exported_markdown_path` (nullable), `exported_at` (nullable), `last_updated_at`.
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
2. **Part number extraction** — pulled from the same markers matched above, resolving
   three real-world complications:

   - **Two numbers in one title.** `Chapter 12 (2/2)` is one chapter split across posts
     to fit Reddit's per-post character limit — not chapter 2. The chapter/part marker
     always wins for `part_number`; the `(N/M)` is captured separately as
     `segment` / `segment_count`. Segments of the same part are concatenated in
     segment order and presented as a single continuous part in the reader and export.
   - **Non-integer parts.** `Part 4.5`, `Interlude`, `Prologue`, `Epilogue`,
     `Side Story: Kevin`. Ordering therefore uses a **sort key**, not a bare int:
     decimals sort naturally (4.5 between 4 and 5), and named parts anchor by
     `created_utc` relative to their numbered neighbors. Only whole numbers participate
     in gap detection.
   - **No extractable marker** — `part_number` stays `None` and the part is positioned
     by timestamp.
3. **Grouping** — posts with the same (normalized base title, author) form a candidate
   `DetectionMatch`. Author match is required, not just a confidence booster — it
   sharply cuts false-positive grouping between unrelated authors with similar titles.
4. **Confidence score** — combination of title-similarity ratio (e.g.
   `difflib.SequenceMatcher` over normalized base titles), whether part numbers form a
   clean ascending sequence, and time spacing between posts (serials post at roughly
   regular intervals; large gaps lower confidence).
5. **Ordering** — parts ordered by the sort key described above (whole numbers,
   decimals, then named parts anchored by `created_utc` relative to numbered
   neighbors); multi-segment parts are concatenated in segment order.
6. **Output** — a list of `DetectionMatch` candidates, always reviewed in the curation
   screen (merge, split, drop, reorder) before becoming committed `Story`/`StoryPart`
   records.

### Volumes, books, and numbering resets

Long serials restart numbering: `Book Two, Chapter 1` arrives after a 50-chapter Book
One. Kept in one story, that produces duplicate part numbers, broken ordering, and gap
detection screaming that chapters 2-50 went missing the moment Book Two started.

**Each volume becomes its own `Story`.** Book/Volume/Season/Arc markers are parsed out
of the title during normalization, and posts sharing a base title but differing in
volume are committed as separate `Story` records carrying the same `series_key` (derived
from the base title + author). Within a story, numbering is contiguous again, so
ordering and gap detection work unmodified.

The `series_key` keeps the volumes visibly related: Story List groups stories of one
series together, and Story Detail links to the sibling volumes so moving from the end of
Book One to the start of Book Two is one keystroke.

### Navigation-link expansion (tracked stories only)

Most serial authors put `[First] [Prev] [Next]` links in each post — the most reliable
linkage signal available, and far better than title parsing. But it lives in the body,
which is only cached for tracked stories, so it cannot drive initial detection without
reversing the storage decision.

The compromise: title parsing remains the primary detection method, and nav links are
used as a **secondary verification and expansion pass that runs only on tracked
stories**, where bodies are already local and the pass costs no extra API calls. It
parses `First`/`Prev`/`Next`/`Previous` links out of each cached body, resolves them to
Reddit post ids, and uses the resulting chain to:

- confirm or correct part ordering when title-derived numbers are absent or ambiguous,
  and
- surface parts the title matching missed (a chapter the author titled inconsistently),
  offered through the normal curation flow.

Links pointing at posts not in the cache are fetched as `PostMeta` and presented as
candidates; they are never silently added.

### Attaching new parts to existing stories

Curation is for discovering **new series**, not for re-approving every new chapter of a
series you already read. Without this distinction, a refresh that turns up new parts for
20 tracked stories would demand 20 curation passes, and you would stop refreshing.

So detection runs against committed stories first:

1. A newly fetched post whose (normalized base title, author) matches a **committed**
   `Story` is scored the same way as any other candidate.
2. Above a confidence threshold, it **auto-attaches**: a `StoryPart` row is created, the
   `PostBody` is fetched if the story is tracked, and `last_updated_at` is bumped. No
   prompt.
3. Below the threshold, it goes to the curation screen as an ambiguous match against
   that specific story ("looks like it belongs to X — attach?") rather than as a
   brand-new series candidate.
4. Posts matching no committed story follow the normal new-series curation flow.

**Unread state is derived, never stored.** A story has unread parts when any part orders
after `last_read_part`; the count shown in Story List is computed from the same ordering
the reader uses. There is no per-part read flag to keep in sync.

### Gap detection

After a story's parts are committed, the known `part_number` values are checked for
completeness. A **gap** is either:

- an **interior gap** — a missing number strictly between known parts (have 1-3 and
  5-8; part 4 is missing), or
- a **missing start** — the sequence doesn't begin at part 1 (have 5-30; parts 1-4 are
  missing).

Gaps are *computed on demand* from the story's `StoryPart` rows, not stored — there is
no gap state to keep in sync.

Trailing parts are deliberately **not** treated as a gap: newer installments appear in
the subreddit listing and are picked up by an ordinary manual refresh, so they need no
author-history lookup. Parts with `part_number = None` are excluded from the gap
calculation (they can't be positioned reliably), and a story whose parts are entirely
unnumbered simply reports no gaps.

### Find missing parts (author-history expansion)

Only runs when gap detection reports gaps — a story with a complete, contiguous
sequence has nothing to backfill, so the action is disabled and no API calls are made.

When gaps exist, the story is flagged in the UI with the specific missing parts (e.g.
"missing parts 4, 12"), and the "find missing parts" action becomes available. **You**
trigger it; it is never automatic. Triggering it pulls the author's submission history
via `reddit_client.py`, re-runs the title-pattern matching above against that expanded
set, and surfaces any newly found candidate parts through the same curation flow for
confirm/merge.

### Unavailable parts

Some gaps can never be filled: the author deleted the chapter, mods removed it, or the
author nuked their whole history on moving to Patreon or RoyalRoad. Left alone, those
gaps get flagged forever and "find missing parts" keeps failing on them.

An `unavailable_parts` record per story tracks part numbers known to be unfillable.
A number lands there when a "find missing parts" run completes without locating it, and
gap detection then stops reporting it — the story reads as complete-as-possible. You can
also mark a gap unavailable by hand, and clear the mark to force a re-check if you think
the post resurfaced.

Separately, a part **already cached** in a tracked story that later disappears from
Reddit keeps its locally cached body — that is precisely what the cache is for, and the
part stays readable and exportable. It is flagged as no longer available upstream so the
links export can note that its permalink is dead.

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
  position, whether new parts are available since last fetch, and a gap indicator for
  stories with missing parts.
- **Story Detail** — a selected story: part list with any missing parts called out
  explicitly; "select/track" action (triggers eager `PostBody` fetch for all known
  parts); "find missing parts" action (author-history expansion, enabled only when
  gaps are detected); export actions.
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

## Boilerplate Cleaning

Serial posts carry recurring cruft that is useful on Reddit and noise in an assembled
90-chapter file: `[First] [Prev] [Next]` navigation blocks, Patreon/RoyalRoad/Ko-fi
plugs, and "hope you enjoyed, comments welcome" sign-offs. Exported verbatim, that's 90
copies of each.

`cleaning.py` strips these by pattern before text reaches the reader or an export:

- navigation link blocks (`First`/`Prev`/`Previous`/`Next` link clusters),
- known external-support link plugs (Patreon, RoyalRoad, Ko-fi, and similar).

The **raw body is always stored untouched** in `PostBody`; cleaning is applied on
render, so the patterns can be improved later without re-fetching anything. Stripping is
toggleable in config for when you'd rather see the post as written.

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
  spelled-out-chapter-number cases. Gap detection is pure list-of-ints logic and gets
  direct cases: contiguous (no gaps), interior gap, missing start, unnumbered parts
  excluded, entirely-unnumbered story.
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
