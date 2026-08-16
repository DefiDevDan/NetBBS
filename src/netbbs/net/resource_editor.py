"""
Shared draft-based field editor (design doc, dogfood feature request):
one screen serves both creating a new resource and editing an existing
one -- "create" is just "edit a fresh draft of defaults, then [S]ave
inserts instead of updates." Fixes two related dogfood complaints in
one shape: editing an existing board/channel/file-area/Community no
longer walks the same linear step-by-step wizard creating one does
(every field addressable independently, in any order, skipping
whatever doesn't need changing), and there is no way to be left with a
half-created resource on cancel -- nothing is written to the database
until an explicit [S]ave; [B]ack simply discards the draft.

Generalizes `netbbs.net.login_flow`'s own profile screen
(`_render_profile`/`_edit_profile`) shape -- show every field's
current value, one hotkey per field, redraw after each edit -- into a
reusable driver (`edit_resource_draft`) parameterized by a list of
`FieldSpec` entries, instead of each resource hand-writing its own
sequential prompt chain. `netbbs.net.admin_flow` supplies each
resource kind's own field list, built from a mix of this module's
generic `text_field`/`bool_field` factories and thin adapters over its
own existing per-type prompt helpers (`_prompt_optional_int`,
`_prompt_min_age`, `_prompt_name_requirement`, `_pick_optional_community`,
`_pick_optional_category`) -- this module has no knowledge of any one
resource kind's own fields, domain functions, or error types.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from netbbs.net.char_input import CANCEL_KEY, HELP_KEY, reject_unhandled_key
from netbbs.net.help_overlay import show_help
from netbbs.net.session import Session
from netbbs.rendering import HEADER_COLOR, MUTED_COLOR, action_bar, colored, sanitize_text, screen_title
from netbbs.storage.execution import DatabaseLane

# A draft is a plain, freely-mutable dict of field values -- for
# "create," seeded with the resource's own sensible defaults up front
# (identical shape to an "edit" draft seeded from an existing
# resource's current values); this module never distinguishes the two
# cases itself, only the caller's own `save` closure does (calling
# create_* vs. update_*).
Draft = dict[str, Any]

# One field's own sub-interaction: reads whatever it needs (may span
# several prompts, e.g. a picker), and mutates `draft[key]` in place.
# Leaving the draft unchanged -- an invalid entry, an explicit "keep
# current" -- is always a safe, silent outcome here: unlike this
# field's `edit_resource_draft` call site, a mistake on one field never
# discards any other field already entered into the same draft.
FieldPrompt = Callable[[Session, DatabaseLane, Draft], Awaitable[None]]


@dataclass(frozen=True)
class FieldSpec:
    """One editable field on a draft-based resource editor screen.

    `menu_text` is a pre-rendered `netbbs.rendering.menu_key(...)`
    string (e.g. `menu_key("N", "ame")`) -- built by the caller, not
    this module, the same way every other menu in this codebase
    assembles its own options list; keeps this module free of any
    opinion on hotkey/prefix choices. `render(draft)` is called fresh
    on every redraw and must be a pure, cheap read of the draft, no I/O
    -- the "current value" line shown above the menu.

    `help` (dogfood feature request, issue #150), if given, is a short
    plain-text explanation shown when the caller presses Ctrl-H --
    optional and `None` by default, since authoring it for every field
    on day one isn't required (issue's own scope note); a field with no
    `help` is simply omitted from that screen.
    """

    key: str
    hotkey: str
    menu_text: str
    label: str
    render: Callable[[Draft], str]
    prompt: FieldPrompt
    help: str | None = None


async def edit_resource_draft(
    session: Session,
    lane: DatabaseLane,
    *,
    title: str,
    fields: list[FieldSpec],
    draft: Draft,
    save: Callable[[Draft], Awaitable[Any]],
    error_type: type[Exception],
    save_menu_text: str,
    back_menu_text: str,
    save_hotkey: str = "s",
    back_hotkey: str = "b",
) -> Any | None:
    """
    Drives one draft-based create/edit screen: renders `title` plus
    every field's current value, offers one hotkey per field (jumps
    straight to that field's own `prompt`) plus save/back, and loops
    until the caller either saves (returns whatever `save` returns) or
    backs out (returns `None`, `draft` discarded, nothing persisted or
    changed).

    `save(draft)` is the resource's own `create_*`/`update_*` call,
    already bound via closure to whatever it needs beyond the draft
    itself (`actor`, the existing resource being updated, `lane`,
    etc.) -- this function has no opinion on *how* a draft becomes a
    persisted resource, only on gathering the draft itself. `error_type`
    is caught around that call so a domain rejection (a duplicate name,
    an invalid combination) shows a friendly message and returns to the
    field menu with the draft intact, rather than crashing the session
    or silently discarding work already entered.
    """
    while True:
        await session.write_line("\r\n" + screen_title(title, width=session.terminal_width))
        for f in fields:
            value = sanitize_text(f.render(draft))
            await session.write_line(f"  {f.label}: {colored(value, fg_color=MUTED_COLOR)}")
        menu_line = action_bar(
            [f.menu_text for f in fields] + [save_menu_text, back_menu_text], width=session.terminal_width
        )
        await session.write_line(f"\r\n{menu_line}")
        if any(f.help for f in fields):
            # Only hinted when at least one field actually has help
            # authored -- otherwise Ctrl-H would be an undiscoverable
            # dead end advertised on every screen (issue #150's own
            # "does not need to cover every existing feature on day
            # one" scope extends to which screens mention it at all).
            await session.write_line(colored("(Ctrl-H for help on these fields)", fg_color=MUTED_COLOR))
        await session.write("Choice: ")
        choice = (await session.read_key()).lower()

        if choice == HELP_KEY:
            await _show_field_help(session, fields)
            continue
        if choice == back_hotkey or choice == CANCEL_KEY:
            # Issue #157: Ctrl-C as an incremental alias for [B]ack --
            # this screen's own "discard the draft" action.
            await session.write_line("")
            return None
        if choice == save_hotkey:
            await session.write_line("")
            try:
                return await save(draft)
            except error_type as exc:
                await session.write_line(colored(f"Could not save: {exc}", fg_color=MUTED_COLOR))
                continue

        field = next((f for f in fields if f.hotkey.lower() == choice), None)
        if field is None:
            await session.write(reject_unhandled_key(choice))
            continue
        await session.write_line("")
        await field.prompt(session, lane, draft)


async def _show_field_help(session: Session, fields: list[FieldSpec]) -> None:
    """Ctrl-H's own content (issue #150): every field with a `help`
    string authored, one after another -- not "whichever field the
    caller's cursor happens to be on," since this screen has no cursor
    concept at all (every field is always independently addressable by
    its own hotkey, see this module's own docstring). A reasonable
    reading of "contextual" for a screen shaped like this one."""
    documented = [f for f in fields if f.help]
    if not documented:
        await show_help(session, "Field help", ["No help is available for this screen yet."])
        return
    lines: list[str] = []
    for f in documented:
        lines.append(colored(f.label, fg_color=HEADER_COLOR, bold=True))
        lines.append(f"  {f.help}")
        lines.append("")
    await show_help(session, "Field help", lines[:-1])


def text_field(key: str, *, required: bool = False) -> FieldPrompt:
    """A plain single-line text prompt -- blank always keeps whatever
    is currently in the draft (matching every existing edit screen's
    own "blank = keep" convention); `required` only changes what the
    *current-value line* shows when the draft's value is still blank
    (a fresh "create" draft that hasn't had this field touched yet),
    never blocks typing here -- `save`'s own validation is where a
    still-blank required field actually gets rejected, the same
    "errors surface at Save, not mid-edit" shape `edit_resource_draft`
    itself already uses for domain (`error_type`) rejections."""

    async def prompt(session: Session, lane: DatabaseLane, draft: Draft) -> None:
        current = draft.get(key) or ""
        shown = current if current else "(blank)" if required else "(none)"
        await session.write(f"[{shown}] (blank = keep): ")
        raw = (await session.read_line()).strip()
        if raw:
            draft[key] = raw

    return prompt


def bool_field(key: str, prompt_text: str) -> FieldPrompt:
    """A toggle field -- always offers "keep current" via a bare
    Enter (`netbbs.net.confirm.prompt_yes_no_or_keep`'s own shape),
    for both a freshly-defaulted create draft and an existing value on
    edit alike."""
    from netbbs.net.confirm import prompt_yes_no_or_keep

    async def prompt(session: Session, lane: DatabaseLane, draft: Draft) -> None:
        draft[key] = await prompt_yes_no_or_keep(session, prompt_text, current=bool(draft.get(key)))

    return prompt


def choice_field(key: str, values: list[Any]) -> FieldPrompt:
    """A cycling multi-value toggle field (dogfood feature request,
    issue #153) -- `bool_field`'s "press the hotkey, no typing" shape
    generalized past two states: each press of the field's own hotkey
    advances `draft[key]` to the next entry in `values`, wrapping back
    to the first after the last. No sub-prompt, no I/O beyond the
    immediate advance -- exactly one keystroke changes the value, the
    same way `edit_resource_draft`'s outer loop already redraws the
    field's current value (via `render`) after every field
    interaction, so the caller sees each step of the cycle in turn.

    `values[0]` is the fallback starting point both when the draft
    doesn't yet contain `key` at all and when it holds a value that
    isn't one of `values` (defensive only -- every field-list caller
    seeds `key` from a real current/default value, this never happens
    in practice)."""

    async def prompt(session: Session, lane: DatabaseLane, draft: Draft) -> None:
        current = draft.get(key, values[0])
        try:
            index = values.index(current)
        except ValueError:
            index = -1
        draft[key] = values[(index + 1) % len(values)]

    return prompt
