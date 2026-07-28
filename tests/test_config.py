from pathlib import Path

import pytest

import reddit_reader.config as config_module
from reddit_reader.config import Settings, load_settings


@pytest.fixture(autouse=True)
def _isolate_default_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test in this module that omits `config_path` falls through to
    `DEFAULT_CONFIG_PATH` — the real `~/.config/reddit-reader/config.toml` this
    app tells users to create. Point it somewhere that can never exist so the
    suite never reads real machine state, regardless of what's installed on the
    machine running it."""
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", tmp_path / "nonexistent.toml")


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


def test_subreddits_accept_a_comma_separated_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDDIT_READER_SUBREDDITS", "HFY, Sexyspacebabes")
    settings = load_settings()
    assert settings.subreddits == ["HFY", "Sexyspacebabes"]


def test_database_path_expands_user_when_set_via_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REDDIT_READER_DATABASE_PATH", "~/env-db.db")
    settings = load_settings()
    assert "~" not in str(settings.database_path)


def test_database_path_expands_user_when_set_via_config_file(tmp_path: Path) -> None:
    path = write_config(tmp_path, 'database_path = "~/file-db.db"\n')
    settings = load_settings(config_path=path)
    assert "~" not in str(settings.database_path)


def test_subreddit_order_is_preserved_for_dedupe_priority() -> None:
    settings = Settings(subreddits=["First", "Second"])
    assert settings.subreddits[0] == "First"


def test_paths_expand_user(tmp_path: Path) -> None:
    settings = Settings(database_path="~/rr.db")  # type: ignore[arg-type]
    assert "~" not in str(settings.database_path)
