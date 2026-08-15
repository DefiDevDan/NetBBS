"""
Text reflow: wraps long text to fit a target terminal width.

Uses Python's stdlib `textwrap` rather than a hand-rolled wrapper —
word-wrapping correctly (hyphenation edge cases, not breaking mid-word,
etc.) is a solved problem with no reason to reinvent it. This module
exists to apply stdlib `textwrap` with NetBBS-appropriate defaults:
specifically, preserving blank-line paragraph breaks, which a single
`textwrap.wrap()` call over multi-paragraph text does not do on its own
(it collapses all whitespace, including intentional blank lines,
uniformly).
"""

from __future__ import annotations

import textwrap
from typing import Sequence

from netbbs.rendering.ansi import colored
from netbbs.rendering.width import cut_to_width, display_width, truncate_to_width

DEFAULT_WIDTH = 80


def reflow(text: str, width: int = DEFAULT_WIDTH) -> str:
    """
    Reflow `text` to fit `width` columns, preserving paragraph breaks.

    Splits on blank lines first, wraps each paragraph independently, then
    rejoins with blank lines restored — so intentional paragraph
    structure survives, even though within a paragraph all whitespace
    (including single line breaks) is still collapsed and rewrapped, the
    normal `textwrap` behavior.
    """
    if width < 1:
        raise ValueError(f"width must be >= 1, got {width}")

    paragraphs = text.split("\n\n")
    wrapped_paragraphs = [
        "\n".join(textwrap.wrap(paragraph, width=width)) if paragraph.strip() else ""
        for paragraph in paragraphs
    ]
    return "\n\n".join(wrapped_paragraphs)


def truncate(text: str, width: int, *, ellipsis: str = "...") -> str:
    """
    Truncate `text` to fit within `width` display columns, appending
    `ellipsis` if truncation actually occurred.

    Unlike `reflow`, this always produces a single line, never wrapping
    — for contexts like a one-line list entry (e.g. `netbbs.net.picker`)
    where multi-line wrapping would break the list's visual structure.

    Delegates to `netbbs.rendering.width.truncate_to_width` (design
    doc, dogfood feature request) -- `width` is display columns, not
    characters, so any East Asian Wide/Fullwidth character counts as
    2, not 1.
    """
    return truncate_to_width(text, width, ellipsis=ellipsis)


def colored_truncate(
    segments: Sequence[tuple[str, int | None]], width: int, *, ellipsis: str = "..."
) -> str:
    """
    Like `truncate`, but for a line built from several differently-
    colored fields (`(text, fg_color)` pairs, `fg_color=None` for
    uncolored) -- coloring each segment only *after* the truncation
    budget is decided against the plain, unescaped text.

    Coloring first and truncating the ANSI-escaped result the way
    `truncate()` alone would is unsafe: SGR escape sequences count
    toward `truncate`'s character budget just like visible text, and a
    cut mid-sequence leaves an unterminated code that bleeds its color
    into everything printed afterward (see `colored()`'s own docstring
    on exactly that failure mode).

    `width` is display columns, not characters (design doc, dogfood
    feature request) -- each segment's own share of the budget is
    measured/cut with `netbbs.rendering.width`'s `display_width`/
    `cut_to_width`, the same primitives `truncate` itself now delegates
    to, so a multi-field row (e.g. `netbbs.net.picker`'s numbered list
    rows) truncates each colored field at a real column boundary
    instead of a character count.
    """
    if width < 1:
        raise ValueError(f"width must be >= 1, got {width}")

    plain = "".join(text for text, _ in segments)
    if display_width(plain) <= width:
        return "".join(colored(text, fg_color=color) for text, color in segments if text)
    ellipsis_width = display_width(ellipsis)
    if width <= ellipsis_width:
        return cut_to_width(ellipsis, width)

    budget = width - ellipsis_width
    rendered: list[str] = []
    for text, color in segments:
        if budget <= 0:
            break
        piece = cut_to_width(text, budget)
        if piece:
            rendered.append(colored(piece, fg_color=color))
        budget -= display_width(piece)
    rendered.append(ellipsis)
    return "".join(rendered)
