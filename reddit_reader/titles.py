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

NAMED_PART_WORDS = (
    "interlude",
    "prologue",
    "epilogue",
    "side story",
    "intermission",
    "conclusion",
)

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
    r"\b(?:the\s+)?(" + "|".join(NAMED_PART_WORDS) + r")\b\s*:?",
    re.IGNORECASE,
)
_CONT_RE = re.compile(r"\(?\b(?:cont\.?|continued)\b\)?", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")
_SUBTITLE_STOP_RE = re.compile(r"[\[(]")
# A bare number with no "part"/"chapter"/etc. keyword, but only when it's the
# last meaningful thing in the title — trailing tags like "[OC]" are allowed
# after it, so "The Remote 3 [OC]" still counts. A number anywhere earlier
# ("Top 10 Places") is left alone, since it's far more likely to just be part
# of the title than an implicit part marker.
_TRAILING_NUMBER_RE = re.compile(r"(?<!\w)(\d+(?:\.\d+)?)\s*(?:[\[(][^\]\)]*[\])]\s*)*$")


def _strip_marker_and_subtitle(working: str, match: re.Match[str]) -> str:
    """Remove a part/chapter marker plus any per-part subtitle trailing it.

    Posts in the same series are often titled "<Base Title> - Part N <subtitle
    unique to this part>" (e.g. "Part 3 Homecoming"). Left in place, that
    subtitle text would leak into `base_title` and make otherwise-identical
    series fail to group since every part's title differs after the marker.
    Stop at the next bracketed tag/fraction segment (e.g. "[OC]", "(2/2)") so
    those are left for their own regexes to pick up.
    """
    stop = _SUBTITLE_STOP_RE.search(working, match.end())
    end = stop.start() if stop else len(working)
    return working[: match.start()] + " " + working[end:]


class ParsedTitle(BaseModel):
    """Structured view of a post title."""

    base_title: str
    display_title: str
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
    """Lowercase, strip punctuation, collapse whitespace.

    For `base_title`: a matching key, not something ever shown to a user, so
    stripping "can't" down to "can t" is harmless there — it just needs to be
    stable and comparable across differently-punctuated titles.
    """
    return _WS_RE.sub(" ", _PUNCT_RE.sub(" ", text)).strip().lower()


def _clean_display_title(text: str) -> str:
    """Collapse whitespace and trim leftover marker punctuation, but keep the
    original casing and punctuation (like apostrophes) intact — unlike
    `base_title`, this is shown to the user, so mangling "can't" into "can t"
    (and then into "Can T" once title-cased) is exactly what this avoids.
    """
    collapsed = _WS_RE.sub(" ", text).strip()
    return collapsed.strip(" -–—:,.|")  # noqa: RUF001


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
        working = _strip_marker_and_subtitle(working, numeric_match)

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
                working = _strip_marker_and_subtitle(working, word_match)

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
            working = _strip_marker_and_subtitle(working, named_match)

    if part_number is None and part_label is None:
        trailing_match = _TRAILING_NUMBER_RE.search(working)
        if trailing_match:
            part_number = Decimal(trailing_match.group(1))
            part_label = trailing_match.group(1)
            working = working[: trailing_match.start(1)] + " " + working[trailing_match.end(1) :]

    working = _CONT_RE.sub(" ", working)

    tags: list[str] = []
    for tag_match in _TAG_RE.finditer(working):
        tags.append(tag_match.group(1).strip())
    working = _TAG_RE.sub(" ", working)

    return ParsedTitle(
        base_title=_normalize(working),
        display_title=_clean_display_title(working),
        part_number=part_number,
        part_label=part_label,
        volume=volume,
        segment=segment,
        segment_count=segment_count,
        tags=tags,
    )
