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
