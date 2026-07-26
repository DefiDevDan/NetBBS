"""Regression coverage for Last Sessions privacy reconciliation (#123)."""

import sqlite3

import pytest

from netbbs.auth.users import create_user, delete_user
from netbbs.session_history import (
    list_recent_sessions,
    reconcile_interrupted_sessions,
    record_session_end,
    record_session_start,
    session_history_name_visible,
    set_session_history_name_visible,
)
from netbbs.storage.database import Database


def test_startup_reconciliation_backfills_preexisting_opt_out(tmp_path):
    db = Database(tmp_path / "node.db")
    try:
        alice = create_user(db, "alice", password="hunter2", user_level=10)
        sysop = create_user(db, "sysop", password="hunter2", user_level=255)
        history_id = record_session_start(db, alice)
        record_session_end(db, history_id)

        db.connection.execute(
            "INSERT INTO user_preferences (user_id, key, value) VALUES (?, ?, '0') "
            "ON CONFLICT(user_id, key) DO UPDATE SET value = '0'",
            (alice.id, "session_history_name_visible"),
        )
        db.connection.execute(
            "UPDATE session_history SET name_visible_fallback = 1 WHERE user_id = ?",
            (alice.id,),
        )
        db.connection.commit()

        assert session_history_name_visible(db, alice) is False
        assert list_recent_sessions(db)[0].name_visible_fallback is True
        assert reconcile_interrupted_sessions(db) == 0
        assert list_recent_sessions(db)[0].name_visible_fallback is False

        delete_user(db, alice, deleted_by=sysop)
        entry = list_recent_sessions(db)[0]
        assert entry.user_id is None
        assert entry.name_visible_fallback is False
    finally:
        db.close()


def test_visibility_preference_and_fallback_rollback_together(tmp_path):
    db = Database(tmp_path / "node.db")
    try:
        alice = create_user(db, "alice", password="hunter2", user_level=10)
        record_session_start(db, alice)
        db.connection.execute(
            """
            CREATE TRIGGER fail_history_visibility_update
            BEFORE UPDATE OF name_visible_fallback ON session_history
            BEGIN
                SELECT RAISE(ABORT, 'forced history update failure');
            END
            """
        )
        db.connection.commit()

        with pytest.raises(sqlite3.IntegrityError):
            set_session_history_name_visible(db, alice, False)

        assert session_history_name_visible(db, alice) is True
        assert list_recent_sessions(db)[0].name_visible_fallback is True
    finally:
        db.close()
