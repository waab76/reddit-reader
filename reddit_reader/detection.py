"""Group posts into candidate series and score how confident the grouping is."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from decimal import Decimal
from difflib import SequenceMatcher
from itertools import pairwise
from typing import Literal

from pydantic import BaseModel

from reddit_reader.dedupe import DEFAULT_WINDOW_HOURS, collapse_duplicates
from reddit_reader.models import DetectionMatch, PostMeta, Story
from reddit_reader.ordering import resolve_order
from reddit_reader.titles import ParsedTitle, parse_title

DELETED_AUTHOR = "[deleted]"

# Confidence weights. Title similarity dominates because it is the primary signal;
# numbering and cadence refine it.
WEIGHT_TITLE = 0.5
WEIGHT_NUMBERING = 0.3
WEIGHT_CADENCE = 0.2

# A serial posting more than this many days apart looks abandoned or mis-grouped.
CADENCE_TOLERANCE_DAYS = 120.0


def series_key(author: str, base_title: str) -> str:
    """Stable identity for a serial across its volumes."""
    return f"{author.lower()}:{base_title}"


def _title_similarity(parsed: Sequence[ParsedTitle]) -> float:
    if len(parsed) < 2:
        return 1.0
    reference = parsed[0].base_title
    ratios = [SequenceMatcher(None, reference, p.base_title).ratio() for p in parsed[1:]]
    return min(ratios)


def _numbering_score(parsed: Sequence[ParsedTitle]) -> float:
    numbers = [p.part_number for p in parsed if p.part_number is not None]
    if not numbers:
        return 0.0
    coverage = len(numbers) / len(parsed)
    unique = len(set(numbers)) == len(numbers)
    return coverage * (1.0 if unique else 0.5)


def _cadence_score(posts: Sequence[PostMeta]) -> float:
    if len(posts) < 2:
        return 1.0
    times = sorted(p.created_utc for p in posts)
    gaps = [(later - earlier).total_seconds() / 86400 for earlier, later in pairwise(times)]
    median_gap = statistics.median(gaps)
    if median_gap <= 0:
        return 1.0
    return max(0.0, min(1.0, CADENCE_TOLERANCE_DAYS / (median_gap + CADENCE_TOLERANCE_DAYS) * 2))


def _score(posts: Sequence[PostMeta], parsed: Sequence[ParsedTitle]) -> tuple[float, list[str]]:
    title = _title_similarity(parsed)
    numbering = _numbering_score(parsed)
    cadence = _cadence_score(posts)
    confidence = WEIGHT_TITLE * title + WEIGHT_NUMBERING * numbering + WEIGHT_CADENCE * cadence
    reasons = [
        f"titles {title:.0%} similar",
        f"part numbering score {numbering:.2f}",
        f"posting cadence score {cadence:.2f}",
    ]
    return round(min(1.0, max(0.0, confidence)), 4), reasons


def group_posts(
    posts: Sequence[PostMeta],
    subreddit_priority: Sequence[str],
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> list[DetectionMatch]:
    """Collapse duplicates, then group the survivors into candidate series."""
    groups = collapse_duplicates(posts, subreddit_priority, window_hours=window_hours)
    canonical = [group.canonical for group in groups]

    # Per canonical post, which alternate (mirrored/crossposted) ids were
    # collapsed into it, so the resulting StoryPart can cite them later instead
    # of silently discarding them.
    alternates_by_canonical: dict[str, list[str]] = {
        group.canonical.id: [alt.id for alt in group.alternates]
        for group in groups
        if group.alternates
    }

    def _alternates_for(post_ids: Sequence[str]) -> dict[str, list[str]]:
        return {
            pid: alternates_by_canonical[pid] for pid in post_ids if pid in alternates_by_canonical
        }

    buckets: dict[tuple[str, str, int | None], list[tuple[PostMeta, ParsedTitle]]] = {}
    solo: list[tuple[PostMeta, ParsedTitle]] = []

    for post in canonical:
        parsed = parse_title(post.title)
        if post.author == DELETED_AUTHOR:
            # A deleted account is not an identity: never let it satisfy author match.
            solo.append((post, parsed))
            continue
        key = (post.author.lower(), parsed.base_title, parsed.volume)
        buckets.setdefault(key, []).append((post, parsed))

    matches: list[DetectionMatch] = []
    for (_author_key, base_title, volume), items in buckets.items():
        ordered = resolve_order(items)
        group_posts_list = [part.post for part in ordered]
        group_parsed = [part.parsed for part in ordered]
        confidence, reasons = _score(group_posts_list, group_parsed)
        post_ids = [p.id for p in group_posts_list]
        matches.append(
            DetectionMatch(
                base_title=base_title,
                author=group_posts_list[0].author,
                volume=volume,
                post_ids=post_ids,
                confidence=confidence,
                reasons=reasons,
                alternate_post_ids=_alternates_for(post_ids),
            )
        )

    for post, parsed in solo:
        confidence, reasons = _score([post], [parsed])
        matches.append(
            DetectionMatch(
                base_title=parsed.base_title,
                author=post.author,
                volume=parsed.volume,
                post_ids=[post.id],
                confidence=confidence,
                reasons=[*reasons, "author is [deleted]; grouping requires review"],
                alternate_post_ids=_alternates_for([post.id]),
            )
        )

    return matches


DEFAULT_ATTACH_THRESHOLD = 0.85


class AttachDecision(BaseModel):
    """What to do with a detection match: attach silently, curate, or treat as new."""

    action: Literal["auto_attach", "curate", "new_series"]
    story_id: int | None
    confidence: float


# A mis-parsed title can produce a spurious part number in the thousands or
# millions (e.g. matching a stray number in the text as a "part"). Without a
# cap, `find_gaps` would iterate `range(1, that_number)` — potentially millions
# of `Decimal` allocations — on every redraw of Story List, freezing the TUI.
# No real serial runs anywhere near this many parts.
MAX_GAP_SEARCH = 1000


def find_gaps(
    part_numbers: Sequence[Decimal], unavailable: Sequence[Decimal] = ()
) -> list[Decimal]:
    """Return whole-number parts missing from the start of, or inside, the sequence.

    Trailing parts are deliberately not gaps: newer installments arrive via an
    ordinary refresh and need no author-history lookup. The search is capped at
    `MAX_GAP_SEARCH`, so a spuriously large parsed part number can't hang the
    caller — gaps past the cap are simply not reported.
    """
    whole = sorted({n for n in part_numbers if n == n.to_integral_value()})
    if not whole:
        return []

    suppressed = set(unavailable)
    highest = max(whole)
    present = set(whole)
    upper_bound = min(int(highest), MAX_GAP_SEARCH)

    missing = [
        Decimal(candidate)
        for candidate in range(1, upper_bound)
        if Decimal(candidate) not in present and Decimal(candidate) not in suppressed
    ]
    return missing


def decide_attachment(
    match: DetectionMatch, existing: Story | None, threshold: float
) -> AttachDecision:
    """Decide whether a match attaches silently, needs curation, or is a new series."""
    if existing is None:
        return AttachDecision(action="new_series", story_id=None, confidence=match.confidence)
    if match.confidence >= threshold:
        return AttachDecision(
            action="auto_attach", story_id=existing.id, confidence=match.confidence
        )
    return AttachDecision(action="curate", story_id=existing.id, confidence=match.confidence)
