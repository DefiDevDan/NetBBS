"""
The node's login/welcome banner (design doc -- welcome banner), part of
a broader skinning initiative; deliberately independent of the larger
TUI/editor context (see design doc for that).

A SysOp who wants custom ANSI art at login places a `.ans` file
directly on the node's filesystem, at the well-known path this module
resolves (`banner_path`), then enables it via `netbbs.net.admin_flow`'s
`[W]elcome banner` screen. There is no in-BBS upload mechanism --
the file is authored externally (a normal ANSI-art-scene tool,
or a download) and placed on the node the same way its SSH host key
already is: colocated with the database file
(`netbbs.net.ssh.ensure_host_key`'s established pattern), not stored
inside SQLite (`node_config` stays reserved for small string settings)
and not routed through the content-addressed file-area storage (that
scheme exists for many uploaded files; this is a single node-wide
singleton).

`load_welcome_banner` is the login-time hot path, called on every
single connection -- every failure mode it can encounter (missing
file, oversized file, unreadable file) falls back to
`DEFAULT_WELCOME_BANNER` silently rather than ever raising or showing
a raw error to an anonymous pre-auth session. It deliberately never
calls `netbbs.rendering.reflow` (would destroy fixed-width ANSI art
alignment -- real art is authored at a fixed width, 80 columns being
the classic BBS standard) or `netbbs.rendering.sanitize_text` (would
strip the art's own ESC sequences -- see `netbbs.rendering.ansi_art`'s
module docstring for why this content is trusted, SysOp-authored
content at the same tier as `colored()` output, not something to
sanitize).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from netbbs.config import get_config, set_config
from netbbs.rendering import HEADER_COLOR, RESET, colored, decode_ansi_bytes, gradient_text
from netbbs.rendering.layout import double_frame
from netbbs.storage.database import Database

_logger = logging.getLogger(__name__)

# Style spec (round following the pre-5.0.0 "beautify" audit): the
# double-line frame is NetBBS's one standard panel style, not gated
# behind a per-account `unicode_style` check here -- this banner is
# shown pre-login, to anonymous connections with no account/preference
# to look up yet, and (see `unicode_style_preference`'s own docstring)
# NetBBS's Telnet transport already sends every screen as UTF-8
# unconditionally regardless of any preference, so there's no separate
# "safe ASCII" pre-login mode to fall back to here in the first place.
DEFAULT_WELCOME_BANNER = (
    double_frame(
        [
            "",
            colored(" " * 21 + "N E T B B S", fg_color=HEADER_COLOR, bold=True),
            colored(" " * 7 + "conversations across independent nodes", fg_color=HEADER_COLOR, bold=True),
            "",
        ],
        width=58,
    )
    + "\r\n"
    + colored("  NetBBS Link  ›  private experimental federation", fg_color=HEADER_COLOR, bold=True)
)


def _default_welcome_banner(*, truecolor: bool) -> str:
    """`DEFAULT_WELCOME_BANNER` stays a static, precomputed, 256-color-
    safe constant -- correct for every client -- since it can't itself
    depend on a per-session flag that doesn't exist at import time. This
    builds the truecolor variant per-call instead: the "NetBBS" name
    gets `gradient_text`'s per-character flair, composed alongside the
    surrounding flat-`HEADER_COLOR` border/subtitle via concatenated
    `colored()`/`gradient_text()` spans -- the same "one colored() call
    per span, concatenated" shape `netbbs.rendering.reflow.
    colored_truncate` already uses, just assembled by hand here since
    this banner isn't a segment list."""
    if not truecolor:
        return DEFAULT_WELCOME_BANNER
    # The full-width border makes negotiated truecolor unmistakable at a
    # glance instead of confining the showcase to six subtly shaded letters.
    # The 256-color fallback above intentionally remains one flat cyan span.
    border_text = "╔══════════════════════════════════════════════════════╗"
    border = gradient_text(border_text, "blue", bold=True, truecolor=True)
    bottom_border = gradient_text(border_text.replace("╔", "╚").replace("╗", "╝"), "blue", bold=True, truecolor=True)
    wordmark = gradient_text("N E T B B S", "blue", bold=True, truecolor=True)
    welcome_line = colored("║                      ", fg_color=HEADER_COLOR, bold=True) + wordmark + colored(
        "                     ║", fg_color=HEADER_COLOR, bold=True
    )
    blank = colored("║                                                      ║", fg_color=HEADER_COLOR, bold=True)
    tagline = colored(
        "║        conversations across independent nodes        ║",
        fg_color=HEADER_COLOR,
        bold=True,
    )
    subtitle = colored(
        "  NetBBS Link  ›  private experimental federation", fg_color=HEADER_COLOR, bold=True
    )
    return "\r\n".join([border, blank, welcome_line, tagline, blank, bottom_border, subtitle])

# Comfortably covers realistic ANSI art (typically a few KB, rarely
# above ~150 KB even for elaborate multi-panel pieces) while bounding a
# SysOp accidentally pointing the path at something pathological. Not
# admin-configurable.
MAX_BANNER_SIZE_BYTES = 262_144  # 256 KiB

_WELCOME_BANNER_ENABLED_CONFIG_KEY = "welcome_banner_enabled"


def is_welcome_banner_enabled(db: Database) -> bool:
    return get_config(db, _WELCOME_BANNER_ENABLED_CONFIG_KEY) == "1"


def set_welcome_banner_enabled(db: Database, enabled: bool) -> None:
    set_config(db, _WELCOME_BANNER_ENABLED_CONFIG_KEY, "1" if enabled else "0")


def banner_path(db: Database) -> Path:
    """The well-known path a custom banner file must be placed at,
    colocated with the database file. Deliberately does not
    auto-create anything (unlike `netbbs.net.ssh.ensure_host_key`) --
    a missing file is normal, expected state here, not an error to
    paper over."""
    return db.path.parent / f"{db.path.stem}_welcome_banner.ans"


@dataclass(frozen=True)
class WelcomeBannerStatus:
    enabled: bool
    path: Path
    exists: bool
    size_bytes: int | None


def welcome_banner_status(db: Database) -> WelcomeBannerStatus:
    """Cheap, `stat()`-based introspection for the admin screens --
    never reads the file's actual content."""
    path = banner_path(db)
    exists = path.exists()
    size_bytes = path.stat().st_size if exists else None
    return WelcomeBannerStatus(
        enabled=is_welcome_banner_enabled(db), path=path, exists=exists, size_bytes=size_bytes
    )


def load_welcome_banner(db: Database, *, truecolor: bool = False) -> str:
    """
    Resolve the banner to show at login: the SysOp's custom file if
    enabled and usable, the default banner otherwise. Synchronous
    -- matches existing precedent (`netbbs.config.get_config`,
    `netbbs.net.ssh.ensure_host_key`) of plain blocking local disk/DB
    calls made directly from async functions; a sub-256KB read isn't
    worth `asyncio.to_thread`.

    `truecolor` (default `False`, the safe universal choice) selects
    whether the *default* banner's "NetBBS" name is rendered with a
    truecolor gradient (`_default_welcome_banner`) -- callers should
    pass their session's negotiated/effective truecolor support (see
    `netbbs.net.session.Session.supports_truecolor`). Has no effect on
    the SysOp's custom `.ans` file path: that content is trusted,
    already-composed art, shown exactly as authored regardless of this
    flag.

    Every fallback here is silent to the connecting user (never show a
    raw error to an anonymous pre-auth session -- every visitor would
    see it) but logged server-side at WARNING level so a SysOp can
    diagnose a vanished/oversized/unreadable file after enabling it.
    `netbbs.net.admin_flow`'s `[E]nable` screen already checks for
    these conditions proactively before allowing enable, so they
    shouldn't normally arise here -- but this function must defend
    against them independently anyway, since it runs unattended on
    every login regardless of how the flag got set.
    """
    if not is_welcome_banner_enabled(db):
        return _default_welcome_banner(truecolor=truecolor)

    path = banner_path(db)
    if not path.exists():
        _logger.warning("welcome banner enabled but missing at %s -- using default", path)
        return _default_welcome_banner(truecolor=truecolor)

    try:
        size = path.stat().st_size
        if size > MAX_BANNER_SIZE_BYTES:
            _logger.warning(
                "welcome banner at %s is %d bytes, over the %d byte limit -- using default",
                path, size, MAX_BANNER_SIZE_BYTES,
            )
            return _default_welcome_banner(truecolor=truecolor)
        data = path.read_bytes()
    except OSError:
        _logger.warning("could not read welcome banner at %s -- using default", path, exc_info=True)
        return _default_welcome_banner(truecolor=truecolor)

    # decode_ansi_bytes cannot raise (see its own docstring) -- no
    # decode-failure fallback is needed here, by construction.
    return decode_ansi_bytes(data) + RESET
