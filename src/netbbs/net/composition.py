"""Transport-independent line composition and pre-commit review.

The fullscreen prose editor owns a cursor-addressed screen model. This
module deliberately does not: it gives the default Telnet/SSH/web path a
caller-owned logical-line buffer with explicit operations, then provides the
shared review state used after either editor. Domain flows remain responsible
for validation and persistence; finishing an editor only returns a draft.
"""

from __future__ import annotations

from enum import Enum, auto

from netbbs.net.char_input import reject_unhandled_key
from netbbs.net.session import Session
from netbbs.rendering import HEADER_COLOR, MUTED_COLOR, colored, menu_key, reflow, sanitize_text


class ReviewAction(Enum):
    COMMIT = auto()
    EDIT_RECIPIENT = auto()
    EDIT_SUBJECT = auto()
    EDIT_BODY = auto()
    CANCEL = auto()


def _body_bytes(lines: list[str]) -> int:
    return len("\n".join(lines).encode("utf-8"))


async def _show_line_editor_help(session: Session) -> None:
    await session.write_line(colored("Line editor commands:", fg_color=HEADER_COLOR, bold=True))
    await session.write_line("  /done       finish editing and review the draft")
    await session.write_line("  /list       show all submitted lines")
    await session.write_line("  /insert N   insert a new line before line N")
    await session.write_line("  /edit N     replace line N")
    await session.write_line("  /delete N   delete line N")
    await session.write_line("  /cancel     discard the composition")
    await session.write_line("  /help       show these commands")
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
) -> str | None:
    """Edit a logical-line body without cursor-addressed terminal UI.

    Ordinary non-empty input appends one line; a blank line (or ``/done``)
    finishes into review. Blank paragraph lines remain expressible through
    ``/insert N``. Slash commands operate on the retained buffer; command
    follow-up prompts use ordinary ``read_line`` too, so behavior is identical
    on Telnet, SSH, and web sessions. ``None`` means explicit ``/cancel``.
    """
    lines = initial_text.split("\n") if initial_text is not None else []
    await session.write_line(
        "Enter message text. Blank line or /done reviews the draft; /help shows editing commands."
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
            return body
        if lowered == "/cancel":
            return None
        if lowered == "/help":
            await _show_line_editor_help(session)
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
) -> ReviewAction:
    """Render a complete draft and return one explicit review action."""
    await session.write_line(colored("\r\nReview composition", fg_color=HEADER_COLOR, bold=True))
    if recipient is not None:
        await session.write_line(f"To: {sanitize_text(recipient)}")
    await session.write_line(f"Subject: {sanitize_text(subject)}")
    await session.write_line(colored("Body:", fg_color=MUTED_COLOR))
    await session.write_line(_preview_body(body, session.terminal_width))

    options = [menu_key(commit_key.upper(), commit_label)]
    if recipient is not None:
        options.append(menu_key("T", "o"))
    options.extend([menu_key("U", "pdate subject"), menu_key("B", "ody"), menu_key("C", "ancel")])
    await session.write_line("  ".join(options))
    await session.write("Choice: ")

    actions = {
        commit_key.lower(): ReviewAction.COMMIT,
        "u": ReviewAction.EDIT_SUBJECT,
        "b": ReviewAction.EDIT_BODY,
        "c": ReviewAction.CANCEL,
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
