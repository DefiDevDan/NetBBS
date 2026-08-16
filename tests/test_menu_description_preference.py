"""Tests for netbbs.net.menu_description_preference, the per-user
menu-description verbosity setting -- mirrors
tests/test_color_depth_preference.py's shape for the analogous
per-user rendering preference."""

from __future__ import annotations

import pytest

from netbbs.auth.users import create_user
from netbbs.net.menu_description_preference import (
    menu_description_level,
    set_menu_description_level,
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


def test_defaults_to_brief(db, alice):
    # Issue #160's own stated goal: descriptions on by default, not an
    # opt-in a caller would need to already know exists.
    assert menu_description_level(db, alice) == "brief"


def test_can_be_set_to_off(db, alice):
    set_menu_description_level(db, alice, "off")
    assert menu_description_level(db, alice) == "off"


def test_can_be_set_to_detailed(db, alice):
    set_menu_description_level(db, alice, "detailed")
    assert menu_description_level(db, alice) == "detailed"


def test_can_be_reset_to_brief(db, alice):
    set_menu_description_level(db, alice, "off")
    set_menu_description_level(db, alice, "brief")
    assert menu_description_level(db, alice) == "brief"


def test_is_per_user(db, alice):
    bob = create_user(db, "bob", password="hunter2", user_level=10)
    set_menu_description_level(db, alice, "off")
    assert menu_description_level(db, alice) == "off"
    assert menu_description_level(db, bob) == "brief"


def test_invalid_value_raises(db, alice):
    with pytest.raises(ValueError):
        set_menu_description_level(db, alice, "verbose")
