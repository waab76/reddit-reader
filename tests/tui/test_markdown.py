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
