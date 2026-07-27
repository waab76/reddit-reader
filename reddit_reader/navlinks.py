"""Parse First/Prev/Next navigation links out of a cached post body."""

from __future__ import annotations

import re

from pydantic import BaseModel

_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_COMMENTS_URL_RE = re.compile(r"reddit\.com/r/[^/]+/comments/([a-z0-9]+)", re.IGNORECASE)
_SHORT_URL_RE = re.compile(r"redd\.it/([a-z0-9]+)", re.IGNORECASE)

_FIRST_LABELS = ("first",)
_PREV_LABELS = ("prev", "previous")
_NEXT_LABELS = ("next",)


class NavLinks(BaseModel):
    """Post ids referenced by a body's navigation links."""

    first: str | None = None
    previous: str | None = None
    next: str | None = None


def extract_post_id(url: str) -> str | None:
    """Return the Reddit post id in `url`, or None if it isn't a Reddit post link."""
    match = _COMMENTS_URL_RE.search(url) or _SHORT_URL_RE.search(url)
    return match.group(1) if match else None


def parse_nav_links(selftext: str) -> NavLinks:
    """Find First/Prev/Next navigation links and resolve them to post ids."""
    links = NavLinks()
    for label, url in _MARKDOWN_LINK_RE.findall(selftext):
        post_id = extract_post_id(url)
        if post_id is None:
            continue
        normalized = label.strip().lower().strip("[]<> ")
        if links.first is None and any(w == normalized for w in _FIRST_LABELS):
            links.first = post_id
        elif links.previous is None and any(w == normalized for w in _PREV_LABELS):
            links.previous = post_id
        elif links.next is None and any(w == normalized for w in _NEXT_LABELS):
            links.next = post_id
    return links
