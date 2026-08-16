"""
Per-user preference for whether/how verbosely `netbbs.rendering.layout.
menu_grid` shows each entry's short description underneath it (design
doc, dogfood feature request -- issue #160). A thin typed wrapper over
`netbbs.user_preferences`' generic per-user key-value store, the same
shape `netbbs.net.editor_preference`/`netbbs.net.color_depth_preference`
already established.

One setting with three states -- off / brief / detailed -- rather than
a separate on/off flag plus an independent verbosity level: there is
only ever one thing to reason about, on this screen or in code that
reads it back.

Defaults to `"brief"`: descriptions on by default (issue #160's own
stated goal -- "make the product intuitive to use without needing to
consult help"), matching every existing per-user preference's own
"safe, helpful default until a caller opts out" posture. A power user
who finds the extra lines noisy turns it off; nobody has to discover
and opt in just to get the benefit.
"""

from __future__ import annotations

from netbbs.auth.users import User
from netbbs.storage.database import Database
from netbbs.user_preferences import get_user_preference, set_user_preference

_PREFERENCE_KEY = "menu_description_level"
VALID_LEVELS = ("off", "brief", "detailed")
_DEFAULT_LEVEL = "brief"


def menu_description_level(db: Database, user: User) -> str:
    """`"off"`, `"brief"`, or `"detailed"` -- see module docstring for
    why `"brief"` is the default."""
    return get_user_preference(db, user, _PREFERENCE_KEY, default=_DEFAULT_LEVEL)


def set_menu_description_level(db: Database, user: User, value: str) -> None:
    if value not in VALID_LEVELS:
        raise ValueError(f"value must be one of {VALID_LEVELS}, got {value!r}")
    set_user_preference(db, user, _PREFERENCE_KEY, value)
