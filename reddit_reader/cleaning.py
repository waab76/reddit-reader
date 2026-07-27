"""Remove recurring boilerplate from post bodies at render time.

Nothing here mutates stored text. `PostBody.selftext` always holds the raw post,
so patterns can improve and decisions can be revoked without re-fetching.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from difflib import SequenceMatcher

from pydantic import BaseModel

from reddit_reader.models import CleaningPosition, CleaningRule

_NAV_LABELS = r"(?:first|prev|previous|next|index|wiki)"
_NAV_LINE_RE = re.compile(
    rf"^\s*(?:\[{_NAV_LABELS}\]\([^)]*\)\s*[|\-\u2013\u2014]?\s*)+$",
    re.IGNORECASE | re.MULTILINE,
)

_PLUG_HOSTS = r"(?:patreon|royalroad|ko-?fi|subscribestar|buymeacoffee|topwebfiction)"
_PLUG_LINE_RE = re.compile(rf"^.*{_PLUG_HOSTS}.*$", re.IGNORECASE | re.MULTILINE)

_SIGNOFF_RE = re.compile(
    r"^\s*(?:"
    r"hope you (?:enjoyed|liked)"
    r"|thanks for reading"
    r"|comments? (?:and criticism )?(?:are )?welcome"
    r"|let me know what you think"
    r"|as always[,.]? (?:thanks|thank you)"
    r").*$",
    re.IGNORECASE,
)

_BLANK_RUN_RE = re.compile(r"\n{3,}")

# Sign-offs are trailing author's-note content, never something a story opens or
# passes through mid-narrative. HFY-genre dialogue can plausibly start a line with
# "Thanks for reading the report, Captain" or similar, so `_SIGNOFF_RE` is only
# ever applied to the last few non-blank lines of the body, not every line in it.
_TRAILING_SIGNOFF_WINDOW = 3


def _strip_trailing_signoffs(text: str) -> str:
    """Remove sign-off-shaped lines, but only near the end of the body."""
    lines = text.split("\n")
    non_blank_indices = [i for i, line in enumerate(lines) if line.strip()]
    for i in non_blank_indices[-_TRAILING_SIGNOFF_WINDOW:]:
        if _SIGNOFF_RE.match(lines[i]):
            lines[i] = ""
    return "\n".join(lines)


def strip_patterns(selftext: str) -> str:
    """Remove nav blocks, support plugs, and generic sign-offs."""
    text = _NAV_LINE_RE.sub("", selftext)
    text = _PLUG_LINE_RE.sub("", text)
    text = _strip_trailing_signoffs(text)
    return _BLANK_RUN_RE.sub("\n\n", text).strip()


# --- Learned per-story header/footer detection -----------------------------
#
# strip_patterns() above handles boilerplate that's common across *any* story
# (nav links, Patreon plugs, generic sign-offs). This section instead learns
# boilerplate that's specific to *one* story: an author's recurring chapter
# header or footer, discovered by comparing a story's parts against each other.

DEFAULT_WINDOW = 12
DEFAULT_MAJORITY = 0.6
DEFAULT_MIN_PARTS = 3

# Two lines count as "the same" boilerplate line above this similarity, which lets a
# header embedding a chapter number still match its counterparts in other parts.
LINE_MATCH_THRESHOLD = 0.7


class LearnedBlock(BaseModel):
    """A repeated header or footer discovered across a story's parts."""

    position: CleaningPosition
    block: str
    seen_in_parts: int


def _similar(left: str, right: str) -> bool:
    if not left.strip() and not right.strip():
        return True
    return SequenceMatcher(None, left.strip(), right.strip()).ratio() >= LINE_MATCH_THRESHOLD


def _edge_lines(text: str, window: int, *, trailing: bool) -> list[str]:
    lines = text.splitlines()
    return lines[-window:][::-1] if trailing else lines[:window]


def _prefix_cap(reference: list[str]) -> int:
    """Bound how far a candidate run may grow: up to, but excluding, the first
    blank line in the reference part's edge.

    A single-digit substitution (a chapter number) leaves a line's fuzzy-match
    ratio just as high whether that line is a recurring header or a piece of
    unique story content that merely follows the same template (see the
    "Story content unique to chapter N" fixture in the tests) - `_similar`
    alone cannot tell those apart, since the unique-content line's ratio across
    parts is *higher* than the header's. What does distinguish them is
    structure: real boilerplate is a self-contained paragraph, and unique
    content lives in the next paragraph, across a blank line. Capping the
    search at the first blank line keeps the run inside the boilerplate's own
    paragraph and out of the content that follows it.
    """
    for i, line in enumerate(reference):
        if not line.strip():
            return i
    return len(reference)


