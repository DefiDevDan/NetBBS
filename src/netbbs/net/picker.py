"""
Generic paginated item picker: browse via [N]ext/[P]rev, [S]earch,
[G]oto #, [B]ack, or a 2-digit number to select an item on the current
page.

Built once, reused across boards, chat channels, and (once built) file
areas — the same underlying problem (choosing one of potentially many
items, some with long/arbitrary names, without forcing the user to type
the full name or scroll through an unbounded list) shows up in all
three, so the picker lives here rather than being reimplemented per
feature.

Design rationale (see design doc phasing sign-off notes): rejected both
pure tab-completion (inconsistent with single-key navigation elsewhere —
Thiesi's own observation — and doesn't solve "jump to item #769") and
pure alphabetical single-letter menu-style navigation (caps out at 26
items, and reserves letters that would collide with navigation commands
like this module's own N/P/S/G/B). Landed on: always-exactly-2-digit
page-relative selection (matches the single-keystroke immediacy of the
main menu) + a free-text search command (subsumes what tab completion
would have offered, without redraw/cycling complexity) + a free-text
"go to #" command referencing each item's own permanent stable ID (the
one thing neither of the two original proposals solved on its own).

`goto`'s number is deliberately *not* a position in the current list —
it's whatever permanent identifier the caller supplies (`stable_id_of`,
typically a database ID). This was a real design correction: an earlier
version derived the number from list position, which broke the moment
sort order became configurable (alphabetical/most-recent-activity
reorder existing items, unlike creation-order's append-only stability) —
the same number would then mean a different item depending on current
sort order, defeating the entire point of a memorable reference. Display
order (whatever the caller's list is sorted by) and item identity
(`stable_id_of`) are now fully independent: paging through an
alphabetically-sorted list might show `(#7)`, `(#23)`, `(#4)` in that
order — visually non-sequential, but each number is permanent regardless
of how the list is currently sorted or filtered.
"""

from __future__ import annotations

import math
from typing import Awaitable, Callable, Sequence, TypeVar

from netbbs.net.char_input import CANCEL_KEY, REDRAW_KEY, REFRESH_KEY, Completer, reject_unhandled_key
from netbbs.net.session import Session
from netbbs.rendering import (
    ACCENT_COLOR,
    ERROR_COLOR,
    MENU_KEY_COLOR,
    MUTED_COLOR,
    MenuEntry,
    action_bar,
    colored,
    colored_truncate,
    cut_to_width,
    menu_grid,
    menu_key,
    reject_keystroke,
    sanitize_text,
    screen_title,
    visible_width,
)

T = TypeVar("T")

# Lines reserved on screen for the title, blank spacing, and the
# footer/prompt — subtracted from the negotiated terminal height (see
# netbbs.net.telnet's NAWS handling) to compute how many items actually
# fit on one page without scrolling off screen.
_RESERVED_LINES = 6

# Selection numbers are always exactly two digits (01-99), zero-padded,
# so a page can never need more than this many items — keeps "always
# exactly 2 keystrokes for a numbered choice" unambiguous, with no
# timeout-based guessing about whether a second digit is coming (the
# same reasoning that led to bounded timeouts elsewhere in
# netbbs.net.telnet, just avoided entirely here by fixing the width).
_MAX_PAGE_SIZE = 99


