"""
Persisted "last N sessions" history (issue #100) -- one row per
authenticated login, recorded from `netbbs.net.login_flow.
run_authenticated_session`, the single entry point every transport
funnels through once a `User` is known-good.

Distinct from `netbbs.net.session_registry.ActiveSessionRegistry`,
which is in-memory and only ever knows about *currently* connected
sessions (design doc): this is the permanent, DB-backed record a caller
browses to see who has recently visited, independent of who happens to
still be online right now.

Row-count-bounded on every insert, the same reasoning
`netbbs.link.diagnostics`'s own pruning already established for a table
fed by an ongoing stream of events over a node's lifetime -- this
feature only ever wants the most recent slice, so there's no reason to
let it grow without bound.
"""

from __future__ import annotations

from dataclasses import dataclass

from netbbs.auth.users import User
from netbbs.storage.database import Database
from netbbs.timeutil import utc_now_iso
from netbbs.user_preferences import get_user_preference, set_user_preference

# Keeps only the most recent this-many rows on every insert -- generous
# enough that "last N sessions" (N well under this) always has a full
# window to draw from, small enough that the table can't grow without
# bound over a node's lifetime.
_MAX_SESSION_HISTORY_ROWS = 500

_NAME_VISIBLE_KEY = "session_history_name_visible"


@dataclass(frozen=True)
class SessionHistoryEntry:
    id: int
    user_id: int | None
    username_label: str
    connected_at: str
    disconnected_at: str | None


def record_session_start(db: Database, user: User) -> int:
    """Called once, at the top of `run_authenticated_session` -- returns
    the new row's id, which the caller holds onto for the matching
    `record_session_end` call when that same session ends."""
    db.connection.execute(
        "INSERT INTO session_history (user_id, username_label, connected_at) VALUES (?, ?, ?)",
        (user.id, user.username, utc_now_iso()),
    )
    row_id = db.connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    # Pruning happens alongside the insert that could have grown the
    # table past the cap, the same "bound it right where it grows"
    # placement `LinkDiagnosticLogHandler.emit` uses -- keeps the most
    # recent rows by id (insertion order), not by connected_at, so a
    # session started slightly "out of order" relative to another
    # (clock skew is not a concern here -- both are this node's own
    # utc_now_iso()) is never a factor.
    db.connection.execute(
        """
        DELETE FROM session_history WHERE id NOT IN (
            SELECT id FROM session_history ORDER BY id DESC LIMIT ?
        )
        """,
        (_MAX_SESSION_HISTORY_ROWS,),
    )
    db.connection.commit()
    return row_id


def record_session_end(db: Database, history_id: int) -> None:
    """A no-op if `history_id`'s row was already pruned away (an
    extremely long-lived session outlasting `_MAX_SESSION_HISTORY_ROWS`
    worth of *other* logins) -- matches `ActiveSessionRegistry.
    notify_one`/`disconnect_one`'s own tolerance for a target that's no
    longer there by the time this runs."""
    db.connection.execute(
        "UPDATE session_history SET disconnected_at = ? WHERE id = ?",
        (utc_now_iso(), history_id),
    )
    db.connection.commit()


def list_recent_sessions(db: Database, *, limit: int = 20) -> list[SessionHistoryEntry]:
    """Most recent first."""
    rows = db.connection.execute(
        "SELECT id, user_id, username_label, connected_at, disconnected_at "
        "FROM session_history ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        SessionHistoryEntry(
            id=row["id"], user_id=row["user_id"], username_label=row["username_label"],
            connected_at=row["connected_at"], disconnected_at=row["disconnected_at"],
        )
        for row in rows
    ]


def session_history_name_visible(db: Database, user: User) -> bool:
    """Default `True` (shown by name) -- opt-out, not opt-in, per the
    feature's own spec: shown by default, with an explicit toggle to
    anonymize. The opposite default from `netbbs.directory`'s bio
    visibility, same reasoning `netbbs.messaging_preferences` already
    documents: this isn't disclosing new personal content, just whether
    an already-necessarily-visible list entry is labeled or not."""
    return get_user_preference(db, user, _NAME_VISIBLE_KEY, default="1") == "1"


def set_session_history_name_visible(db: Database, user: User, visible: bool) -> None:
    set_user_preference(db, user, _NAME_VISIBLE_KEY, "1" if visible else "0")