def _longest_common_run(edges: Sequence[list[str]], majority: float) -> tuple[list[str], int]:
    """Find the longest run of leading lines shared by at least `majority` of parts."""
    if not edges:
        return [], 0

    reference = edges[0]
    cap = _prefix_cap(reference)
    if cap == 0:
        return [], 0

    best_block: list[str] = []
    best_count = 0

    for length in range(cap, 0, -1):
        candidate = reference[:length]
        if not any(line.strip() for line in candidate):
            continue
        # `len(other) > length`, not `>=`: a block may only count a part toward
        # its majority if that part has content left over beyond the block. A
        # block that would consume a part's entire text isn't a header/footer
        # around unique content - it's just the whole part looking similar to
        # the reference, which is exactly what the "unique bodies" fixture
        # does (short, templated lines with no real boilerplate at all).
        count = sum(
            1
            for other in edges
            if len(other) > length
            and all(_similar(a, b) for a, b in zip(candidate, other[:length], strict=True))
        )
        if count / len(edges) >= majority:
            best_block, best_count = candidate, count
            break

    return best_block, best_count


def detect_boilerplate(
    bodies: Sequence[str],
    *,
    window: int = DEFAULT_WINDOW,
    majority: float = DEFAULT_MAJORITY,
    min_parts: int = DEFAULT_MIN_PARTS,
) -> list[LearnedBlock]:
    """Find repeated leading/trailing blocks across a story's parts.

    Repetition across two samples means nothing, so stories below `min_parts`
    return no suggestions at all.
    """
    if len(bodies) < min_parts:
        return []

    blocks: list[LearnedBlock] = []

    leading_edges = [_edge_lines(b, window, trailing=False) for b in bodies]
    leading_block, leading_count = _longest_common_run(leading_edges, majority)
    if leading_block:
        blocks.append(
            LearnedBlock(
                position=CleaningPosition.LEADING,
                block="\n".join(leading_block).strip(),
                seen_in_parts=leading_count,
            )
        )

    trailing_edges = [_edge_lines(b, window, trailing=True) for b in bodies]
    trailing_block, trailing_count = _longest_common_run(trailing_edges, majority)
    if trailing_block:
        blocks.append(
            LearnedBlock(
                position=CleaningPosition.TRAILING,
                block="\n".join(reversed(trailing_block)).strip(),
                seen_in_parts=trailing_count,
            )
        )

    return blocks


def apply_rules(selftext: str, rules: Sequence[CleaningRule]) -> str:
    """Remove blocks the user has explicitly approved. Never strips silently."""
    lines = selftext.splitlines()

    for rule in rules:
        if rule.approved is not True:
            continue
        block_lines = rule.block.splitlines()
        if not block_lines:
            continue

        if rule.position == CleaningPosition.LEADING:
            head = lines[: len(block_lines)]
            if len(head) == len(block_lines) and all(
                _similar(a, b) for a, b in zip(block_lines, head, strict=True)
            ):
                lines = lines[len(block_lines) :]
        else:
            tail = lines[-len(block_lines) :] if len(lines) >= len(block_lines) else []
            if tail and all(_similar(a, b) for a, b in zip(block_lines, tail, strict=True)):
                lines = lines[: -len(block_lines)]

    return _BLANK_RUN_RE.sub("\n\n", "\n".join(lines)).strip()


def clean(
    selftext: str,
    rules: Sequence[CleaningRule],
    *,
    strip_known_patterns: bool = True,
) -> str:
    """Full render-time cleaning: known pattern stripping, then approved learned rules.

    Pattern stripping runs first (not the other way around): a learned footer
    rule matches the tail of the text, and generic noise like a trailing
    support-me plug can otherwise sit after the real footer and hide it from
    the tail check. Stripping known patterns first restores the learned
    footer to the true end of the text before the rule looks for it.
    """
    text = strip_patterns(selftext) if strip_known_patterns else selftext
    return apply_rules(text, rules)
