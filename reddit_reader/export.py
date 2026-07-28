"""Render assembled stories to Markdown or a links index."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from reddit_reader.cleaning import clean
from reddit_reader.models import CleaningRule, PostMeta, Story
from reddit_reader.ordering import OrderedPart, format_part_number

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


def _label(group: Sequence[OrderedPart]) -> str:
    lead = group[0]
    if lead.parsed.part_number is not None:
        number = format_part_number(lead.parsed.part_number)
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
    *,
    strip_known_patterns: bool = True,
) -> str:
    """Regenerate the complete story file from scratch.

    `strip_known_patterns` mirrors `Settings.cleaning_enabled` (the reader
    screen already respects this setting; export previously always stripped
    regardless of it).
    """
    chunks: list[str] = [f"# {story.title}", f"*by {story.author}*"]

    for group in groups:
        chunks.append(part_heading(group))
        segment_texts = [
            clean(bodies.get(part.post.id, ""), rules, strip_known_patterns=strip_known_patterns)
            for part in group
        ]
        chunks.append("\n\n".join(t for t in segment_texts if t))

    return "\n\n".join(chunk for chunk in chunks if chunk).strip() + "\n"


def render_links(
    story: Story,
    groups: Sequence[Sequence[OrderedPart]],
    alternates: Mapping[str, Sequence[PostMeta]] | None = None,
) -> str:
    """A lightweight reading index of permalinks, flagging any that are dead.

    `alternates` maps a canonical post's id to the mirrored/crossposted copies
    that were collapsed into it, so a duplicate isn't just discarded — the
    index can still cite it as an alternate source.
    """
    alternates = alternates or {}
    lines: list[str] = [f"# {story.title}", f"*by {story.author}*", ""]

    for group in groups:
        for part in group:
            note = "" if part.post.available else "  *(unavailable — post removed)*"
            line = f"- {_label(group)}: [{part.post.title}]({part.post.url}){note}"
            alts = alternates.get(part.post.id)
            if alts:
                mirrors = ", ".join(f"[mirror]({alt.url})" for alt in alts)
                line += f"  (also: {mirrors})"
            lines.append(line)

    return "\n".join(lines).strip() + "\n"


def write_export(path: Path, content: str) -> None:
    """Write `content` to `path`, creating parents and overwriting in place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
