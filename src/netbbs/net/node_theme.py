"""
Lives in `netbbs.net`, not `netbbs.rendering`, matching where
`netbbs.net.color_depth_preference` (the closest precedent) already
lives -- `netbbs.rendering` stays a dependency-free foundational layer
with nothing in it importing `netbbs.net.session`, so a `Session`-aware
resolver belongs up here instead.

Node-wide identity-color overrides (GitHub issue #162) -- part three of
the skinning initiative `netbbs.net.welcome_banner`'s own module
docstring calls itself "part one" of (the main-menu masthead, issue
#161, is part two).

Deliberately narrow: only `ACCENT_COLOR`, `HEADER_COLOR`, and
`CLOCK_COLOR` -- the "branding" colors -- are ever overridable here.
Every semantic/status color in `netbbs.rendering.theme` (`ERROR_COLOR`,
`SUCCESS_COLOR`, `WARNING_COLOR`, `PRIVILEGE_COLOR`, `ALERT_COLOR`,
`VERIFIED_COLOR`) is intentionally absent from this module and always
stays exactly as `theme.py` defines it, everywhere -- a caller who has
used several NetBBS nodes can keep trusting "red always means failure,
green always means verified/success" regardless of what any node's
SysOp has branded their own node with. See issue #162's own "why not
full palette theming" section for the full reasoning; issue #163 tracks
that wider idea as considered-and-deferred.

Node-wide, not per-user, unlike `netbbs.net.color_depth_preference`
(the closest existing precedent for this module's own
override-wins-over-default shape): a SysOp sets these once for the
whole node, the same `node_config` scope `netbbs.net.welcome_banner`'s
own enabled flag already uses, not a per-account preference.

A SysOp supplies exactly one RGB triple per slot; `effective_*_color`
below derives the 256-color fallback automatically via
`netbbs.rendering.gradient.nearest_256` (the same downgrade
`gradient_text(..., truecolor=False)` already uses) for a session that
doesn't support truecolor, so nothing here ever needs a SysOp to pick
two numbers for one color.
"""

from __future__ import annotations

from netbbs.config import get_config, set_config
from netbbs.net.session import Session
from netbbs.rendering import ACCENT_COLOR, CLOCK_COLOR, HEADER_COLOR, nearest_256
from netbbs.storage.database import Database

_ACCENT_CONFIG_KEY = "theme_accent_rgb"
_HEADER_CONFIG_KEY = "theme_header_rgb"
_CLOCK_CONFIG_KEY = "theme_clock_rgb"


def _parse_rgb(value: str | None) -> tuple[int, int, int] | None:
    # "" is how `_set_color_override(rgb=None)` clears a slot below --
    # `netbbs.config` has no delete, only an overwrite -- so "" must
    # parse back to "no override" the same as a row that never existed.
    if not value:
        return None
    r, g, b = (int(part) for part in value.split(","))
    return (r, g, b)


def _color_override(db: Database, config_key: str) -> tuple[int, int, int] | None:
    return _parse_rgb(get_config(db, config_key))


def _set_color_override(db: Database, config_key: str, rgb: tuple[int, int, int] | None) -> None:
    if rgb is None:
        set_config(db, config_key, "")
        return
    r, g, b = rgb
    for name, value in (("r", r), ("g", g), ("b", b)):
        if not 0 <= value <= 255:
            raise ValueError(f"color override {name} must be 0-255, got {value}")
    set_config(db, config_key, f"{r},{g},{b}")


def _effective_color(
    session: Session, db: Database, config_key: str, default: int
) -> int | tuple[int, int, int]:
    override = _color_override(db, config_key)
    if override is None:
        return default
    return override if session.supports_truecolor else nearest_256(override)


# -- accent -----------------------------------------------------------


def accent_color_override(db: Database) -> tuple[int, int, int] | None:
    """`None` means no override -- every caller falls back to
    `theme.ACCENT_COLOR`, unchanged from today."""
    return _color_override(db, _ACCENT_CONFIG_KEY)


def set_accent_color_override(db: Database, rgb: tuple[int, int, int] | None) -> None:
    """`rgb=None` clears the override, reverting to `theme.ACCENT_COLOR`."""
    _set_color_override(db, _ACCENT_CONFIG_KEY, rgb)


def effective_accent_color(session: Session, db: Database) -> int | tuple[int, int, int]:
    """The color every accent-branded render call site (board/channel/
    user names, and every other spot `theme.ACCENT_COLOR` used to be
    used directly) should resolve through instead of importing the bare
    constant -- the SysOp's override RGB (downgraded to nearest-256 for
    a session without truecolor support) if set, `theme.ACCENT_COLOR`
    otherwise."""
    return _effective_color(session, db, _ACCENT_CONFIG_KEY, ACCENT_COLOR)


def effective_accent_color_256(db: Database) -> int:
    """Always the 256-color depth, ignoring any individual viewer's own
    truecolor support -- for a renderer that composes one shared string
    for many simultaneous recipients at once (`netbbs.net.chat_flow`'s
    broadcast message formatting, in particular), where no single
    per-session depth decision is even meaningful. NetBBS's live chat
    has never emitted truecolor at all (`chat_flow` never calls
    `gradient_text`); this keeps that a uniform property of the whole
    surface rather than carving out a partial truecolor exception just
    for the accent override."""
    override = accent_color_override(db)
    return ACCENT_COLOR if override is None else nearest_256(override)


# -- header (not yet wired into any render call site -- issue #162's own
# "land as a phased sweep" plan; accent is phase 1) --------------------


def header_color_override(db: Database) -> tuple[int, int, int] | None:
    return _color_override(db, _HEADER_CONFIG_KEY)


def set_header_color_override(db: Database, rgb: tuple[int, int, int] | None) -> None:
    _set_color_override(db, _HEADER_CONFIG_KEY, rgb)


def effective_header_color(session: Session, db: Database) -> int | tuple[int, int, int]:
    return _effective_color(session, db, _HEADER_CONFIG_KEY, HEADER_COLOR)


# -- clock (not yet wired into any render call site -- see above) ------


def clock_color_override(db: Database) -> tuple[int, int, int] | None:
    return _color_override(db, _CLOCK_CONFIG_KEY)


def set_clock_color_override(db: Database, rgb: tuple[int, int, int] | None) -> None:
    _set_color_override(db, _CLOCK_CONFIG_KEY, rgb)


def effective_clock_color(session: Session, db: Database) -> int | tuple[int, int, int]:
    return _effective_color(session, db, _CLOCK_CONFIG_KEY, CLOCK_COLOR)
