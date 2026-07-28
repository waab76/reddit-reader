"""Command line entry point."""

from __future__ import annotations

from pathlib import Path

import typer

from reddit_reader.config import Settings, build_reddit, load_settings
from reddit_reader.models import Story
from reddit_reader.reddit_client import RedditClient, RedditError
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
    config: Path | None = typer.Option(None, help="Path to a config file."),  # noqa: B008
) -> None:
    """Fetch posts into the local cache without opening the TUI."""
    settings = _settings(
        config,
        subreddits=subreddit or None,
        listing=listing,
        fetch_limit=limit,
    )
    service = build_service(settings)
    try:
        result = service.fetch()
    except RedditError as exc:
        typer.echo(f"Reddit fetch failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"Fetched {result.fetched} posts. "
        f"Auto-attached {result.auto_attached} new parts. "
        f"{len(result.candidates)} candidates awaiting curation."
    )


@app.command("list")
def list_stories(
    config: Path | None = typer.Option(None, help="Path to a config file."),  # noqa: B008
) -> None:
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
    config: Path | None = typer.Option(None, help="Path to a config file."),  # noqa: B008
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
def tui(
    config: Path | None = typer.Option(None, help="Path to a config file."),  # noqa: B008
) -> None:
    """Launch the interactive reader."""
    from reddit_reader.tui.app import RedditReaderApp

    service = build_service(_settings(config))
    RedditReaderApp(service).run()


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Launch the TUI when no subcommand is given."""
    if ctx.invoked_subcommand is None:
        # Call the plain function directly rather than `ctx.invoke(tui)`: typer's
        # `ctx.invoke` does not fill in defaults for parameters it isn't given, so
        # `config` would bind to its raw `typer.OptionInfo` default object instead
        # of `None`, crashing config.py's `_read_config_file` with a confusing
        # "'bool' object is not callable".
        tui(config=None)
