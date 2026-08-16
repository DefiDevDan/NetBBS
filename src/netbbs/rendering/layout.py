"""Responsive, transport-independent composition for ordinary NetBBS screens.

These helpers build styled strings only. They deliberately know nothing about
sessions, databases, or domain objects, keeping screen layout in the rendering
layer while callers retain ownership of behavior and authorization.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from netbbs.rendering.ansi import clear_screen, colored
from netbbs.rendering.reflow import colored_truncate
from netbbs.rendering.theme import (
    ERROR_COLOR,
    HEADER_COLOR,
    METADATA_COLOR,
    MUTED_COLOR,
    SUCCESS_COLOR,
    WARNING_COLOR,
)
from netbbs.rendering.width import cut_to_width, display_width, wrap_to_width

_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")
_WIDE_MENU_MIN_WIDTH = 72
# GitHub issue #160: a third column once there's genuinely room for one --
# beyond this, `menu_grid`'s own multi-line-per-entry layout (once
# descriptions are shown) gets cramped rather than more useful.
_THREE_COLUMN_MIN_WIDTH = 120
# Below this many rows, descriptions are always suppressed regardless of
# the caller's requested level -- genuinely short terminals are rare
# enough in real usage (issue #160 design discussion: no real client has
# defaulted below 80x24 in decades, and `netbbs.net.session.
# clamp_terminal_size` itself enforces no such floor) that a smooth
# multi-step degrade curve isn't worth designing for. One defensive
# floor, mirroring the fullscreen editors' own `_MIN_HEIGHT`-style clamp.
_MIN_HEIGHT_FOR_DESCRIPTIONS = 15
_DESCRIPTION_LEVELS = ("off", "brief", "detailed")
_COLUMN_GUTTER = 3


def visible_width(text: str) -> int:
    """Return the displayed width of text containing NetBBS SGR
    styling -- strips SGR escapes, then measures the remainder in
    display columns via `netbbs.rendering.width.display_width` (design
    doc, dogfood feature request), not `len()`: any East Asian Wide/
    Fullwidth character counts as 2 columns, not 1."""
    return display_width(_SGR_RE.sub("", text))


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
    lines = [colored(cut_to_width(title, width), fg_color=HEADER_COLOR, bold=True)]
    if detail:
        lines.append(colored(cut_to_width(detail, width), fg_color=METADATA_COLOR))
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
    clear: bool = False,
    unicode_style: bool = False,
) -> str:
    """Render a compact location/title block with a divider.

    `clear` (dogfood feature request -- `netbbs.net.redraw_preference`),
    if `True`, prepends `clear_screen()` -- home the cursor and blank
    the terminal -- so this screen replaces whatever was there instead
    of printing below it and scrolling. `False` by default, so every
    existing caller renders byte-for-byte as before; a caller opts in
    by passing the resolved `redraw_in_place_enabled(db, user)` value,
    the same "resolve once, pass down" shape `menu_grid`'s own
    `description_level` already uses -- this stays a pure rendering
    function with no `Session`/`Database` access of its own.

    `unicode_style` (dogfood feature request -- `netbbs.net.
    unicode_style_preference`) joins multi-level breadcrumbs with a "›"
    arrow instead of a plain "/", and colors every ancestor level
    `METADATA_COLOR` (muted) with only the final, current-location
    segment in `HEADER_COLOR` -- "NetBBS › System › Trust
    policy" instead of one uniformly-colored "NetBBS / System / Trust
    policy", directly answering a dogfood report that the old flat
    breadcrumb was hard to parse at a glance. `False` by default here
    too -- even though `unicode_style_preference` itself defaults to
    `True` (unlike `redraw_in_place`'s own off-by-default choice; see
    that preference module's own docstring for why), this local
    parameter stays conservative so every existing caller/test renders
    byte-for-byte as before until a caller explicitly threads the
    resolved `unicode_style_enabled(db, user)` value through, the exact
    same "safe local default, rich preference default" split `clear`
    already established -- flipping this one's own default to match the
    preference's would have silently changed output (and broken
    literal-text assertions) for every one of `screen_title`'s many
    existing callers/tests before any of them opted in on purpose.
    """
    if width < 1:
        raise ValueError("width must be >= 1")
    segments = (*breadcrumb, title) if breadcrumb else (title,)
    plain_location = " / ".join(segments)
    if unicode_style and len(segments) > 1:
        colored_segments: list[tuple[str, int | None]] = []
        for segment in segments[:-1]:
            colored_segments.append((segment, METADATA_COLOR))
            colored_segments.append((" › ", METADATA_COLOR))
        colored_segments.append((segments[-1], HEADER_COLOR))
        location_line = colored_truncate(colored_segments, width, ellipsis="")
    else:
        location_line = colored(cut_to_width(plain_location, width), fg_color=HEADER_COLOR, bold=True)
    lines = [location_line]
    if subtitle:
        lines.append(colored(cut_to_width(subtitle, width), fg_color=METADATA_COLOR))
    lines.append(colored("-" * min(width, max(12, display_width(plain_location))), fg_color=METADATA_COLOR))
    result = "\r\n".join(lines)
    return f"{clear_screen()}{result}" if clear else result


@dataclass(frozen=True)
class MenuEntry:
    """One menu option for `menu_grid` (design doc, dogfood feature
    request -- issue #160): `label` is already-styled text (normally
    `menu_key()` output, exactly what a plain `str` option has always
    been), `brief`/`detailed` are optional plain-text descriptions shown
    indented underneath when descriptions are enabled. `detailed` falls
    back to `brief` when not given separately -- authoring one string is
    enough to support both levels; a second, longer one is opt-in, not
    required. Sanitized like any other rendered text is expected to be
    by the caller authoring it (these are trusted, hardcoded UI copy,
    never untrusted/remote content), matching every other menu label in
    this codebase."""

    label: str
    brief: str | None = None
    detailed: str | None = None


_MenuOption = str | MenuEntry


def _as_entry(option: _MenuOption) -> MenuEntry:
    return option if isinstance(option, MenuEntry) else MenuEntry(label=option)


def _column_count(width: int, section_count: int) -> int:
    if width >= _THREE_COLUMN_MIN_WIDTH:
        target = 3
    elif width >= _WIDE_MENU_MIN_WIDTH:
        target = 2
    else:
        target = 1
    return max(1, min(target, section_count))


_DESCRIPTION_INDENT = "    "
# Dogfood-reported gap (issue #160's own rollout): a single flat,
# unheaded section -- most converted screens' actual shape -- always
# got exactly 1 column from `_column_count`, since column count there
# is section-count-based, not entry-count-based. Splitting a flat
# section's own entries into columns is only worth doing once there
# are meaningfully more entries than columns; below this ratio, a
# handful of options spread thin across several columns reads as a
# table, not a menu, and the plain vertical list is more scannable.
_MIN_ENTRIES_PER_COLUMN = 2


def _entry_block_lines(entry: MenuEntry, *, description_level: str, available_width: int) -> list[str]:
    """One entry's own line(s): just the label at `"off"`, plus one
    more line for its description text (`.detailed` at the `"detailed"`
    level, else `.brief`) when authored -- entries with none stay a
    single line even with descriptions on, matching every existing
    caller's expectation (a `MenuEntry` with only a `label` renders
    identically to a bare `str`)."""
    lines = [f"  {entry.label}"]
    if description_level == "off":
        return lines
    text = entry.detailed if description_level == "detailed" and entry.detailed else entry.brief
    if text:
        description_width = max(1, available_width - len(_DESCRIPTION_INDENT))
        # A hard cut, not a wrap: descriptions are meant to be one
        # short line to begin with (the whole point of this feature
        # over full online help), so losing an unlikely overflowing
        # tail on a narrow terminal is an acceptable, simple
        # degradation -- the same convention `screen_title`/
        # `empty_state` already use for their own text in this module.
        lines.append(colored(f"{_DESCRIPTION_INDENT}{cut_to_width(text, description_width)}", fg_color=MUTED_COLOR))
    return lines


def _section_lines(
    title: str, entries: Sequence[MenuEntry], *, description_level: str, available_width: int
) -> list[str]:
    # An empty title means "one flat group of options, no heading" -- a
    # legitimate caller shape (a single-purpose menu with nothing to
    # group), not just an unlabeled section; skip the line entirely
    # rather than rendering a blank one.
    lines = [colored(title.upper(), fg_color=METADATA_COLOR, bold=True)] if title else []
    for entry in entries:
        lines.extend(_entry_block_lines(entry, description_level=description_level, available_width=available_width))
    return lines


def _flat_entry_columns(
    entries: Sequence[MenuEntry], *, description_level: str, width: int, columns: int
) -> list[str]:
    """Column-major layout (fill top-to-bottom within a column before
    moving to the next -- the same reading order `ls`'s own column
    output uses) for one flat section's entries, since `_column_count`
    only ever gives a lone section 1 column otherwise. Entries can be 1
    or 2 lines each depending on whether that entry has description
    text; cells are padded to the tallest entry actually present so
    every column's rows line up, rather than assuming every entry is
    always 2 lines."""
    column_width = max(1, (width - _COLUMN_GUTTER * (columns - 1)) // columns)
    blocks = [
        _entry_block_lines(entry, description_level=description_level, available_width=column_width)
        for entry in entries
    ]
    entry_height = max((len(block) for block in blocks), default=1)
    padded = [block + [""] * (entry_height - len(block)) for block in blocks]
    rows_per_column = -(-len(padded) // columns)  # ceil division, no float rounding surprises
    lines = []
    for row in range(rows_per_column):
        for sub_row in range(entry_height):
            cells = []
            for column in range(columns):
                index = column * rows_per_column + row
                cells.append(padded[index][sub_row] if index < len(padded) else "")
            parts = []
            for i, cell in enumerate(cells):
                if i < len(cells) - 1:
                    padding = " " * max(1, column_width - visible_width(cell))
                    parts.append(cell + padding + " " * _COLUMN_GUTTER)
                else:
                    parts.append(cell)
            lines.append("".join(parts).rstrip())
    return lines


def menu_grid(
    sections: Sequence[tuple[str, Sequence[_MenuOption]]],
    *,
    width: int = 80,
    height: int | None = None,
    description_level: str = "off",
) -> str:
    """Render named menu groups in columns when space permits, one
    column per fixed width breakpoint (GitHub issue #160: 1 below 72,
    2 from 72-119, 3 from 120 up) rather than the fixed 2-column-max
    this used to be capped at.

    Options arrive already styled (normally through ``menu_key``) as
    plain strings, or as a `MenuEntry` when a short description should
    show underneath -- the two are freely mixable within one section.
    Narrow terminals receive the same groups in fewer columns without
    losing actions; every existing caller that never passes
    `description_level` (default `"off"`) or `height` renders byte-for-
    byte as before, since a `MenuEntry` with only a `label` and no
    description text behaves identically to a bare `str`.

    `description_level` is `"off"`/`"brief"`/`"detailed"` -- the
    caller's own resolved `netbbs.net.menu_description_preference`
    setting, not something this pure rendering function looks up
    itself. `height`, if given, forces descriptions off below
    `_MIN_HEIGHT_FOR_DESCRIPTIONS` regardless of the requested level --
    a real terminal that short is rare enough in practice that a
    smoother multi-step degrade isn't worth building (issue #160).

    Whenever the rendered result is actually narrower (fewer columns
    than the section count would otherwise use) or plainer (descriptions
    requested but suppressed by the height floor) than what was asked
    for, a standing muted note is appended explaining why -- mirroring
    this codebase's existing "AT LENGTH LIMIT"-style always-visible
    state indicators, not a one-off flash the caller could miss.
    """
    if width < 1:
        raise ValueError("width must be >= 1")
    if description_level not in _DESCRIPTION_LEVELS:
        raise ValueError(f"description_level must be one of {_DESCRIPTION_LEVELS}, got {description_level!r}")
    populated = [(title, [_as_entry(o) for o in options]) for title, options in sections if options]
    if not populated:
        return ""

    effective_level = description_level
    descriptions_collapsed = False
    if effective_level != "off" and height is not None and height < _MIN_HEIGHT_FOR_DESCRIPTIONS:
        effective_level = "off"
        descriptions_collapsed = True

    columns = _column_count(width, len(populated))
    # Only the single-column fallback counts as "collapsed" -- going
    # from 3 columns to 2 (or having only 2 sections to begin with) is
    # routine width adaptation most real terminals hit every day (the
    # classic 80-column default never reaches the 3-column breakpoint),
    # not a degraded state worth flagging. Squeezing multiple sections
    # down to one column, on the other hand, is a genuinely narrower
    # experience than this menu would otherwise give.
    columns_collapsed = columns == 1 and len(populated) > 1

    # A lone flat (unheaded) section -- most converted screens' actual
    # shape -- always got 1 column above, since `_column_count` counts
    # *sections*, not entries (dogfood-reported gap). Column-split its
    # own entries instead, using the same width breakpoints, once
    # there are meaningfully more entries than columns.
    if columns == 1 and len(populated) == 1 and populated[0][0] == "":
        flat_entries = populated[0][1]
        flat_columns = _column_count(width, len(flat_entries))
        if flat_columns > 1 and len(flat_entries) >= flat_columns * _MIN_ENTRIES_PER_COLUMN:
            result = "\r\n".join(
                _flat_entry_columns(
                    flat_entries, description_level=effective_level, width=width, columns=flat_columns
                )
            )
        else:
            result = "\r\n".join(
                _section_lines("", flat_entries, description_level=effective_level, available_width=width)
            )
    elif columns == 1:
        blocks = [
            "\r\n".join(_section_lines(title, entries, description_level=effective_level, available_width=width))
            for title, entries in populated
        ]
        result = "\r\n\r\n".join(blocks)
    else:
        column_width = max(1, (width - _COLUMN_GUTTER * (columns - 1)) // columns)
        blocks = []
        for offset in range(0, len(populated), columns):
            group = populated[offset : offset + columns]
            column_lines = [
                _section_lines(title, entries, description_level=effective_level, available_width=column_width)
                for title, entries in group
            ]
            row_count = max(len(lines) for lines in column_lines)
            rows = []
            for row in range(row_count):
                cells = [lines[row] if row < len(lines) else "" for lines in column_lines]
                parts = []
                for i, cell in enumerate(cells):
                    if i < len(cells) - 1:
                        padding = " " * max(1, column_width - visible_width(cell))
                        parts.append(cell + padding + " " * _COLUMN_GUTTER)
                    else:
                        parts.append(cell)
                rows.append("".join(parts).rstrip())
            blocks.append("\r\n".join(rows))
        result = "\r\n\r\n".join(blocks)

    notices = []
    if columns_collapsed:
        notices.append("Showing fewer columns than usual -- widen your terminal to see more at once.")
    if descriptions_collapsed:
        notices.append("Descriptions hidden -- terminal too short to show them.")
    if notices:
        # Wrapped, not just cut, to `width` -- this text is informational
        # prose, not a fixed-format label, and a hard cut on top of an
        # already-narrow terminal (the exact situation this notice fires
        # in) could chop it mid-sentence into something unreadable.
        notice_lines = [
            colored(wrapped, fg_color=MUTED_COLOR)
            for notice in notices
            for wrapped in wrap_to_width(notice, width)
        ]
        result = f"{result}\r\n\r\n" + "\r\n".join(notice_lines)
    return result