async def pick_item(
    session: Session,
    items: Sequence[T],
    *,
    name_of: Callable[[T], str],
    stable_id_of: Callable[[T], int],
    description_of: Callable[[T], str | None] = lambda item: None,
    title: str,
    empty_message: str,
    refresh: Callable[[], Awaitable[Sequence[T]]] | None = None,
    on_sort: Callable[[], Awaitable[Sequence[T] | None]] | None = None,
    sort_label: Callable[[], str] | None = None,
    description_level: str = "off",
    redraw_in_place: bool = False,
) -> T | None:
    """
    Let the user browse/search/jump through `items` and pick one, or
    return `None` if they quit without selecting.

    `items` should already be filtered to whatever the user is actually
    allowed to see/select (e.g. by level — see design doc §13) — this
    function has no concept of permissions, purely presentation and
    selection. `name_of` is used both for the per-line display and as
    what `search` matches against; `description_of` is optional
    secondary text shown alongside the name but never searched — search
    matching only the name is more predictable than also matching
    free-text descriptions. `stable_id_of` supplies each item's
    permanent identifier (typically a database ID) — see the module
    docstring for why this is deliberately independent of the item's
    position in `items`.

    `name_of`/`description_of` results are sanitized (`netbbs.rendering.
    sanitize_text`, design doc) immediately before display —
    every caller of this shared picker (boards, chat channels, file
    areas) gets that protection automatically rather than needing to
    remember it individually. Search matching (`query.lower() in
    name_of(item).lower()`) deliberately uses the *raw*, unsanitized
    name — matching is a text-comparison operation, not something
    written to the terminal, so there's nothing to protect there.

    The page/nav block, and the `"Choice: "` prompt itself, are drawn
    once on entry and again only after an actual state change (paging
    that moves, a search that changes the working set, a sub-prompt's
    specific answer) — not on every keystroke. An action that changes
    nothing (paging past the last/first page, an unrecognized key, an
    out-of-range 2-digit selection) sounds a bell and does *nothing*
    else (design doc) — no redraw, no reprinted prompt, no
    error message; the screen is left exactly as it was, and the next
    keystroke's own echo lands wherever the cursor already sits. A
    deliberately typed sub-prompt that fails on its own terms (`search`
    with no matches, `goto` with an unparseable or out-of-range number)
    is different in kind, not a stray keystroke: it still gets its own
    specific text response *and* a freshly reprinted prompt afterward,
    since something was actually communicated that the user needs a
    clean line to respond to.

    Issue #102: Ctrl-L always redraws the current page in place (no
    state change, just a fresh copy of what's already on screen -- the
    same "not a real action" bucket paging past the last page falls
    into, just without the bell, since nothing here was actually
    rejected). Ctrl-R additionally re-fetches via `refresh` if the
    caller supplied one -- resetting to the freshly fetched list and
    clearing any active search filter, since "refresh" means "show me
    current reality," not "reapply my old filter to it" -- and falls
    through to an ordinary rejected-keystroke bell if the caller didn't
    (most existing callers), the same as any other key this function
    doesn't recognize.

    Issue #112: an empty list remains interactive when `refresh` exists.
    Dynamic screens such as Who's Online can therefore start empty and
    populate later via Ctrl-R instead of immediately returning to their
    caller. Non-refreshable empty pickers keep the historical immediate-
    return behavior. Ctrl-L/Ctrl-R are deliberately unechoed by
    `read_key`, so rejection paths must not erase a character that was
    never written to the terminal.

    `on_sort` (design doc, dogfood feature request), if given, offers an
    `[O]rder` command -- this function has no concept of what sort
    modes exist or how to persist a choice (that's
    `netbbs.net.sort_ui.prompt_sort_change`, resource-kind-agnostic in
    the same way this function itself is), so `on_sort` fully owns its
    own sub-prompt and returns the freshly re-sorted *entire* item
    sequence, or `None` if the user backed out without changing
    anything. A non-`None` result replaces both `items` and
    `working_set` (so a later `search`/`goto` reflects the new order
    too) and resets to page 1. `sort_label`, if given alongside, is
    read fresh on every render and appended to the nav trailer (e.g.
    "Sort: Activity") so the current mode is never a mystery -- exactly
    the ambiguity the dogfood report behind this feature complained
    about.

    `description_level` (issue #160's own rollout to this screen) is
    the caller's already-resolved `menu_description_level` preference
    ("off"/"brief"/"detailed") -- fetched once by the caller, same
    caching rule as `netbbs.net.resource_editor.edit_resource_draft`'s
    own `description_level` parameter. The nav row (Next/Prev/Search/
    Goto/Order/Back) renders through `menu_grid`; the per-item list
    itself is unaffected -- items already show their own description
    via `description_of`. Unlike `edit_resource_draft`'s single fixed-
    size menu row, this nav block's *rendered height* now varies with
    `description_level` (1 line/entry when off, 2 when brief/detailed)
    and directly affects how many items fit on a page -- `_page_size`
    accounts for the nav block's actual line count instead of assuming
    the old constant 1-line nav that `_RESERVED_LINES` was calibrated
    against, so paging math and the real on-screen nav never disagree.

    `redraw_in_place` (dogfood feature request, `netbbs.net.
    redraw_preference`) clears the terminal before every redraw of this
    screen instead of printing a fresh block below the last one -- same
    "caller resolves the preference once, this function just trusts it"
    shape as `description_level`. `False` by default, so an existing
    caller that doesn't pass it renders exactly as before.
    """
    if not items and refresh is None:
        await session.write_line(colored(f"\r\n{empty_message}", fg_color=MUTED_COLOR))
        return None

    working_set: Sequence[T] = items
    page_index = 0

    def _total_pages() -> int:
        return max(1, math.ceil(len(working_set) / _page_size(session, on_sort, description_level)))

    async def _render() -> Sequence[T]:
        nonlocal page_index
        if not working_set:
            page_index = 0
            await session.write_line(colored(f"\r\n{empty_message}", fg_color=MUTED_COLOR))
            trailer = f"{menu_key('B', 'ack')} — Ctrl-L: redraw"
            if refresh is not None:
                trailer += ", Ctrl-R: refresh"
            await session.write_line(f"\r\n{trailer}")
            await session.write("Choice: ")
            return []

        page_size = _page_size(session, on_sort, description_level)
        total_pages = _total_pages()
        page_index = max(0, min(page_index, total_pages - 1))
        start = page_index * page_size
        page_items = working_set[start : start + page_size]

        await session.write_line(
            "\r\n" + screen_title(
                title,
                subtitle=f"page {page_index + 1}/{total_pages}, {len(working_set)} total",
                width=session.terminal_width,
                clear=redraw_in_place,
            )
        )
        for position, item in enumerate(page_items, start=1):
            # Two numbers shown per line, deliberately: the 2-digit
            # prefix is what to press to select *this item, right now,
            # on this page*; the "(#N)" is its permanent stable_id_of
            # reference for `goto` — usable later, from anywhere,
            # regardless of paging, search state, or sort order. Without
            # showing this second number somewhere, `goto` would be
            # nearly undiscoverable — nothing else on screen reveals what
            # number to type for it.
            #
            # Colored per field (issue #104) via colored_truncate, not
            # plain truncate() on an already-colored string: the
            # selector in MENU_KEY_COLOR (it's literally the keystroke
            # to press), the permanent reference in MUTED_COLOR, the
            # name in ACCENT_COLOR (this module's existing convention for
            # navigable item names), and any description muted again.
            description = description_of(item)
            segments: list[tuple[str, int | None]] = [
                (f"  {position:02d}. ", MENU_KEY_COLOR),
                (f"(#{stable_id_of(item)}) ", MUTED_COLOR),
                (sanitize_text(name_of(item)), ACCENT_COLOR),
            ]
            if description:
                segments.append((f" - {sanitize_text(description)}", MUTED_COLOR))
            await session.write_line(colored_truncate(segments, session.terminal_width))

        nav = _render_nav(session, on_sort, description_level)
        # Folded into this same trailing line, not a line of its own
        # (issue #102's own "document it somewhere discoverable"
        # criterion) -- a permanent extra row here would shift every
        # picker's page_size by one and ripple through every existing
        # page-boundary test/assumption for a purely cosmetic addition.
        #
        # `sort_label` goes first, not last: it's this screen's own
        # standing "current state" indicator (design doc -- the dogfood
        # complaint this was built for was specifically about the
        # active sort mode being a mystery), not a one-time hint the
        # way the rest of this trailer is -- it must survive truncation
        # ahead of the boilerplate instructions below it.
        trailer = ""
        if sort_label is not None:
            trailer = f"Sort: {sanitize_text(sort_label())}"
        boilerplate = "or type a 2-digit number to select; Ctrl-L: redraw"
        if refresh is not None:
            boilerplate += ", Ctrl-R: refresh"
        trailer = f"{trailer}; {boilerplate}" if trailer else boilerplate
        # Dogfood-reported regression: with sort mode (and/or refresh)
        # active, nav + separator + trailer could run past the real
        # terminal width -- unlike every other line on this screen
        # (each already deterministically cut via colored_truncate/
        # menu_grid), this one wasn't clamped at all, so whichever
        # client rendered it wrapped wherever it happened to land,
        # sometimes mid-word. Cut the trailer to whatever room remains,
        # mirroring `menu_grid`'s own established "hard cut, not a
        # client wrap" convention for this kind of trailing text.
        separator = " — "
        last_nav_line = nav.rsplit("\r\n", 1)[-1]
        if description_level == "off":
            # The compact `action_bar` form's last (often only) line is
            # short, so folding the trailer onto it is cheap and keeps
            # this screen's height completely unchanged from before
            # descriptions existed at all.
            available_for_trailer = session.terminal_width - visible_width(last_nav_line) - visible_width(separator)
            trailer = cut_to_width(trailer, max(0, available_for_trailer))
            await session.write_line(f"\r\n{nav}{separator}{trailer}" if trailer else f"\r\n{nav}")
        else:
            # `menu_grid`'s own last line, unlike `action_bar`'s, is
            # often padded out to nearly the full width already (issue
            # #160's flat-section column-splitting fills every row to
            # its column width) -- folding the trailer onto it the same
            # way left almost no room and cut "Sort: X" down to nothing.
            # Its own line instead; `_page_size` already measures
            # whatever this function actually renders, so the one extra
            # line is accounted for automatically, not a hardcoded
            # assumption to keep in sync.
            trailer = cut_to_width(trailer, max(0, session.terminal_width))
            await session.write_line(f"\r\n{nav}")
            if trailer:
                await session.write_line(trailer)
        await session.write("Choice: ")
        return page_items

    page_items = await _render()
    while True:
        key = await session.read_key()
        key_lower = key.lower()

        if key == REDRAW_KEY:
            page_items = await _render()
            continue

        if key == REFRESH_KEY:
            if refresh is None:
                await session.write(reject_unhandled_key(key))
                continue
            items = await refresh()
            working_set = items
            page_index = 0
            page_items = await _render()
            continue

        if key_lower == "b" or key == CANCEL_KEY:
            # Issue #157: Ctrl-C as an incremental alias for [B]ack --
            # this screen's own "leave without selecting" action.
            await session.write_line("")
            return None

        if key_lower == "n":
            if page_index < _total_pages() - 1:
                await session.write_line("")
                page_index += 1
                page_items = await _render()
            else:
                await session.write(reject_keystroke())
            continue

        if key_lower == "p":
            if page_index > 0:
                await session.write_line("")
                page_index -= 1
                page_items = await _render()
            else:
                await session.write(reject_keystroke())
            continue

        if key_lower == "s":
            if not items:
                # Dogfood report, issue #155: reachable at all only
                # because `refresh` (Who's Online's own use) keeps this
                # loop interactive instead of the plain empty_message
                # early-return above -- `_render`'s own empty-state
                # trailer already omits [S]earch (there's nothing to
                # search for), but without this the key still worked
                # anyway, silently available despite not being
                # advertised. Gated on `items` (the full unfiltered
                # set search always searches, not the possibly already-
                # narrowed `working_set`) -- the same set whose
                # emptiness the trailer's own message is about.
                await session.write(reject_keystroke())
                continue
            await session.write_line("")
            await session.write("Search: ")
            search_completer = _search_completer([name_of(item) for item in working_set])
            query = (await session.read_line(completer=search_completer)).strip()
            if not query:
                # Empty search clears back to the full, unfiltered list
                # — doubles as "cancel" when nothing was filtered yet
                # (a no-op in that case) and "clear filter" when a
                # previous search narrowed working_set, without needing
                # two separate commands for what's really one action.
                working_set = items
                page_index = 0
                page_items = await _render()
                continue
            matches = [item for item in items if query.lower() in name_of(item).lower()]
            if not matches:
                await session.write_line(colored("No matches.", fg_color=ERROR_COLOR))
                await session.write("Choice: ")
                continue
            if len(matches) == 1:
                return matches[0]
            working_set = matches
            page_index = 0
            page_items = await _render()
            continue

        if key_lower == "o":
            if on_sort is None:
                await session.write(reject_unhandled_key(key))
                continue
            new_items = await on_sort()
            if new_items is not None:
                items = new_items
                working_set = new_items
                page_index = 0
            page_items = await _render()
            continue

        if key_lower == "g":
            if not items:
                # Same reasoning as [S]earch's own guard above -- issue
                # #155.
                await session.write(reject_keystroke())
                continue
            await session.write_line("")
            await session.write("Go to #: ")
            raw = (await session.read_line()).strip()
            try:
                target_id = int(raw)
            except ValueError:
                await session.write_line(colored("Not a number.", fg_color=ERROR_COLOR))
                await session.write("Choice: ")
                continue
            # Always searches `items` (the full original list) by
            # stable_id_of, never `working_set` — a goto number means the
            # same item regardless of any active search filter or sort
            # order, matching the "(#N)" shown next to every displayed
            # item. A linear scan, not a lookup table, since the caller's
            # list is expected to be reasonably sized (boards/channels/
            # areas on one node, not the whole Link) — acceptable here,
            # revisit if that assumption stops holding.
            for item in items:
                if stable_id_of(item) == target_id:
                    return item
            await session.write_line(colored("Out of range.", fg_color=ERROR_COLOR))
            await session.write("Choice: ")
            continue

        if key.isdigit():
            second = await session.read_key()
            if not second.isdigit():
                # The first digit is always echoed. Ctrl-L/Ctrl-R are
                # deliberately returned unechoed, however, so erase only
                # the one character which actually reached the terminal in
                # that case; ordinary invalid second keys still contributed
                # their own echo and therefore erase both characters.
                erase_count = 1 if second in (REDRAW_KEY, REFRESH_KEY) else 2
                await session.write(reject_keystroke(erase_count))
                continue
            number = int(key + second)
            if 1 <= number <= len(page_items):
                # A valid selection is a real state change -- same "end
                # the echoed input with its own newline before whatever
                # comes next" discipline every other branch here already
                # follows (`b`/`n`/`p` above). Missing here was a real
                # dogfood-reported bug: without it, a caller's own very
                # next prompt (e.g. "Disconnect 'x'? [y/N]: ") landed
                # directly after the echoed "02" with no separation at
                # all, on the same line.
                await session.write_line("")
                return page_items[number - 1]
            await session.write(reject_keystroke(2))
            continue

        await session.write(reject_keystroke())


