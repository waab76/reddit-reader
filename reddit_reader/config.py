"""Layered configuration: CLI flags > config file > environment variables."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from reddit_reader.reddit_client import ListingType, TimeWindow

DEFAULT_CONFIG_PATH = Path("~/.config/reddit-reader/config.toml").expanduser()


class Settings(BaseSettings):
    """Every user-facing option, resolved once at startup."""

    model_config = SettingsConfigDict(
        env_prefix="REDDIT_READER_",
        extra="ignore",
    )

    # NoDecode: env values for list fields are JSON-decoded by default, which
    # breaks a plain comma-separated string like "HFY, Sexyspacebabes". Turning
    # decoding off lets the raw string reach `_split_subreddits` below.
    subreddits: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["HFY"])
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
