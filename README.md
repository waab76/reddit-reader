# reddit-reader

Find, assemble, and read multi-part serial fiction scattered across a
subreddit (e.g. [r/HFY](https://reddit.com/r/HFY)) as single, ordered
stories — in a terminal UI or from the command line.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- A Reddit account and API credentials (see below)

## Install

```bash
git clone https://github.com/waab76/reddit-reader.git
cd reddit-reader
uv sync
```

This creates a `.venv` and installs the `reddit-reader` command inside it.
Run it with `uv run reddit-reader ...`, or activate the venv
(`source .venv/bin/activate`) and drop the `uv run` prefix.

## Reddit API credentials

reddit-reader authenticates via [PRAW](https://praw.readthedocs.io/) using a
standard `praw.ini` file, so credentials are never stored in the app's own
config.

1. Create a Reddit "script" app at
   <https://www.reddit.com/prefs/apps> (click "are you a developer? create
   an app...", choose type **script**, any name/redirect URI works — e.g.
   `http://localhost:8080`).
2. Create `praw.ini` in your current directory or `~/.config/praw.ini`:

   ```ini
   [default]
   client_id=<the string under your app's name>
   client_secret=<the "secret" field>
   user_agent=reddit-reader by u/<your-username>
   username=<your-username>
   password=<your-password>
   ```

   The section name (`default` here) is a **profile** — `praw.ini` can hold
   several, and reddit-reader picks one via the `praw_site` setting (see
   below). This lets you switch accounts without touching credentials.
3. See PRAW's own docs for the full file format and for using an app-only
   (script) token if you'd rather not store a password:
   <https://praw.readthedocs.io/en/stable/getting_started/configuration/prawini.html>

## Configuration

Every setting can come from three places, in this order of precedence
(highest wins): **CLI flags > config file > environment variables**.

The config file defaults to `~/.config/reddit-reader/config.toml`, or pass
`--config path/to/file.toml` to any command. Copy the sample and edit it:

```bash
mkdir -p ~/.config/reddit-reader
cp config.sample.toml ~/.config/reddit-reader/config.toml
```

See `config.sample.toml` in this repo for every available setting with
comments. The only one you'll likely want to change immediately is
`subreddits`.

Environment variables use the `REDDIT_READER_` prefix, e.g.
`REDDIT_READER_SUBREDDITS="HFY,Sexyspacebabes"` or
`REDDIT_READER_FETCH_LIMIT=200`.

## Usage

### Interactive (TUI)

```bash
uv run reddit-reader
# or explicitly:
uv run reddit-reader tui
```

Story List is the home screen. Key bindings by screen:

**Story List**
| Key | Action |
|---|---|
| `Enter` | Open selected story |
| `s` | Cycle sort (series / score / parts / recent) |
| `t` | Cycle tracked filter |
| `b` | Browse subreddit |
| `/` | Search |
| `g` | Storage admin |

**Story Detail**
| Key | Action |
|---|---|
| `r` | Read (opens Reader — requires tracking first) |
| `t` / `u` | Track / untrack |
| `f` | Find missing parts (only enabled when gaps exist) |
| `e` / `l` | Export story / export links index |
| `c` | Detect boilerplate (propose cleaning rules) |
| `Esc` | Back |

**Reader**
| Key | Action |
|---|---|
| `n` / `p` | Next / previous part |
| `s` | Toggle spoiler reveal |
| `Esc` | Back |

**Browse**
| Key | Action |
|---|---|
| `f` | Fetch from configured subreddit(s) |
| `l` | Cycle listing type (new / hot / top) |
| `Esc` | Back |

**Search**
| Key | Action |
|---|---|
| `Enter` | Search local cache |
| `Ctrl+R` | Search Reddit live |
| `Esc` | Back |

**Curation** (reviewing detected series before they become stories)
| Key | Action |
|---|---|
| `a` | Accept candidate |
| `d` | Drop candidate |
| `m` | Mark/merge two candidates |
| `Esc` | Back |

**Storage Admin**
| Key | Action |
|---|---|
| `p` | Prune orphaned post metadata |
| `u` | Untrack selected story (drops cached bodies) |
| `d` | Delete selected story (press twice to confirm) |
| `Esc` | Back |

Global: `q` quits, `Esc` also pops back a screen from anywhere.

### Command line

```bash
# Fetch posts into the local cache without opening the TUI
uv run reddit-reader fetch --subreddit HFY --limit 50

# List committed stories with their ids, part counts, and status
uv run reddit-reader list

# Export a story by id or "author/title" slug
uv run reddit-reader export 3
uv run reddit-reader export "BlueFishcake/the long road"
uv run reddit-reader export 3 --links   # links index instead of full text
```

All commands accept `--config path/to/file.toml`.

## Where things live

- **Local database**: `~/.local/share/reddit-reader/library.db` (SQLite +
  full-text search index) — cached post metadata, tracked story bodies,
  read progress, curation state.
- **Exports**: `~/reddit-reader-exports/` — Markdown story files and links
  indexes, named `<author>-<title>[-vol<N>].md`.

Both paths are configurable — see `config.sample.toml`.

## Development

```bash
uv sync                          # install with dev dependencies
uv run pytest                    # run the test suite
uv run ruff check . && uv run ruff format --check .
uv run mypy reddit_reader
```
