"""Transport-independent line composition and pre-commit review.

The fullscreen prose editor owns a cursor-addressed screen model. This
module deliberately does not: it gives the default Telnet/SSH/web path a
caller-owned logical-line buffer with explicit operations, then provides the
shared review state used after either editor. Domain flows remain responsible
for validation and persistence; finishing an editor only returns a draft.
"""

from __future__ import annotations

from enum import Enum, auto
from pathlib import Path

from netbbs.net.char_input import CANCEL_KEY, reject_unhandled_key
from netbbs.net.draft_storage import delete_draft, load_draft, offer_draft_recovery, save_draft
from netbbs.net.session import Session
from netbbs.rendering import (
    ACCENT_COLOR,
    HEADER_COLOR,
    LABEL_COLOR,
    MUTED_COLOR,
    MenuEntry,
    action_bar,
    colored,
    menu_grid,
    menu_key,
    reflow,
    sanitize_text,
    screen_title,
)


def _menu_row(entries: list[MenuEntry], *, width: int, height: int, description_level: str) -> str:
    """Compact `action_bar` packing when descriptions are off, `menu_grid`'s
    taller one-entry-per-line layout once the caller has opted into "brief"/
    "detailed" (issue #160's rollout) -- see `netbbs.net.resource_editor.
    edit_resource_draft`'s identical branch for why `menu_grid` alone isn't a
    byte-for-byte substitute for `action_bar`'s packed row at the off level."""
    if description_level == "off":
        return action_bar([e.label for e in entries], width=width)
    return menu_grid([("", entries)], width=width, height=height, description_level=description_level)


class ReviewAction(Enum):
    COMMIT = auto()
    EDIT_RECIPIENT = auto()
    EDIT_SUBJECT = auto()
    EDIT_BODY = auto()
    CANCEL = auto()


def _body_bytes(lines: list[str]) -> int:
    return len("\n".join(lines).encode("utf-8"))


async def _show_line_editor_help(session: Session, *, can_save_draft: bool) -> None:
    await session.write_line(colored("Line editor commands:", fg_color=HEADER_COLOR, bold=True))
    await session.write_line("  /done       finish editing and review the draft")
    await session.write_line("  /list       show all submitted lines")
    await session.write_line("  /insert N   insert a new line before line N")
    await session.write_line("  /edit N     replace line N")
    await session.write_line("  /delete N   delete line N")
    await session.write_line("  /cancel     discard the composition")
    if can_save_draft:
        # Dogfood feature request, issue #149: distinct from /cancel --
        # only offered when the caller passed a `draft_path` (persisted
        # posts, not e.g. mail, which has no resume mechanism to offer).
        await session.write_line("  /exit, /quit  save as a draft and leave -- resume it later")
    await session.write_line("  /help, /?   show these commands")
    await session.write_line("  //text      add a line beginning with /")


async def _show_lines(session: Session, lines: list[str]) -> None:
    if not lines:
        await session.write_line(colored("(body is empty)", fg_color=MUTED_COLOR))
        return
    width = max(1, session.terminal_width - 6)
    for number, line in enumerate(lines, start=1):
        safe = sanitize_text(line)
        wrapped = reflow(safe, width=width).splitlines() or [""]
        await session.write_line(f"{number:>3}: {wrapped[0]}")
        for continuation in wrapped[1:]:
            await session.write_line(f"     {continuation}")


def _parse_line_number(command: str, line_count: int, *, allow_end: bool = False) -> int | None:
    parts = command.split()
    if len(parts) != 2 or not parts[1].isdigit():
        return None
    number = int(parts[1])
    maximum = line_count + 1 if allow_end else line_count
    return number if 1 <= number <= maximum else None


