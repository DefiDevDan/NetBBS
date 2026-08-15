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

from netbbs.net.char_input import reject_unhandled_key
from netbbs.net.session import Session
from netbbs.rendering import HEADER_COLOR, MUTED_COLOR, colored, sanitize_text
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
    """

    key: str
    hotkey: str
    menu_text: str
    label: str
    render: Callable[[Draft], str]
    prompt: FieldPrompt


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
        await session.write_line(colored(f"\r\n{title}", fg_color=HEADER_COLOR, bold=True))
        for f in fields:
            value = sanitize_text(f.render(draft))
            await session.write_line(f"  {f.label}: {colored(value, fg_color=MUTED_COLOR)}")
        menu_line = "  ".join([f.menu_text for f in fields] + [save_menu_text, back_menu_text])
        await session.write_line(f"\r\n{menu_line}")
        await session.write("Choice: ")
        choice = (await session.read_key()).lower()

        if choice == back_hotkey:
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