def _search_completer(candidates: Sequence[str]) -> Completer:
    """
    Tab completion for `pick_item`'s `"Search: "` prompt — purely
    additive: the substring-match-on-Enter
    search behavior above is completely unchanged, this only helps when
    what's typed so far happens to already be a real *prefix* of some
    candidate's name.

    Deliberately returns no candidates once the query contains a space:
    `netbbs.net.char_input`'s generic Tab logic only ever replaces the
    *last* whitespace-delimited word, which is exactly right for
    `chat_flow`'s single-word command/username completions but would
    corrupt a multi-word candidate name (e.g. a category like "Vintage
    Computing") if allowed to complete past an already-typed internal
    space. Safe scope: complete the *first* word of a name, not every
    word within it — redefining the picker's own search matching to
    prefix-only (which could support the general case properly) is a
    separate, larger question that would reverse the existing
    substring-match search behavior, out of scope here.
    """

    def completer(text: str) -> list[str]:
        if " " in text:
            return []
        lower = text.lower()
        return sorted(name for name in candidates if name.lower().startswith(lower))

    return completer


# `menu_description_level`'s own real default is "brief", not "off" --
# descriptions are on for every caller who has never touched the
# setting (see that module's docstring). `menu_grid` renders one line
# per nav entry even once a short terminal collapses its *description
# text*, so a caller sitting at the real default on a modest terminal
# would otherwise see the item list itself shrink to almost nothing
# just to make room for nav blurbs -- at 20 rows, page size drops from
# 18 items (the old always-compact nav) to 5; below 15 rows, to exactly
# 1. Below this floor, the nav falls back to the compact single-line
# `action_bar` regardless of preference: descriptions are a nice-to-
# have, being able to actually browse the list is the point of this
# screen.
_MIN_PAGE_SIZE_FOR_DESCRIPTIVE_NAV = 5


