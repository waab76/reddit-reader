"""Parse Reddit serial-fiction post titles into structured parts.

The raw title is never modified. Everything here produces derived values used
for grouping comparisons and ordering.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, Field
from text_to_num import text2num

ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}

NAMED_PART_WORDS = ("interlude", "prologue", "epilogue", "side story", "intermission")

_TAG_RE = re.compile(r"[\[(]([^\]\)]+)[\])]")
_FRACTION_RE = re.compile(r"[\[(](\d+)\s*/\s*(\d+)[\])]")
_VOLUME_RE = re.compile(
    r"\b(?:book|volume|vol\.?|season|arc)\s+([\w.]+)\b",
    re.IGNORECASE,
)
_NUMERIC_PART_RE = re.compile(
    r"\b(?:part|chapter|ch\.?|pt\.?|episode|ep\.?)\s*#?\s*(\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)
_WORD_PART_RE = re.compile(
    r"\b(?:part|chapter)\s+([a-z][a-z\s-]*?)(?=\s*(?:[-–—:,.|]|$))",  # noqa: RUF001
    re.IGNORECASE,
)
_NAMED_PART_RE = re.compile(
    r"\b(" + "|".join(NAMED_PART_WORDS) + r")\b\s*:?\s*([^\-–—|]*)",  # noqa: RUF001
    re.IGNORECASE,
)
_CONT_RE = re.compile(r"\(?\b(?:cont\.?|continued)\b\)?", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


class ParsedTitle(BaseModel):
    """Structured view of a post title."""

    base_title: str
    part_number: Decimal | None = None
    part_label: str | None = None
    volume: int | None = None
    segment: int | None = None
    segment_count: int | None = None
    tags: list[str] = Field(default_factory=list)


def _roman_to_int(text: str) -> int | None:
    lowered = text.lower()
    if not lowered or any(ch not in ROMAN_VALUES for ch in lowered):
        return None
    total = 0
    previous = 0
    for ch in reversed(lowered):
        value = ROMAN_VALUES[ch]
        total = total - value if value < previous else total + value
        previous = max(previous, value)
    return total


def _words_to_int(text: str) -> int | None:
    cleaned = text.strip().replace("-", " ")
    if not cleaned:
        return None
    try:
        return int(text2num(cleaned, "en"))
    except (ValueError, TypeError):
        return None


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    return _WS_RE.sub(" ", _PUNCT_RE.sub(" ", text)).strip().lower()


def parse_title(raw: str) -> ParsedTitle:
    """Extract part number, label, volume, segment, and tags from a raw title."""
    working = raw

    volume: int | None = None
    volume_match = _VOLUME_RE.search(working)
    if volume_match:
        token = volume_match.group(1)
        volume = int(token) if token.isdigit() else _words_to_int(token) or _roman_to_int(token)
        if volume is not None:
            working = working[: volume_match.start()] + " " + working[volume_match.end() :]

    part_number: Decimal | None = None
    part_label: str | None = None
    segment: int | None = None
    segment_count: int | None = None

    numeric_match = _NUMERIC_PART_RE.search(working)
    if numeric_match:
        try:
            part_number = Decimal(numeric_match.group(1))
        except InvalidOperation:
            part_number = None
        part_label = numeric_match.group(0).strip()
        working = working[: numeric_match.start()] + " " + working[numeric_match.end() :]

    if part_number is None:
        word_match = _WORD_PART_RE.search(working)
        if word_match:
            candidate = word_match.group(1).strip()
            value = _words_to_int(candidate)
            if value is None:
                value = _roman_to_int(candidate)
            if value is not None:
                part_number = Decimal(value)
                part_label = word_match.group(0).strip()
                working = working[: word_match.start()] + " " + working[word_match.end() :]

    fraction_match = _FRACTION_RE.search(working)
    if fraction_match:
        first, second = int(fraction_match.group(1)), int(fraction_match.group(2))
        if part_number is None:
            # Only number in the title: it *is* the part number.
            part_number = Decimal(first)
        else:
            # A chapter/part marker is also present: this is a segment marker.
            segment, segment_count = first, second
        working = working[: fraction_match.start()] + " " + working[fraction_match.end() :]

    if part_number is None:
        named_match = _NAMED_PART_RE.search(working)
        if named_match:
            part_label = named_match.group(0).strip().rstrip(":").strip()
            working = working[: named_match.start()] + " " + working[named_match.end() :]

    working = _CONT_RE.sub(" ", working)

    tags: list[str] = []
    for tag_match in _TAG_RE.finditer(working):
        tags.append(tag_match.group(1).strip())
    working = _TAG_RE.sub(" ", working)

    return ParsedTitle(
        base_title=_normalize(working),
        part_number=part_number,
        part_label=part_label,
        volume=volume,
        segment=segment,
        segment_count=segment_count,
        tags=tags,
    )
