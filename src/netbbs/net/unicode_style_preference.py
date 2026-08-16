"""
Per-user "use Unicode decorative characters (breadcrumb arrows, and
whatever else opts into this later) instead of plain ASCII" preference
(dogfood feature request). A thin typed wrapper over
`netbbs.user_preferences`' generic per-user key-value store, the same
shape `netbbs.net.editor_preference`/`netbbs.net.color_depth_preference`/
`netbbs.net.menu_description_preference`/`netbbs.net.redraw_preference`
already established.

Defaults to `True`, unlike `redraw_preference`'s own off-by-default
choice: NetBBS's Telnet transport already unconditionally encodes every
live screen as UTF-8 today (no ASCII/CP437 fallback path exists for
anything currently on screen), so this isn't "enabling Unicode" so much
as choosing a *decorative style* that happens to use a few more Unicode
glyphs than plain ASCII punctuation -- the downside of guessing wrong is
some glyphs rendering oddly, not real functionality lost the way
`redraw_preference`'s own scrollback trade-off is. Matches this
codebase's more common "rich default, easy opt-out" posture instead
(`menu_description_preference`'s own stated reasoning: "nobody has to
discover and opt in just to get the benefit").

Since a genuinely non-UTF-8-capable client can't be reliably detected
(no Telnet/SSH negotiation for it -- unlike `color_depth_preference`'s
own COLORTERM signal), the fast-feedback safety net lives in
`netbbs.net.login_flow`'s one-time post-login confirmation prompt
instead: shown once, right after the first Unicode-styled screen an
account with `unicode_style_ever_set() is False` actually sees, asking
whether it looked garbled. Answering either way (even "keep it on")
calls `set_unicode_style_enabled` and so counts as touched, the same
"a set call to the current value still marks it as touched" contract
`redraw_preference`'s own `_ever_set` already established -- verified
by that module's own test suite, mirrored here.
"""

from __future__ import annotations

from netbbs.auth.users import User
from netbbs.storage.database import Database
from netbbs.user_preferences import get_user_preference, set_user_preference

_PREFERENCE_KEY = "unicode_style"


def unicode_style_enabled(db: Database, user: User) -> bool:
    return get_user_preference(db, user, _PREFERENCE_KEY, default="on") == "on"


def unicode_style_ever_set(db: Database, user: User) -> bool:
    """Whether this account has ever explicitly touched the setting --
    including via the one-time post-login confirmation prompt answering
    "keep it on" -- gates that prompt from ever asking a second time."""
    return get_user_preference(db, user, _PREFERENCE_KEY, default=None) is not None


def set_unicode_style_enabled(db: Database, user: User, enabled: bool) -> None:
    set_user_preference(db, user, _PREFERENCE_KEY, "on" if enabled else "off")
