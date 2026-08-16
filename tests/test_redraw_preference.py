"""Tests for netbbs.net.redraw_preference, the per-user "clear the
terminal on redraw instead of scrolling" setting -- mirrors
tests/test_menu_description_preference.py's shape for the analogous
per-user rendering preference."""

from __future__ import annotations

import pytest

from netbbs.auth.users import create_user
from netbbs.net.redraw_preference import (
    redraw_in_place_enabled,
    redraw_in_place_ever_set,
    set_redraw_in_place_enabled,
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


def test_defaults_to_off(db, alice):
    # Unlike menu_description_level's "on by default", this trades away
    # scrollback continuity -- a real behavior change every existing
    # account should opt into, not wake up to.
    assert redraw_in_place_enabled(db, alice) is False


def test_can_be_enabled(db, alice):
    set_redraw_in_place_enabled(db, alice, True)
    assert redraw_in_place_enabled(db, alice) is True


def test_can_be_disabled_again(db, alice):
    set_redraw_in_place_enabled(db, alice, True)
    set_redraw_in_place_enabled(db, alice, False)
    assert redraw_in_place_enabled(db, alice) is False


def test_is_per_user(db, alice):
    bob = create_user(db, "bob", password="hunter2", user_level=10)
    set_redraw_in_place_enabled(db, alice, True)
    assert redraw_in_place_enabled(db, alice) is True
    assert redraw_in_place_enabled(db, bob) is False


def test_ever_set_is_false_until_explicitly_touched(db, alice):
    assert redraw_in_place_ever_set(db, alice) is False


def test_ever_set_is_true_after_setting_even_to_the_default_value(db, alice):
    # The whole point of this function: distinguish "never touched"
    # from "touched, and happened to choose off" -- setting it to its
    # own default value must still count as touched, or the one-time
    # contextual hint would show forever for an account that explicitly
    # chose to leave it off.
    set_redraw_in_place_enabled(db, alice, False)
    assert redraw_in_place_ever_set(db, alice) is True


def test_ever_set_is_per_user(db, alice):
    bob = create_user(db, "bob", password="hunter2", user_level=10)
    set_redraw_in_place_enabled(db, alice, True)
    assert redraw_in_place_ever_set(db, alice) is True
    assert redraw_in_place_ever_set(db, bob) is False
