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
