"""
Bounded run-history for recurring node operations (backup, update
check) -- SysOp reporting dogfood follow-up.

Before this, `netbbs.backup`/`netbbs.selfupdate` each tracked only a
single last-known point in time via `netbbs.config`'s single-value
key-value store, overwritten on every run -- a SysOp had no way to
tell "this runs on a healthy schedule" from "it happened to succeed
once." One shared table for both kinds of run, mirroring
`netbbs.moderation.log`'s own "one shared table rather than a bespoke
log per feature" precedent: `kind` distinguishes 'backup' from
'update_check' the same way `moderation_log.action` distinguishes
grant/mute/ban/etc, rather than two near-identical tables to keep in
sync.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from netbbs.storage.database import Database
from netbbs.timeutil import utc_now_iso

# How many of the most recent rows to keep per `kind` -- this is
# reporting context for a SysOp glancing at recent run health, not a
# permanent audit trail, so unbounded growth here would be pure waste.
# Mirrors `netbbs.link.diagnostics.LinkDiagnosticLogHandler`'s own
# prune-on-insert bound.
_MAX_ROWS_PER_KIND = 20


@dataclass(frozen=True)
class OperationalRun:
    id: int
    kind: str
    outcome: str
    detail: str | None
    created_at: str


def record_operational_run(
    db: Database, kind: str, outcome: str, *, detail: str | None = None
) -> OperationalRun:
    """
    Append one run record for `kind` ('backup' or 'update_check'),
    pruning that kind's own history back down to the most recent
    `_MAX_ROWS_PER_KIND` rows in the same write.
    """
    created_at = utc_now_iso()
    cursor = db.connection.execute(
        "INSERT INTO operational_run_history (kind, outcome, detail, created_at) VALUES (?, ?, ?, ?)",
        (kind, outcome, detail, created_at),
    )
    db.connection.execute(
        """
        DELETE FROM operational_run_history WHERE kind = ? AND id NOT IN (
            SELECT id FROM operational_run_history WHERE kind = ? ORDER BY id DESC LIMIT ?
        )
        """,
        (kind, kind, _MAX_ROWS_PER_KIND),
    )
    db.connection.commit()
    row = db.connection.execute(
        "SELECT * FROM operational_run_history WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _row_to_run(row)


def list_operational_run_history(
    db: Database, kind: str, *, limit: int = _MAX_ROWS_PER_KIND
) -> list[OperationalRun]:
    """Most recent first."""
    rows = db.connection.execute(
        "SELECT * FROM operational_run_history WHERE kind = ? ORDER BY id DESC LIMIT ?",
        (kind, limit),
    ).fetchall()
    return [_row_to_run(row) for row in rows]


def _row_to_run(row: sqlite3.Row) -> OperationalRun:
    return OperationalRun(
        id=row["id"],
        kind=row["kind"],
        outcome=row["outcome"],
        detail=row["detail"],
        created_at=row["created_at"],
    )
