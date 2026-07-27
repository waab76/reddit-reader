"""Remove recurring boilerplate from post bodies at render time.

Nothing here mutates stored text. `PostBody.selftext` always holds the raw post,
so patterns can improve and decisions can be revoked without re-fetching.
"""

from __future__ import annotations

import re

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
    re.IGNORECASE | re.MULTILINE,
)

_BLANK_RUN_RE = re.compile(r"\n{3,}")


def strip_patterns(selftext: str) -> str:
    """Remove nav blocks, support plugs, and generic sign-offs."""
    text = _NAV_LINE_RE.sub("", selftext)
    text = _PLUG_LINE_RE.sub("", text)
    text = _SIGNOFF_RE.sub("", text)
    return _BLANK_RUN_RE.sub("\n\n", text).strip()
