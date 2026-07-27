"""Group posts into candidate series and score how confident the grouping is."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from difflib import SequenceMatcher
from itertools import pairwise

from reddit_reader.dedupe import collapse_duplicates
from reddit_reader.models import DetectionMatch, PostMeta
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
    posts: Sequence[PostMeta], subreddit_priority: Sequence[str]
) -> list[DetectionMatch]:
    """Collapse duplicates, then group the survivors into candidate series."""
    groups = collapse_duplicates(posts, subreddit_priority)
    canonical = [group.canonical for group in groups]

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
        matches.append(
            DetectionMatch(
                base_title=base_title,
                author=group_posts_list[0].author,
                volume=volume,
                post_ids=[p.id for p in group_posts_list],
                confidence=confidence,
                reasons=reasons,
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
            )
        )

    return matches
