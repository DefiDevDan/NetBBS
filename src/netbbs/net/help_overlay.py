"""
Shared in-context help rendering (dogfood feature request, issue
#150): one small primitive reused by two genuinely different contexts
-- the fullscreen prose editor's cursor-addressed screen
(`netbbs.net.prose_editor`, Ctrl+G) and ordinary plain-scrolling
SysOp prompts (`netbbs.net.resource_editor`, Ctrl-H via
`netbbs.net.char_input.HELP_KEY`).

Deliberately does *not* clear or otherwise manage the screen around
itself -- that's a per-context concern, not something this module has
an opinion on. A cursor-addressed caller clears first and redraws its
own previous state afterward (its own existing redraw machinery
already does this for other reasons, e.g. Ctrl-L); a plain scrolling
caller just lets the help block scroll like any other inline text,
the same convention `netbbs.net.composition._show_line_editor_help`
already uses. This is what makes one function actually reusable by
both rather than two bespoke near-duplicates.
"""

from __future__ import annotations

from netbbs.net.session import Session
from netbbs.rendering import HEADER_COLOR, MUTED_COLOR, colored


async def show_help(session: Session, title: str, lines: list[str]) -> None:
    """Print a titled help block, then wait for any keystroke before
    returning. `lines` are written as-is (already-composed strings) --
    this function has no opinion on their content, only on presenting
    and waiting."""
    await session.write_line(colored(title, fg_color=HEADER_COLOR, bold=True))
    for line in lines:
        await session.write_line(line)
    await session.write_line(colored("Press any key to continue...", fg_color=MUTED_COLOR))
    await session.read_key()
