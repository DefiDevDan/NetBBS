"""
Display-width-aware text measurement (design doc, dogfood feature
request: international users reported "extremely poor handling of
anything beyond 7-bit ASCII"). Every width calculation elsewhere in
this codebase used plain `len()` (or stdlib `textwrap`, which is
`len()`-based internally) as a stand-in for terminal columns -- correct
for ASCII, wrong for any East Asian Wide/Fullwidth character (2
columns on a real terminal, not 1) or zero-width combining mark (0
columns, not 1). A board/channel name, post subject, or bio containing
CJK text therefore truncated at the wrong point, wrapped at the wrong
column, and (see `netbbs.net.char_input`/`netbbs.net.ansi_editor`, a
separate, later piece of this same fix) visibly desynced the cursor
from where the user was actually typing.

Built entirely on stdlib `unicodedata`'s `east_asian_width`/
`combining` -- no `wcwidth`-style third-party dependency needed, and
one less thing to track down through pkgsrc for a NetBSD target
(CLAUDE.md's own external-dependency preference). This is a real,
deliberate simplification, not full Unicode conformance: it does not
attempt UAX #11's "Ambiguous" category (treated as narrow, matching
most East Asian legacy terminal conventions) or emoji-specific width
tables (`east_asian_width` alone does not correctly widen most modern
emoji -- a real, accepted gap, not silently "handled"). CJK and
combining-mark text, the reported complaint, are both covered
correctly.
"""

from __future__ import annotations

import unicodedata

_ZERO_WIDTH_CATEGORIES = frozenset({"Cc", "Cf"})
_WIDE_EAST_ASIAN = frozenset({"W", "F"})


def char_width(ch: str) -> int:
    """Display columns occupied by one character: 0 for a combining
    mark or control/format character, 2 for an East Asian Wide/
    Fullwidth character, 1 otherwise. `ch` is assumed to already be a
    single character (or empty) -- callers iterating a `str` (which
    yields one Unicode code point per step) already satisfy this."""
    if not ch:
        return 0
    if unicodedata.combining(ch):
        return 0
    if unicodedata.category(ch) in _ZERO_WIDTH_CATEGORIES:
        return 0
    return 2 if unicodedata.east_asian_width(ch) in _WIDE_EAST_ASIAN else 1


def display_width(text: str) -> int:
    """Total display columns `text` occupies -- the width-aware
    replacement for `len(text)` everywhere `len` was standing in for
    "how many terminal columns does this take.\""""
    return sum(char_width(ch) for ch in text)


def cut_to_width(text: str, width: int) -> str:
    """The longest prefix of `text` whose `display_width` does not
    exceed `width` -- a character-by-character walk, not a slice
    (`text[:n]` assumes one column per character, the exact assumption
    this module exists to stop making). Public (unlike `truncate_to_
    width`'s ellipsis handling, which is specific to that one use)
    because `netbbs.rendering.reflow.colored_truncate` needs this same
    bare per-segment cut, with no ellipsis of its own -- the ellipsis
    there is a separate, final segment appended once, after every
    colored field's own budget is already spent."""
    total = 0
    cut = 0
    for ch in text:
        w = char_width(ch)
        if total + w > width:
            break
        total += w
        cut += 1
    return text[:cut]


def truncate_to_width(text: str, width: int, *, ellipsis: str = "...") -> str:
    """Truncate `text` to fit within `width` display columns, appending
    `ellipsis` if truncation actually occurred -- the width-aware
    counterpart to `netbbs.rendering.reflow.truncate`, same shape and
    edge-case handling (a `width` too narrow even for `ellipsis` alone
    truncates `ellipsis` itself), just measured in columns rather than
    characters."""
    if width < 1:
        raise ValueError(f"width must be >= 1, got {width}")
    if display_width(text) <= width:
        return text
    ellipsis_width = display_width(ellipsis)
    if width <= ellipsis_width:
        return cut_to_width(ellipsis, width)
    return cut_to_width(text, width - ellipsis_width) + ellipsis
