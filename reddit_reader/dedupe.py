"""Collapse crossposted and manually mirrored copies of the same part."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from reddit_reader.models import PostMeta
from reddit_reader.titles import parse_title

DEFAULT_WINDOW_HOURS = 48


class DuplicateGroup(BaseModel):
    """One logical post plus any mirrored copies of it."""

    canonical: PostMeta
    alternates: list[PostMeta]


def _priority_rank(subreddit: str, priority: Sequence[str]) -> int:
    lowered = [s.lower() for s in priority]
    try:
        return lowered.index(subreddit.lower())
    except ValueError:
        return len(priority)


def collapse_duplicates(
    posts: Sequence[PostMeta],
    subreddit_priority: Sequence[str],
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> list[DuplicateGroup]:
    """Group mirrored copies of the same part, choosing one canonical post each."""
    by_id = {p.id: p for p in posts}

    # Trust explicit crosspost links first. `direct_parent` maps a post to the
    # post it was crossposted from (only when that parent is itself in this
    # batch). Resolve to the ultimate ancestor so chained crossposts (a
    # crosspost of a crosspost) still land in a single cluster regardless of
    # dict/list iteration order.
    direct_parent: dict[str, str] = {}
    for post in posts:
        if post.crosspost_parent and post.crosspost_parent in by_id:
            direct_parent[post.id] = post.crosspost_parent

    def _resolve_root(post_id: str) -> str:
        seen = {post_id}
        current = post_id
        while True:
            parent_id = direct_parent.get(current)
            if parent_id is None or parent_id in seen:
                return current
            seen.add(parent_id)
            current = parent_id

    root_of: dict[str, str] = {p.id: _resolve_root(p.id) for p in posts}

    # Only root posts (no known crosspost parent in this batch) participate in
    # the time/title/author heuristic. Explicit crosspost children are never
    # subject to the heuristic's time window — the explicit link is trusted
    # unconditionally, however far apart the posts were made.
    roots = [p for p in posts if root_of[p.id] == p.id]
    children = [p for p in posts if root_of[p.id] != p.id]

    buckets: dict[tuple[str, str, str], list[PostMeta]] = {}
    for post in roots:
        parsed = parse_title(post.title)
        key = (
            post.author.lower(),
            parsed.base_title,
            str(parsed.part_number) if parsed.part_number is not None else "",
        )
        buckets.setdefault(key, []).append(post)

    clusters: list[list[PostMeta]] = []
    for bucket in buckets.values():
        ordered = sorted(bucket, key=lambda p: p.created_utc)
        current: list[PostMeta] = []
        for post in ordered:
            if current:
                elapsed = (post.created_utc - current[0].created_utc).total_seconds() / 3600
                if elapsed > window_hours:
                    clusters.append(current)
                    current = []
            current.append(post)
        if current:
            clusters.append(current)

    # Attach every explicit crosspost child to its ultimate root's cluster,
    # regardless of chain depth or the order posts were processed in.
    cluster_by_post_id: dict[str, list[PostMeta]] = {}
    for cluster in clusters:
        for post in cluster:
            cluster_by_post_id[post.id] = cluster

    for child in children:
        root_id = root_of[child.id]
        target = cluster_by_post_id.get(root_id)
        if target is None:
            target = [by_id[root_id]]
            clusters.append(target)
            cluster_by_post_id[root_id] = target
        target.append(child)
        cluster_by_post_id[child.id] = target

    groups: list[DuplicateGroup] = []
    for cluster in clusters:
        ranked = sorted(
            cluster,
            key=lambda p: (_priority_rank(p.subreddit, subreddit_priority), p.created_utc),
        )
        groups.append(DuplicateGroup(canonical=ranked[0], alternates=ranked[1:]))
    return groups
