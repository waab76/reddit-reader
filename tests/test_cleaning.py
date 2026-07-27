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
