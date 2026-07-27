"""Render assembled stories to Markdown or a links index."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path

from reddit_reader.cleaning import clean
from reddit_reader.models import CleaningRule, Story
from reddit_reader.ordering import OrderedPart

_UNSAFE_RE = re.compile(r"[^\w\s-]")
_WS_RE = re.compile(r"\s+")


def _slug(text: str) -> str:
    return _WS_RE.sub("-", _UNSAFE_RE.sub("", text).strip())


def export_filename(story: Story) -> str:
    """`<author>-<sanitized-title>[-vol<N>].md`, qualified so same-named serials never collide."""
    parts = [_slug(story.author), _slug(story.title)]
    name = "-".join(p for p in parts if p)
    if story.volume is not None:
        name = f"{name}-vol{story.volume}"
    return f"{name}.md"


def _format_number(value: Decimal) -> str:
    """Render a part number without trailing zeros, never in scientific notation.

    `Decimal.normalize()` collapses whole numbers like 10 or 100 to scientific
    notation ("1E+1", "1E+2"), which would render as "Part 1E+2" instead of
    "Part 100". Whole numbers are formatted as plain integers; only genuinely
    fractional numbers (e.g. 12.50) go through `normalize()` to drop trailing
    zeros, which is safe there since the exponent stays non-positive.
    """
    if value == value.to_integral_value():
        return str(int(value))
    return str(value.normalize())


def _label(group: Sequence[OrderedPart]) -> str:
    lead = group[0]
    if lead.parsed.part_number is not None:
        number = _format_number(lead.parsed.part_number)
        return f"Part {number}"
    if lead.parsed.part_label:
        return lead.parsed.part_label
    return lead.post.title


def part_heading(group: Sequence[OrderedPart]) -> str:
    """A boundary heading naming the part and citing every source post."""
    sources = " ".join(f"[source]({part.post.url})" for part in group)
    posted = group[0].post.created_utc.date().isoformat()
    return f"## {_label(group)} — {sources} — posted {posted}"


def render_markdown(
    story: Story,
    groups: Sequence[Sequence[OrderedPart]],
    bodies: Mapping[str, str],
    rules: Sequence[CleaningRule],
) -> str:
    """Regenerate the complete story file from scratch."""
    chunks: list[str] = [f"# {story.title}", f"*by {story.author}*"]

    for group in groups:
        chunks.append(part_heading(group))
        segment_texts = [clean(bodies.get(part.post.id, ""), rules) for part in group]
        chunks.append("\n\n".join(t for t in segment_texts if t))

    return "\n\n".join(chunk for chunk in chunks if chunk).strip() + "\n"


def render_links(story: Story, groups: Sequence[Sequence[OrderedPart]]) -> str:
    """A lightweight reading index of permalinks, flagging any that are dead."""
    lines: list[str] = [f"# {story.title}", f"*by {story.author}*", ""]

    for group in groups:
        for part in group:
            note = "" if part.post.available else "  *(unavailable — post removed)*"
            lines.append(f"- {_label(group)}: [{part.post.title}]({part.post.url}){note}")

    return "\n".join(lines).strip() + "\n"


def write_export(path: Path, content: str) -> None:
    """Write `content` to `path`, creating parents and overwriting in place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
