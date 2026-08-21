"""
Per-user "always collapse the top status line's breadcrumb to just the
current location" preference (dogfood feature request, follow-up to the
pre-5.0.0 style rollout). Same thin wrapper over `netbbs.user_
preferences`'s generic per-user store as `netbbs.net.redraw_preference`/
`netbbs.net.unicode_style_preference`/etc.

Off by default, matching `redraw_preference`'s own reasoning rather than
`unicode_style_preference`'s "rich default" one: `netbbs.rendering.
layout.screen_title` already collapses to the current segment on its own
whenever the full breadcrumb genuinely doesn't fit `width` (the dynamic
half of this feature, not gated by this preference at all -- see that
function's own docstring), so this preference only controls whether a
caller wants the *shorter* form even when there'd be room for the full
one. That's a matter of taste, not a correctness fix, so nobody should
have to discover an "off" switch just to get today's existing behavior
back -- the inverse of `menu_description_preference`'s "nobody should
have to opt in to a fix" reasoning.
"""

from __future__ import annotations

from netbbs.auth.users import User
from netbbs.storage.database import Database
from netbbs.user_preferences import get_user_preference, set_user_preference

_BREADCRUMB_COLLAPSED_KEY = "breadcrumb_collapsed"


def breadcrumb_collapsed_enabled(db: Database, user: User) -> bool:
    return get_user_preference(db, user, _BREADCRUMB_COLLAPSED_KEY, default="0") == "1"


def set_breadcrumb_collapsed_enabled(db: Database, user: User, enabled: bool) -> None:
    set_user_preference(db, user, _BREADCRUMB_COLLAPSED_KEY, "1" if enabled else "0")
