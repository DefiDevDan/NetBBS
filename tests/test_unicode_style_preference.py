"""Tests for netbbs.net.unicode_style_preference, the per-user
"Unicode decorative style vs. plain ASCII" setting -- mirrors
tests/test_redraw_preference.py's shape for the analogous per-user
rendering preference."""

from __future__ import annotations

import pytest

from netbbs.auth.users import create_user
from netbbs.net.unicode_style_preference import (
    set_unicode_style_enabled,
    unicode_style_enabled,
    unicode_style_ever_set,
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


def test_defaults_to_on(db, alice):
    # Unlike redraw_preference's off-by-default choice: guessing wrong
    # here risks a few odd glyphs, not real functionality lost, so this
    # matches the codebase's more common "rich default" posture instead.
    assert unicode_style_enabled(db, alice) is True


def test_can_be_disabled(db, alice):
    set_unicode_style_enabled(db, alice, False)
    assert unicode_style_enabled(db, alice) is False


def test_can_be_reenabled(db, alice):
    set_unicode_style_enabled(db, alice, False)
    set_unicode_style_enabled(db, alice, True)
    assert unicode_style_enabled(db, alice) is True


def test_is_per_user(db, alice):
    bob = create_user(db, "bob", password="hunter2", user_level=10)
    set_unicode_style_enabled(db, alice, False)
    assert unicode_style_enabled(db, alice) is False
    assert unicode_style_enabled(db, bob) is True


def test_ever_set_is_false_until_explicitly_touched(db, alice):
    assert unicode_style_ever_set(db, alice) is False


def test_ever_set_is_true_after_setting_even_to_the_default_value(db, alice):
    # The one-time confirmation prompt answering "keep it on" still
    # writes the (unchanged) value -- must count as touched, or the
    # prompt would show again next session.
    set_unicode_style_enabled(db, alice, True)
    assert unicode_style_ever_set(db, alice) is True


def test_ever_set_is_per_user(db, alice):
    bob = create_user(db, "bob", password="hunter2", user_level=10)
    set_unicode_style_enabled(db, alice, False)
    assert unicode_style_ever_set(db, alice) is True
    assert unicode_style_ever_set(db, bob) is False