async def edit_line_body(
    session: Session,
    *,
    initial_text: str | None,
    max_bytes: int,
    max_lines: int,
    draft_path: Path | None = None,
) -> str | None:
    """Edit a logical-line body without cursor-addressed terminal UI.

    Ordinary non-empty input appends one line; a blank line (or ``/done``)
    finishes into review. Blank paragraph lines remain expressible through
    ``/insert N``. Slash commands operate on the retained buffer; command
    follow-up prompts use ordinary ``read_line`` too, so behavior is identical
    on Telnet, SSH, and web sessions. ``None`` means either ``/cancel``
    (draft discarded) or ``/exit``/``/quit`` (draft saved) -- callers that
    need to tell the two apart check whether `draft_path` still exists.

    `draft_path` (dogfood feature request, issue #149), if given, is the
    same kind of caller-owned persistence target
    `netbbs.net.prose_editor.edit_prose` already uses for its own
    crash-recovery autosave -- see `netbbs.net.draft_storage`. A
    pre-existing draft there is offered for recovery on entry, same
    wording as the fullscreen editor; declining deletes it. `/cancel`
    always deletes it (nothing to keep). `/exit`/`/quit` are only
    recognized as commands at all when `draft_path` is given -- a
    caller with no resume mechanism to offer (e.g. mail composition)
    simply doesn't gain these two commands, same as before this
    parameter existed. Finishing normally (`/done`/blank line) deletes
    the draft too: the body is being handed back for real persistence,
    so the temporary autosave has nothing left to recover.
    """
    if draft_path is not None and draft_path.exists():
        if await offer_draft_recovery(session):
            initial_text = load_draft(draft_path)
        else:
            delete_draft(draft_path)
    lines = initial_text.split("\n") if initial_text is not None else []
    exit_hint = " /exit or /quit saves it as a draft;" if draft_path is not None else ""
    await session.write_line(
        f"Enter message text. Blank line or /done reviews the draft;{exit_hint} "
        "/help or /? shows editing commands."
    )
    if lines:
        await _show_lines(session, lines)

    async def apply(candidate: list[str]) -> bool:
        if len(candidate) > max_lines:
            await session.write_line(
                colored(f"Body cannot exceed {max_lines} logical lines.", fg_color=MUTED_COLOR)
            )
            return False
        size = _body_bytes(candidate)
        if size > max_bytes:
            await session.write_line(
                colored(f"Body cannot exceed {max_bytes} bytes (would be {size}).", fg_color=MUTED_COLOR)
            )
            return False
        lines[:] = candidate
        return True

    while True:
        await session.write(f"{len(lines) + 1}> ")
        raw = await session.read_line()
        command = raw.strip()
        lowered = command.lower()

        if raw == "" or lowered == "/done":
            body = "\n".join(lines)
            if not body.strip():
                await session.write_line(colored("Body cannot be blank.", fg_color=MUTED_COLOR))
                continue
            if draft_path is not None:
                delete_draft(draft_path)
            return body
        if lowered == "/cancel":
            if draft_path is not None:
                delete_draft(draft_path)
            return None
        if draft_path is not None and lowered in ("/exit", "/quit"):
            # No confirmation printed here on purpose -- the caller
            # (the only one who knows *where* this draft becomes
            # resumable, e.g. "next time you visit this board") owns
            # that message, the same way it already owns "Post
            # cancelled." Checking `draft_path.exists()` after a `None`
            # return is how a caller tells this apart from `/cancel`.
            save_draft(draft_path, "\n".join(lines))
            return None
        if lowered in ("/help", "/?"):
            await _show_line_editor_help(session, can_save_draft=draft_path is not None)
            continue
        if lowered == "/list":
            await _show_lines(session, lines)
            continue
        if lowered.startswith("/insert"):
            number = _parse_line_number(command, len(lines), allow_end=True)
            if number is None:
                await session.write_line(colored(f"Usage: /insert N (1-{len(lines) + 1})", fg_color=MUTED_COLOR))
                continue
            await session.write(f"New line {number}: ")
            text = await session.read_line()
            candidate = list(lines)
            candidate.insert(number - 1, text)
            await apply(candidate)
            continue
        if lowered.startswith("/edit"):
            number = _parse_line_number(command, len(lines))
            if number is None:
                await session.write_line(colored(f"Usage: /edit N (1-{len(lines)})", fg_color=MUTED_COLOR))
                continue
            await session.write_line(
                colored(
                    f"Current line {number}: {sanitize_text(lines[number - 1])}",
                    fg_color=MUTED_COLOR,
                )
            )
            await session.write(f"Replacement line {number}: ")
            text = await session.read_line()
            candidate = list(lines)
            candidate[number - 1] = text
            await apply(candidate)
            continue
        if lowered.startswith("/delete"):
            number = _parse_line_number(command, len(lines))
            if number is None:
                await session.write_line(colored(f"Usage: /delete N (1-{len(lines)})", fg_color=MUTED_COLOR))
                continue
            candidate = list(lines)
            deleted = candidate.pop(number - 1)
            if await apply(candidate):
                await session.write_line(
                    colored(f"Deleted line {number}: {sanitize_text(deleted)}", fg_color=MUTED_COLOR)
                )
            continue
        if raw.startswith("//"):
            raw = raw[1:]
        elif raw.startswith("/"):
            await session.write_line(
                colored(
                    "Unknown editor command. Type /help, or // to begin a text line with /.",
                    fg_color=MUTED_COLOR,
                )
            )
            continue

        await apply([*lines, raw])


