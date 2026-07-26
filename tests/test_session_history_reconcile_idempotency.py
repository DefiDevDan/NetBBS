"""Regression coverage for interrupted-session reconciliation (#122)."""

from netbbs.auth.users import create_user
from netbbs.session_history import (
    list_recent_sessions,
    reconcile_interrupted_sessions,
    record_session_start,
)
from netbbs.storage.database import Database


def test_reconcile_only_marks_an_interrupted_session_once(tmp_path):
    db = Database(tmp_path / "node.db")
    try:
        alice = create_user(db, "alice", password="hunter2", user_level=10)
        record_session_start(db, alice)

        assert reconcile_interrupted_sessions(db) == 1
        first_timestamp = list_recent_sessions(db)[0].interrupted_at
        assert first_timestamp is not None
        assert reconcile_interrupted_sessions(db) == 0
        assert list_recent_sessions(db)[0].interrupted_at == first_timestamp
    finally:
        db.close()


def test_reconcile_still_marks_a_newer_stale_session(tmp_path):
    db = Database(tmp_path / "node.db")
    try:
        alice = create_user(db, "alice", password="hunter2", user_level=10)
        first_id = record_session_start(db, alice)
        assert reconcile_interrupted_sessions(db) == 1
        first_timestamp = {e.id: e for e in list_recent_sessions(db)}[first_id].interrupted_at

        second_id = record_session_start(db, alice)
        assert reconcile_interrupted_sessions(db) == 1
        entries = {e.id: e for e in list_recent_sessions(db)}
        assert entries[first_id].interrupted_at == first_timestamp
        assert entries[second_id].interrupted_at is not None
    finally:
        db.close()
