"""Responsive, transport-independent composition for ordinary NetBBS screens.

These helpers build styled strings only. They deliberately know nothing about
sessions, databases, or domain objects, keeping screen layout in the rendering
layer while callers retain ownership of behavior and authorization.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from netbbs.rendering.ansi import colored
from netbbs.rendering.theme import (
    ERROR_COLOR,
    HEADER_COLOR,
    METADATA_COLOR,
    SUCCESS_COLOR,
    WARNING_COLOR,
)

_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")
_WIDE_MENU_MIN_WIDTH = 72


def visible_width(text: str) -> int:
    """Return the displayed width of text containing NetBBS SGR styling."""
    return len(_SGR_RE.sub("", text))


def badge(text: str, *, tone: str = "neutral") -> str:
    """Render a compact semantic label without assuming Unicode support."""
    colors = {
        "neutral": METADATA_COLOR,
        "success": SUCCESS_COLOR,
        "warning": WARNING_COLOR,
        "error": ERROR_COLOR,
    }
    try:
        color = colors[tone]
    except KeyError as exc:
        raise ValueError(f"unknown badge tone: {tone}") from exc
    return colored(f"[{text}]", fg_color=color, bold=True)


def empty_state(
    title: str,
    *,
    detail: str | None = None,
    width: int = 80,
) -> str:
    """Render an intentional, compact state for a screen with no content."""
    if width < 1:
        raise ValueError("width must be >= 1")
    lines = [colored(title[:width], fg_color=HEADER_COLOR, bold=True)]
    if detail:
        lines.append(colored(detail[:width], fg_color=METADATA_COLOR))
    return "\r\n".join(lines)


def action_bar(options: Sequence[str], *, width: int = 80) -> str:
    """Wrap already-styled actions as whole units at the terminal edge."""
    if width < 1:
        raise ValueError("width must be >= 1")
    lines: list[str] = []
    current: list[str] = []
    current_width = 0
    for option in options:
        option_width = visible_width(option)
        separator_width = 2 if current else 0
        if current and current_width + separator_width + option_width > width:
            lines.append("  ".join(current))
            current = []
            current_width = 0
            separator_width = 0
        current.append(option)
        current_width += separator_width + option_width
    if current:
        lines.append("  ".join(current))
    return "\r\n".join(lines)


def screen_title(
    title: str,
    *,
    breadcrumb: Sequence[str] = ("NetBBS",),
    subtitle: str | None = None,
    width: int = 80,
) -> str:
    """Render a compact location/title block with an ASCII-safe divider."""
    if width < 1:
        raise ValueError("width must be >= 1")
    location = " / ".join((*breadcrumb, title)) if breadcrumb else title
    lines = [colored(location[:width], fg_color=HEADER_COLOR, bold=True)]
    if subtitle:
        lines.append(colored(subtitle[:width], fg_color=METADATA_COLOR))
    lines.append(colored("-" * min(width, max(12, len(location))), fg_color=METADATA_COLOR))
    return "\r\n".join(lines)


def menu_grid(
    sections: Sequence[tuple[str, Sequence[str]]], *, width: int = 80
) -> str:
    """Render named menu groups in two columns when space permits.

    Options arrive already styled (normally through ``menu_key``). Narrow
    terminals receive the same groups in one column without losing actions.
    """
    if width < 1:
        raise ValueError("width must be >= 1")
    populated = [(title, list(options)) for title, options in sections if options]
    if not populated:
        return ""

    if width < _WIDE_MENU_MIN_WIDTH or len(populated) == 1:
        blocks = []
        for title, options in populated:
            heading = colored(title.upper(), fg_color=METADATA_COLOR, bold=True)
            blocks.append("\r\n".join([heading, *(f"  {option}" for option in options)]))
        return "\r\n\r\n".join(blocks)

    column_width = max(1, (width - 3) // 2)
    blocks = []
    for offset in range(0, len(populated), 2):
        left = populated[offset]
        right = populated[offset + 1] if offset + 1 < len(populated) else ("", [])
        row_count = max(len(left[1]), len(right[1])) + 1
        rows = []
        for row in range(row_count):
            left_text = (
                colored(left[0].upper(), fg_color=METADATA_COLOR, bold=True)
                if row == 0
                else f"  {left[1][row - 1]}" if row - 1 < len(left[1]) else ""
            )
            right_text = (
                colored(right[0].upper(), fg_color=METADATA_COLOR, bold=True)
                if row == 0 and right[0]
                else f"  {right[1][row - 1]}" if row and row - 1 < len(right[1]) else ""
            )
            padding = " " * max(1, column_width - visible_width(left_text))
            rows.append(f"{left_text}{padding}   {right_text}".rstrip())
        blocks.append("\r\n".join(rows))
    return "\r\n\r\n".join(blocks)