def _preview_body(body: str, width: int) -> str:
    safe = sanitize_text(body, allow_newlines=True)
    return "\n".join(reflow(line, width=max(1, width)) if line else "" for line in safe.split("\n"))


async def review_composition(
    session: Session,
    *,
    subject: str,
    body: str,
    recipient: str | None,
    commit_key: str,
    commit_label: str,
    commit_brief: str | None = None,
    description_level: str = "off",
) -> ReviewAction:
    """Render a complete draft and return one explicit review action.

    `commit_brief` and `description_level` (issue #160's rollout to this
    screen) describe the caller-supplied commit action for `menu_grid`'s
    description text -- this module has no domain knowledge of its own
    (posting a board message, sending mail, etc.) to describe it with,
    unlike the other fixed T/U/B/C options below. `description_level`
    should be the caller's already-resolved `menu_description_level`
    preference, same caching rule as every other screen in this rollout."""
    heading = screen_title(
        "Review composition",
        breadcrumb=("NetBBS", "Compose"),
        subtitle="Check the draft before continuing",
        width=session.terminal_width,
    )
    await session.write_line(f"\r\n{heading}")
    if recipient is not None:
        await session.write_line(
            colored("To: ", fg_color=LABEL_COLOR)
            + colored(sanitize_text(recipient), fg_color=ACCENT_COLOR)
        )
    await session.write_line(
        colored("Subject: ", fg_color=LABEL_COLOR)
        + colored(sanitize_text(subject), fg_color=ACCENT_COLOR, bold=True)
    )
    await session.write_line(colored("Body", fg_color=MUTED_COLOR, bold=True))
    await session.write_line(_preview_body(body, session.terminal_width))

    options = [MenuEntry(label=menu_key(commit_key.upper(), commit_label), brief=commit_brief)]
    if recipient is not None:
        options.append(MenuEntry(label=menu_key("T", "o"), brief="Change the recipient"))
    options.extend([
        MenuEntry(label=menu_key("U", "pdate subject"), brief="Change the subject"),
        MenuEntry(label=menu_key("B", "ody"), brief="Edit the body text"),
        MenuEntry(label=menu_key("C", "ancel"), brief="Discard this draft"),
    ])
    await session.write_line(
        f"\r\n{_menu_row(options, width=session.terminal_width, height=session.terminal_height, description_level=description_level)}"
    )
    await session.write("Choice: ")

    actions = {
        commit_key.lower(): ReviewAction.COMMIT,
        "u": ReviewAction.EDIT_SUBJECT,
        "b": ReviewAction.EDIT_BODY,
        "c": ReviewAction.CANCEL,
        # Issue #157: Ctrl-C as an incremental alias for [C]ancel.
        CANCEL_KEY: ReviewAction.CANCEL,
    }
    if recipient is not None:
        actions["t"] = ReviewAction.EDIT_RECIPIENT
    while True:
        choice = (await session.read_key()).lower()
        action = actions.get(choice)
        if action is not None:
            await session.write_line("")
            return action
        await session.write(reject_unhandled_key(choice))