def _nav_entries(on_sort: Callable | None) -> list[MenuEntry]:
    entries = [
        MenuEntry(label=menu_key("N", "ext"), brief="Next page"),
        MenuEntry(label=menu_key("P", "rev"), brief="Previous page"),
        MenuEntry(label=menu_key("S", "earch"), brief="Search by name"),
        MenuEntry(label=menu_key("G", "oto #"), brief="Jump to an item's #"),
    ]
    if on_sort is not None:
        entries.append(MenuEntry(label=menu_key("O", "rder"), brief="Change sort order"))
    entries.append(MenuEntry(label=menu_key("B", "ack"), brief="Return without picking"))
    return entries


def _render_nav(session: Session, on_sort: Callable | None, description_level: str) -> str:
    entries = _nav_entries(on_sort)
    if description_level != "off":
        descriptive = menu_grid(
            [("", entries)], width=session.terminal_width, height=session.terminal_height,
            description_level=description_level,
        )
        descriptive_lines = descriptive.count("\r\n") + 1
        available = session.terminal_height - (_RESERVED_LINES - 1 + descriptive_lines)
        if max(1, min(_MAX_PAGE_SIZE, available)) >= _MIN_PAGE_SIZE_FOR_DESCRIPTIVE_NAV:
            return descriptive
    # `menu_grid` always renders one entry per line, even with
    # descriptions off -- unlike `action_bar`'s packed single-line row,
    # that's not a byte-for-byte-compatible substitute at this level.
    # Reached either because the caller's preference is "off", or
    # because the descriptive form above didn't clear the page-size
    # floor.
    return action_bar([e.label for e in entries], width=session.terminal_width)


def _page_size(session: Session, on_sort: Callable | None, description_level: str) -> int:
    # `_RESERVED_LINES` was calibrated against the nav row always being
    # exactly 1 line -- still true for `description_level="off"`
    # (`action_bar`), so the reserved budget only needs to grow past
    # that constant once "brief"/"detailed" switches the nav row to
    # `menu_grid`'s taller, one-entry-per-line rendering.
    nav_lines = _render_nav(session, on_sort, description_level).count("\r\n") + 1
    available = session.terminal_height - (_RESERVED_LINES - 1 + nav_lines)
    return max(1, min(_MAX_PAGE_SIZE, available))
