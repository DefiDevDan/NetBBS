"""
Shared "[O]rder" sub-flow (design doc, dogfood feature request) behind
`netbbs.net.picker.pick_item`'s optional `on_sort` callback: choose a
new sort mode, choose where to remember it (just this time / this
category / this Community / your global default for this resource
kind), persist it via `netbbs.sort_preferences`, and return the newly
chosen mode.

One shared implementation for channels/boards/file areas, the same
"the underlying problem is the same across all three" reasoning
`netbbs.net.picker`'s own module docstring already gives for the
picker itself -- this module knows nothing about any one resource
kind's own list_*/hub mechanics; the caller supplies `resource_kind`
plus whatever Community/category context applies and re-fetches its
own freshly sorted item list afterward.
"""

from __future__ import annotations

from netbbs.auth.users import User
from netbbs.net.char_input import reject_unhandled_key
from netbbs.net.session import Session
from netbbs.rendering import menu_key
from netbbs.sort_preferences import set_sort_preference
from netbbs.storage.execution import DatabaseLane


async def prompt_sort_change(
    session: Session,
    lane: DatabaseLane,
    user: User,
    resource_kind: str,
    *,
    community_id: int | None = None,
    community_name: str | None = None,
    category_id: int | None = None,
    category_name: str | None = None,
    volume_label: str = "Volume",
) -> str | None:
    """
    Prompts for a new sort mode, then (unless the user picks "just this
    time") which scope to remember it at, persists that via
    `netbbs.sort_preferences.set_sort_preference`, and returns the
    newly chosen mode. Returns `None`, with nothing persisted, if the
    user backs out of the mode prompt itself without choosing one.

    `community_id`/`category_id` describe *where* the picker being
    customized currently is, so the matching save-scope option can be
    offered at all -- pass whichever apply, with their `*_name` for
    display; passing neither still lets the user set the bare per-kind
    global default (the "Just this time"/"Global default" choices are
    always offered).

    `volume_label` overrides "Volume"'s displayed word (and, since the
    hotkey is always that word's own first letter, its hotkey too) for
    a resource kind where the underlying `"volume"` mode means
    something other than a stored-content count -- channels pass
    "Participants" (live headcount, not persisted chat history; see
    `netbbs.net.chat_flow._pick_channel`'s own docstring).
    """
    volume_hotkey = volume_label[0].lower()
    mode_keys = {"a": "activity", "l": "alphabetical", "r": "recent", volume_hotkey: "volume"}
    mode_nav = "  ".join(
        [
            menu_key("A", "ctivity"),
            menu_key("L", "phabetical", prefix="A"),
            menu_key("R", "ecent"),
            menu_key(volume_label[0].upper(), volume_label[1:]),
            menu_key("B", "ack"),
        ]
    )
    await session.write_line("")
    await session.write_line(f"Sort by: {mode_nav}")
    while True:
        await session.write("Choice: ")
        choice = (await session.read_key()).lower()
        if choice == "b":
            await session.write_line("")
            return None
        if choice in mode_keys:
            mode = mode_keys[choice]
            await session.write_line("")
            break
        await session.write(reject_unhandled_key(choice))

    # "Just this time" always first, "Global default" always last --
    # everything in between is however many of the two context-specific
    # scopes actually apply here, most specific first, matching
    # get_effective_sort_mode's own most-specific-first precedence.
    scope_actions: dict[str, dict[str, int] | None] = {"j": None}
    scope_nav = [menu_key("J", "ust this time")]
    if category_id is not None:
        label = f" ({category_name})" if category_name else ""
        scope_nav.append(menu_key("C", f"ategory{label}"))
        scope_actions["c"] = {"category_id": category_id}
    if community_id is not None:
        label = f" ({community_name})" if community_name else ""
        scope_nav.append(menu_key("W", f"hole Community{label}"))
        scope_actions["w"] = {"community_id": community_id}
    scope_nav.append(menu_key("G", "lobal default"))
    scope_actions["g"] = {}

    await session.write_line(f"Remember this as: {'  '.join(scope_nav)}")
    while True:
        await session.write("Choice: ")
        choice = (await session.read_key()).lower()
        if choice in scope_actions:
            break
        await session.write(reject_unhandled_key(choice))
    await session.write_line("")

    save_kwargs = scope_actions[choice]
    if save_kwargs is not None:
        await lane.run(set_sort_preference, user, resource_kind, mode, **save_kwargs)

    return mode
