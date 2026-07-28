"""Convert Reddit-flavoured markdown into something Textual's renderer understands."""

from __future__ import annotations

import re

_SPOILER_RE = re.compile(r">!(.+?)!<", re.DOTALL)
_SUPERSCRIPT_PAREN_RE = re.compile(r"\^\(([^)]*)\)")
_SUPERSCRIPT_BARE_RE = re.compile(r"\^(\S+)")

SPOILER_MASK = "████████"


def to_display_markdown(text: str, *, reveal_spoilers: bool = False) -> str:
    """Mask spoilers unless revealed, and flatten Reddit's superscript syntax."""
    if reveal_spoilers:
        rendered = _SPOILER_RE.sub(lambda m: m.group(1), text)
    else:
        rendered = _SPOILER_RE.sub(SPOILER_MASK, text)

    rendered = _SUPERSCRIPT_PAREN_RE.sub(lambda m: m.group(1), rendered)
    return _SUPERSCRIPT_BARE_RE.sub(lambda m: m.group(1), rendered)
