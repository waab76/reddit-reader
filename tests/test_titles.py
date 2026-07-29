from decimal import Decimal

import pytest

from reddit_reader.titles import parse_title


def test_plain_part_marker() -> None:
    parsed = parse_title("The Long Road - Part 12")
    assert parsed.base_title == "the long road"
    assert parsed.part_number == Decimal("12")


def test_chapter_marker() -> None:
    assert parse_title("The Long Road, Chapter 7").part_number == Decimal("7")


def test_spelled_out_chapter_number() -> None:
    assert parse_title("The Long Road - Chapter One").part_number == Decimal("1")


def test_compound_spelled_out_chapter_number() -> None:
    assert parse_title("The Long Road - Chapter Eighty Six").part_number == Decimal("86")


def test_roman_numeral_part() -> None:
    assert parse_title("The Long Road - Part IV").part_number == Decimal("4")


def test_decimal_part_number() -> None:
    assert parse_title("The Long Road - Part 4.5").part_number == Decimal("4.5")


def test_bare_fraction_is_the_part_number() -> None:
    parsed = parse_title("The Long Road [3/10]")
    assert parsed.part_number == Decimal("3")
    assert parsed.segment is None


def test_fraction_is_a_segment_when_a_chapter_marker_is_present() -> None:
    parsed = parse_title("The Long Road - Chapter 12 (2/2)")
    assert parsed.part_number == Decimal("12")
    assert parsed.segment == 2
    assert parsed.segment_count == 2


def test_topic_tags_are_stripped_but_returned() -> None:
    parsed = parse_title("[OC] The Long Road - Part 3 [Sci-Fi]")
    assert parsed.base_title == "the long road"
    assert set(parsed.tags) == {"OC", "Sci-Fi"}


def test_volume_marker_is_extracted() -> None:
    parsed = parse_title("The Long Road, Book Two, Chapter 1")
    assert parsed.volume == 2
    assert parsed.part_number == Decimal("1")
    assert parsed.base_title == "the long road"


def test_numeric_volume_marker() -> None:
    assert parse_title("The Long Road Volume 3 - Part 5").volume == 3


def test_season_and_arc_are_volume_markers() -> None:
    assert parse_title("The Long Road Season 2 - Part 1").volume == 2
    assert parse_title("The Long Road Arc 4 - Part 1").volume == 4


@pytest.mark.parametrize("label", ["Interlude", "Prologue", "Epilogue"])
def test_named_parts_have_no_number_but_keep_a_label(label: str) -> None:
    parsed = parse_title(f"The Long Road - {label}")
    assert parsed.part_number is None
    assert parsed.part_label == label
    assert parsed.base_title == "the long road"


def test_side_story_is_a_named_part() -> None:
    parsed = parse_title("The Long Road - Side Story: Kevin")
    assert parsed.part_number is None
    assert parsed.part_label is not None
    assert parsed.part_label.startswith("Side Story")


def test_the_conclusion_groups_with_the_numbered_parts() -> None:
    numbered = parse_title("The Long Road. Part 1 [Tag] [Other-Tag]")
    conclusion = parse_title("The Long Road. The Conclusion. [Tag] [Other-Tag]")
    assert numbered.base_title == conclusion.base_title == "the long road"
    assert conclusion.part_number is None
    assert conclusion.part_label == "The Conclusion"


def test_named_part_does_not_swallow_a_hyphenated_tag() -> None:
    """A regression: the named-part regex used to capture everything up to the
    next hyphen, even inside a bracketed tag — corrupting both the base title
    and dropping every tag after the first hyphen it hit."""
    parsed = parse_title("The Long Road - Interlude [Sci-Fi] [Short]")
    assert parsed.base_title == "the long road"
    assert set(parsed.tags) == {"Sci-Fi", "Short"}


def test_continuation_marker_is_stripped() -> None:
    assert parse_title("The Long Road (cont.)").base_title == "the long road"


def test_continuation_marker_does_not_leak_into_tags() -> None:
    parsed = parse_title("The Long Road (cont.)")
    assert parsed.tags == []


def test_title_with_no_marker_yields_no_number() -> None:
    parsed = parse_title("The Long Road")
    assert parsed.part_number is None
    assert parsed.part_label is None
    assert parsed.base_title == "the long road"


def test_base_title_normalizes_whitespace_and_punctuation() -> None:
    assert parse_title("The   Long Road!! -- Part 2").base_title == "the long road"


def test_per_part_subtitle_does_not_leak_into_base_title() -> None:
    first = parse_title("A Multipart Story - Part 1 The First Part of the Story")
    second = parse_title("A Multipart Story - Part 2 The Story Continues")
    assert first.base_title == second.base_title == "a multipart story"
    assert first.part_number == Decimal("1")
    assert second.part_number == Decimal("2")


def test_trailing_bare_number_is_an_implicit_part_marker() -> None:
    first = parse_title("The Remote 1")
    third = parse_title("The Remote 3")
    assert first.base_title == third.base_title == "the remote"
    assert first.part_number == Decimal("1")
    assert third.part_number == Decimal("3")


def test_trailing_bare_number_survives_trailing_tags() -> None:
    parsed = parse_title("The Remote 3 [OC] [NSFW]")
    assert parsed.base_title == "the remote"
    assert parsed.part_number == Decimal("3")
    assert set(parsed.tags) == {"OC", "NSFW"}


def test_a_number_in_the_middle_of_a_title_is_not_a_part_marker() -> None:
    parsed = parse_title("Top 10 Places to Visit")
    assert parsed.part_number is None
    assert parsed.base_title == "top 10 places to visit"


def test_trailing_number_does_not_override_an_explicit_marker() -> None:
    assert parse_title("The Long Road - Part 2").part_number == Decimal("2")


def test_trailing_number_does_not_override_a_named_part() -> None:
    parsed = parse_title("The Long Road - Interlude")
    assert parsed.part_number is None
    assert parsed.part_label == "Interlude"


def test_display_title_keeps_the_apostrophe() -> None:
    """A regression: `base_title` strips all punctuation for matching purposes
    (apostrophe included, "can't" -> "can t"), and that value used to be
    reused as the displayed story title too — so "I Can't Read" rendered as
    "I Can T Read" once title-cased. `display_title` is for showing to a
    user and must never go through that normalization."""
    parsed = parse_title("I Can't Read")
    assert parsed.display_title == "I Can't Read"
    assert parsed.base_title == "i can t read"


def test_display_title_strips_markers_and_tags_but_keeps_casing() -> None:
    parsed = parse_title("the Long road - Part 3 [OC]")
    assert parsed.display_title == "the Long road"
    assert set(parsed.tags) == {"OC"}
