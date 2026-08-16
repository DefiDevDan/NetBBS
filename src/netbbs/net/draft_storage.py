"""
Shared plain-text draft persistence (dogfood feature request, issue
#149): three small, permission-tolerant file operations plus the
"a draft was found -- resume it?" prompt, factored out of
`netbbs.net.prose_editor`'s own pre-existing crash-recovery autosave so
`netbbs.net.composition`'s line editor can offer the identical
recovery/`/exit`-and-resume experience without duplicating it. Callers
own the path convention (`netbbs.net.login_flow._post_draft_path`) and
the UX around *when* to offer recovery, delete, or leave a draft in
place -- this module has no opinion on any of that, only on reading,
writing, and deleting the file itself.
"""

from __future__ import annotations

import logging
from pathlib import Path

from netbbs.net.confirm import prompt_yes_no
from netbbs.net.session import Session
from netbbs.rendering import MUTED_COLOR, colored

_logger = logging.getLogger(__name__)


def save_draft(path: Path, text: str) -> None:
    try:
        path.write_text(text, encoding="utf-8")
    except OSError:
        _logger.warning("could not write draft to %s", path, exc_info=True)


def load_draft(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def delete_draft(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        _logger.warning("could not delete draft at %s", path, exc_info=True)


async def offer_draft_recovery(session: Session) -> bool:
    """Asks whether to resume a draft found on disk at editor entry --
    shared wording/prompt for both editors, so a caller sees the same
    message regardless of which one it opens into."""
    await session.write_line(
        colored(
            "\r\nA draft from a previous session was found here (likely left behind by a "
            "dropped connection, or an earlier /exit).",
            fg_color=MUTED_COLOR,
        )
    )
    return await prompt_yes_no(session, "Resume it?", default=False)
