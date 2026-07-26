"""Resolve reading order for a story's parts.

Numbered parts sort by number. Unnumbered/named parts anchor to the most recent
numbered part that precedes them in time, so an Interlude posted between chapters
7 and 8 reads in that position. Segments of one part stay together.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from pydantic import BaseModel

from reddit_reader.models import PostMeta
from reddit_reader.titles import ParsedTitle

# Anchors are rendered into a zero-padded string so sort keys compare correctly
# as text, which lets them be stored in SQLite and sorted by SQL if needed.
_ANCHOR_WIDTH = 8
_ANCHOR_PRECISION = 3


class OrderedPart(BaseModel):
    """A post with its resolved position in a story."""

    post: PostMeta
    parsed: ParsedTitle
    anchor: Decimal
    tiebreak: int
    sort_key: str


def _format_sort_key(anchor: Decimal, tiebreak: int, created: float, segment: int) -> str:
    scaled = int(anchor * (10**_ANCHOR_PRECISION))
    return f"{scaled:0{_ANCHOR_WIDTH}d}|{tiebreak}|{created:015.3f}|{segment:03d}"


def resolve_order(items: Sequence[tuple[PostMeta, ParsedTitle]]) -> list[OrderedPart]:
    """Return the items in reading order with anchors and sort keys resolved."""
    if not items:
        return []

    by_time = sorted(items, key=lambda pair: pair[0].created_utc)
    numbers = [parsed.part_number for _, parsed in by_time if parsed.part_number is not None]
    fallback_anchor = (min(numbers) - 1) if numbers else Decimal(0)

    resolved: list[OrderedPart] = []
    current_anchor = fallback_anchor

    for post, parsed in by_time:
        if parsed.part_number is not None:
            current_anchor = parsed.part_number
            anchor, tiebreak = parsed.part_number, 0
        else:
            anchor, tiebreak = current_anchor, 1

        resolved.append(
            OrderedPart(
                post=post,
                parsed=parsed,
                anchor=anchor,
                tiebreak=tiebreak,
                sort_key=_format_sort_key(
                    anchor,
                    tiebreak,
                    post.created_utc.timestamp(),
                    parsed.segment or 0,
                ),
            )
        )

    return sorted(resolved, key=lambda part: part.sort_key)


def group_segments(parts: Sequence[OrderedPart]) -> list[list[OrderedPart]]:
    """Group consecutive segments of one logical part together."""
    groups: list[list[OrderedPart]] = []
    for part in parts:
        previous = groups[-1][-1] if groups else None
        same_part = (
            previous is not None
            and part.parsed.segment is not None
            and previous.parsed.segment is not None
            and part.parsed.part_number is not None
            and previous.parsed.part_number == part.parsed.part_number
        )
        if same_part:
            groups[-1].append(part)
        else:
            groups.append([part])
    return groups
