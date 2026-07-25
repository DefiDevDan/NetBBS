"""Tests for netbbs.messaging_preferences -- the direct-message opt-out
preference the caller-facing Who's-online screen honors (issue #99)."""

from __future__ import annotations

import pytest

from netbbs.auth.users import create_user
from netbbs.messaging_preferences import accepts_direct_messages, set_accepts_direct_messages
from netbbs.storage.database import Database


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "node.db")
    yield database
    database.close()


@pytest.fixture
def alice(db):
    return create_user(db, "alice", password="hunter2", user_level=10)


def test_accepts_direct_messages_defaults_to_true(db, alice):
    # Opt-out, not opt-in -- see the module's own docstring for why this
    # is the opposite default from bio visibility.
    assert accepts_direct_messages(db, alice) is True


def test_set_accepts_direct_messages_false(db, alice):
    set_accepts_direct_messages(db, alice, False)
    assert accepts_direct_messages(db, alice) is False


def test_set_accepts_direct_messages_true_after_false(db, alice):
    set_accepts_direct_messages(db, alice, False)
    set_accepts_direct_messages(db, alice, True)
    assert accepts_direct_messages(db, alice) is True
