"""Tests for netbbs.signature — per-account signature, auto-appended to
mail and board posts."""

from __future__ import annotations

import pytest

from netbbs.auth.users import create_user
from netbbs.signature import (
    MAX_SIGNATURE_BYTES,
    MAX_SIGNATURE_LINES,
    SignatureError,
    append_signature,
    get_signature,
    has_signature,
    set_signature,
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


def test_get_signature_none_when_unset(db, alice):
    assert get_signature(db, alice) is None


def test_set_then_get_signature(db, alice):
    set_signature(db, alice, "Alice\nVintage computing enthusiast")
    assert get_signature(db, alice) == "Alice\nVintage computing enthusiast"


def test_set_signature_rejects_more_than_max_lines(db, alice):
    too_many = "\n".join(f"line {i}" for i in range(MAX_SIGNATURE_LINES + 1))
    with pytest.raises(SignatureError):
        set_signature(db, alice, too_many)


def test_set_signature_allows_exactly_max_lines(db, alice):
    exactly = "\n".join(f"line {i}" for i in range(MAX_SIGNATURE_LINES))
    set_signature(db, alice, exactly)  # must not raise
    assert get_signature(db, alice) == exactly


def test_set_signature_rejects_over_byte_cap(db, alice):
    with pytest.raises(SignatureError):
        set_signature(db, alice, "x" * (MAX_SIGNATURE_BYTES + 1))


def test_set_signature_allows_exactly_the_byte_cap(db, alice):
    text = "x" * MAX_SIGNATURE_BYTES
    set_signature(db, alice, text)  # must not raise
    assert get_signature(db, alice) == text


def test_set_signature_can_clear_to_empty(db, alice):
    set_signature(db, alice, "Alice")
    set_signature(db, alice, "")
    assert get_signature(db, alice) == ""


def test_has_signature_false_when_unset(db, alice):
    assert has_signature(db, alice) is False


def test_has_signature_false_for_blank_or_whitespace(db, alice):
    set_signature(db, alice, "   ")
    assert has_signature(db, alice) is False


def test_has_signature_true_for_real_content(db, alice):
    set_signature(db, alice, "Alice")
    assert has_signature(db, alice) is True


# -- append_signature ---------------------------------------------------


def test_append_signature_adds_the_standard_delimiter():
    result = append_signature("Hello there.", "Alice")
    assert result == "Hello there.\n-- \nAlice"


def test_append_signature_returns_body_unchanged_when_signature_blank():
    assert append_signature("Hello there.", "") == "Hello there."
    assert append_signature("Hello there.", "   ") == "Hello there."


def test_append_signature_preserves_a_multiline_signature():
    result = append_signature("Body text.", "Alice\nVintage computing enthusiast")
    assert result == "Body text.\n-- \nAlice\nVintage computing enthusiast"


def test_append_signature_is_idempotent_on_an_already_signed_body():
    """A board post's saved-draft/resume cycle can hand back a body that
    already carries the signature (saved mid-review, after a first
    successful append) -- calling append_signature again must not
    duplicate it."""
    once = append_signature("Body text.", "Alice")
    twice = append_signature(once, "Alice")
    assert once == twice == "Body text.\n-- \nAlice"


def test_append_signature_still_appends_when_body_lacks_it():
    """The idempotency check only recognizes an exact, untouched
    trailing match -- a body that never got the signature (e.g. saved
    via /exit before compose ever completed) still gets it appended."""
    body_without_signature = "Body text."
    assert append_signature(body_without_signature, "Alice") == "Body text.\n-- \nAlice"
