from decimal import Decimal

from reddit_reader.detection import (
    DEFAULT_ATTACH_THRESHOLD,
    decide_attachment,
    find_gaps,
)
from reddit_reader.models import DetectionMatch, Story


def d(*values: str) -> list[Decimal]:
    return [Decimal(v) for v in values]


def test_contiguous_sequence_has_no_gaps() -> None:
    assert find_gaps(d("1", "2", "3")) == []


def test_interior_gap_is_reported() -> None:
    assert find_gaps(d("1", "2", "3", "5", "6")) == d("4")


def test_multiple_interior_gaps_are_reported() -> None:
    assert find_gaps(d("1", "4", "7")) == d("2", "3", "5", "6")


def test_missing_start_is_reported() -> None:
    assert find_gaps(d("5", "6", "7")) == d("1", "2", "3", "4")


def test_trailing_parts_are_never_a_gap() -> None:
    assert find_gaps(d("1", "2", "3")) == []


def test_empty_sequence_has_no_gaps() -> None:
    assert find_gaps([]) == []


def test_decimal_parts_do_not_create_gaps() -> None:
    assert find_gaps(d("1", "1.5", "2")) == []


def test_unavailable_numbers_are_suppressed() -> None:
    assert find_gaps(d("1", "2", "5"), unavailable=d("3", "4")) == []


def test_partially_unavailable_gap_still_reports_the_rest() -> None:
    assert find_gaps(d("1", "5"), unavailable=d("3")) == d("2", "4")


def test_duplicate_numbers_do_not_break_gap_detection() -> None:
    assert find_gaps(d("1", "2", "2", "4")) == d("3")


def test_high_confidence_match_on_existing_story_auto_attaches() -> None:
    match = DetectionMatch(
        base_title="road", author="A", volume=None, post_ids=["x"], confidence=0.95
    )
    story = Story(id=7, series_key="a:road", title="Road", author="A")
    decision = decide_attachment(match, story, DEFAULT_ATTACH_THRESHOLD)
    assert decision.action == "auto_attach"
    assert decision.story_id == 7


def test_low_confidence_match_on_existing_story_goes_to_curation() -> None:
    match = DetectionMatch(
        base_title="road", author="A", volume=None, post_ids=["x"], confidence=0.4
    )
    story = Story(id=7, series_key="a:road", title="Road", author="A")
    decision = decide_attachment(match, story, DEFAULT_ATTACH_THRESHOLD)
    assert decision.action == "curate"
    assert decision.story_id == 7


def test_match_with_no_existing_story_is_a_new_series() -> None:
    match = DetectionMatch(
        base_title="road", author="A", volume=None, post_ids=["x"], confidence=0.99
    )
    decision = decide_attachment(match, None, DEFAULT_ATTACH_THRESHOLD)
    assert decision.action == "new_series"
    assert decision.story_id is None


def test_threshold_boundary_is_inclusive() -> None:
    match = DetectionMatch(
        base_title="road", author="A", volume=None, post_ids=["x"], confidence=0.85
    )
    story = Story(id=1, series_key="a:road", title="Road", author="A")
    assert decide_attachment(match, story, 0.85).action == "auto_attach"
