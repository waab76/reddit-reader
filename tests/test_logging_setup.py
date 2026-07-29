import logging
from pathlib import Path

import pytest

import reddit_reader.logging_setup as logging_setup
from reddit_reader.config import Settings
from reddit_reader.logging_setup import configure_logging


@pytest.fixture(autouse=True)
def _reset_configured_flag() -> None:
    """`configure_logging` only takes effect once per process; reset the guard
    and detach any handler it installed so each test starts clean."""
    logging_setup._configured = False
    logger = logging.getLogger("reddit_reader")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    yield
    logging_setup._configured = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)


def test_configure_logging_creates_the_log_file(tmp_path: Path) -> None:
    settings = Settings(log_path=tmp_path / "sub" / "rr.log")  # type: ignore[arg-type]
    configure_logging(settings)
    logging.getLogger("reddit_reader.somewhere").info("hello")
    assert settings.log_path.exists()
    assert "hello" in settings.log_path.read_text()


def test_configure_logging_respects_the_configured_level(tmp_path: Path) -> None:
    settings = Settings(log_path=tmp_path / "rr.log", log_level="WARNING")  # type: ignore[arg-type]
    configure_logging(settings)
    logging.getLogger("reddit_reader.somewhere").info("should not appear")
    logging.getLogger("reddit_reader.somewhere").warning("should appear")
    text = settings.log_path.read_text()
    assert "should not appear" not in text
    assert "should appear" in text


def test_configure_logging_only_takes_effect_once(tmp_path: Path) -> None:
    first = Settings(log_path=tmp_path / "first.log")  # type: ignore[arg-type]
    second = Settings(log_path=tmp_path / "second.log")  # type: ignore[arg-type]
    configure_logging(first)
    configure_logging(second)
    logging.getLogger("reddit_reader.somewhere").info("hello")
    assert first.log_path.exists()
    assert not second.log_path.exists()


def test_configure_logging_does_not_propagate_to_root(tmp_path: Path) -> None:
    """The TUI owns the terminal — a record reaching the root logger's default
    handler would print to stderr and corrupt the screen. (pytest's `caplog`
    fixture deliberately captures logs even from `propagate=False` loggers to
    stay useful in tests, so it can't be used to observe this — check the
    configuration directly instead.)"""
    settings = Settings(log_path=tmp_path / "rr.log")  # type: ignore[arg-type]
    configure_logging(settings)
    assert logging.getLogger("reddit_reader").propagate is False
