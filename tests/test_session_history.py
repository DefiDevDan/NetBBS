"""Tests for netbbs.session_history -- the persisted "last N sessions"
record backing the caller-facing [H]istory screen (issue #100)."""

from __future__ import annotations

import pytest

from netbbs.auth.users import create_user, delete_user
from netbbs.session_history import (
    _MAX_SESSION_HISTORY_ROWS,
    list_recent_sessions,
    record_session_end,
    record_session_start,
    session_history_name_visible,
    set_session_history_name_visible,
)
from netbbs.storage.database import Database


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "node.db")
    yield database
    database.close()


@pytest.fixture
def alice(db):
    return create_user(db, "alice", password="hunter2", user_level=10)


@pytest.fixture
def sysop(db):
    return create_user(db, "sysop", password="hunter2", user_level=255)


def test_record_session_start_creates_a_row_with_no_end_yet(db, alice):
    history_id = record_session_start(db, alice)
    entries = list_recent_sessions(db)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.id == history_id
    assert entry.user_id == alice.id
    assert entry.username_label == "alice"
    assert entry.connected_at
    assert entry.disconnected_at is None


def test_record_session_end_fills_in_disconnected_at(db, alice):
    history_id = record_session_start(db, alice)
    record_session_end(db, history_id)
    entry = list_recent_sessions(db)[0]
    assert entry.disconnected_at is not None


def test_record_session_end_on_a_pruned_id_is_a_silent_no_op(db, alice):
    # Doesn't correspond to any real row -- must not raise.
    record_session_end(db, 999999)


def test_list_recent_sessions_most_recent_first(db, alice):
    first = record_session_start(db, alice)
    second = record_session_start(db, alice)
    entries = list_recent_sessions(db)
    assert [e.id for e in entries] == [second, first]


def test_list_recent_sessions_respects_limit(db, alice):
    for _ in range(5):
        record_session_start(db, alice)
    assert len(list_recent_sessions(db, limit=2)) == 2


def test_row_count_pruning_keeps_only_the_most_recent_rows(db, alice):
    # +5 over the cap -- confirms pruning actually removes the oldest
    # ones rather than merely capping list_recent_sessions's own read.
    for _ in range(_MAX_SESSION_HISTORY_ROWS + 5):
        record_session_start(db, alice)
    total = db.connection.execute("SELECT COUNT(*) AS n FROM session_history").fetchone()["n"]
    assert total == _MAX_SESSION_HISTORY_ROWS


def test_deleting_the_account_sets_user_id_null_but_keeps_the_row_and_label(db, alice, sysop):
    record_session_start(db, alice)
    delete_user(db, alice, deleted_by=sysop)
    entries = list_recent_sessions(db)
    assert len(entries) == 1
    assert entries[0].user_id is None
    assert entries[0].username_label == "alice"  # denormalized -- survives the delete


# -- session_history_name_visible --------------------------------------


def test_name_visible_defaults_to_true(db, alice):
    assert session_history_name_visible(db, alice) is True


def test_set_name_visible_false(db, alice):
    set_session_history_name_visible(db, alice, False)
    assert session_history_name_visible(db, alice) is False


def test_set_name_visible_true_after_false(db, alice):
    set_session_history_name_visible(db, alice, False)
    set_session_history_name_visible(db, alice, True)
    assert session_history_name_visible(db, alice) is True
