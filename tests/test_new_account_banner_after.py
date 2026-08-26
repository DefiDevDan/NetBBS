"""Tests for netbbs.net.new_account_banner_after -- the loader/status
functions, in isolation from the netbbs.net.admin_flow UI that will
drive them and the netbbs.net.login_flow/netbbs.net.ssh integration
points (GitHub issue #177).

Mirrors tests/test_main_menu_banner.py's own structure -- same
mechanism, duplicated on purpose (see logoff_banner.py's module
docstring for why) -- no "default banner" variant here either, just "no
banner" (`""`) as the safe fallback."""

from __future__ import annotations

import pytest

from netbbs.net.new_account_banner_after import (
    MAX_NEW_ACCOUNT_BANNER_AFTER_SIZE_BYTES,
    NewAccountBannerAfterStatus,
    is_new_account_banner_after_enabled,
    load_new_account_banner_after,
    new_account_banner_after_path,
    new_account_banner_after_status,
    set_new_account_banner_after_enabled,
)
from netbbs.rendering import RESET
from netbbs.storage.database import Database


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "node.db")
    yield database
    database.close()


# -- new_account_banner_after_path ---------------------------------------


def test_banner_path_is_colocated_with_db_and_named_by_convention(db):
    assert (
        new_account_banner_after_path(db)
        == db.path.parent / f"{db.path.stem}_new_account_banner_after.ans"
    )


def test_banner_path_does_not_auto_create_anything(db):
    assert not new_account_banner_after_path(db).exists()


def test_banner_path_is_independent_of_welcome_banner_path(db):
    from netbbs.net.welcome_banner import banner_path

    assert new_account_banner_after_path(db) != banner_path(db)


def test_banner_path_is_independent_of_before_banner_path(db):
    from netbbs.net.new_account_banner_before import new_account_banner_before_path

    assert new_account_banner_after_path(db) != new_account_banner_before_path(db)


# -- enabled flag ---------------------------------------------------------


def test_disabled_by_default(db):
    assert is_new_account_banner_after_enabled(db) is False


def test_set_enabled_then_read_back(db):
    set_new_account_banner_after_enabled(db, True)
    assert is_new_account_banner_after_enabled(db) is True


def test_set_disabled_after_enabled(db):
    set_new_account_banner_after_enabled(db, True)
    set_new_account_banner_after_enabled(db, False)
    assert is_new_account_banner_after_enabled(db) is False


# -- load_new_account_banner_after -----------------------------------------


def test_disabled_by_default_returns_no_banner(db):
    assert load_new_account_banner_after(db) == ""


def test_enabled_but_file_missing_falls_back_to_no_banner(db):
    set_new_account_banner_after_enabled(db, True)
    assert load_new_account_banner_after(db) == ""


def test_enabled_with_valid_utf8_file_returns_file_content(db):
    new_account_banner_after_path(db).write_bytes("YOU'RE IN, WELCOME ABOARD".encode("utf-8"))
    set_new_account_banner_after_enabled(db, True)
    result = load_new_account_banner_after(db)
    assert "YOU'RE IN, WELCOME ABOARD" in result
    assert result.endswith(RESET)


def test_enabled_with_cp437_file_decodes_correctly(db):
    new_account_banner_after_path(db).write_bytes(bytes([0xB0, 0xB1, 0xB2, 0xDB]))
    set_new_account_banner_after_enabled(db, True)
    result = load_new_account_banner_after(db)
    assert "░▒▓█" in result


def test_oversized_file_falls_back_to_no_banner(db):
    new_account_banner_after_path(db).write_bytes(b"x" * (MAX_NEW_ACCOUNT_BANNER_AFTER_SIZE_BYTES + 1))
    set_new_account_banner_after_enabled(db, True)
    assert load_new_account_banner_after(db) == ""


def test_file_at_exactly_the_size_limit_is_not_rejected(db):
    new_account_banner_after_path(db).write_bytes(b"x" * MAX_NEW_ACCOUNT_BANNER_AFTER_SIZE_BYTES)
    set_new_account_banner_after_enabled(db, True)
    assert load_new_account_banner_after(db) != ""


def test_unreadable_file_falls_back_to_no_banner(db, monkeypatch):
    from pathlib import Path

    new_account_banner_after_path(db).write_bytes(b"custom")
    set_new_account_banner_after_enabled(db, True)

    real_read_bytes = Path.read_bytes

    def _boom(self):
        if self == new_account_banner_after_path(db):
            raise OSError("simulated read failure")
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", _boom)
    assert load_new_account_banner_after(db) == ""


# -- new_account_banner_after_status ---------------------------------------


def test_status_when_disabled_and_missing(db):
    status = new_account_banner_after_status(db)
    assert status == NewAccountBannerAfterStatus(
        enabled=False, path=new_account_banner_after_path(db), exists=False, size_bytes=None
    )


def test_status_when_enabled_and_present(db):
    new_account_banner_after_path(db).write_bytes(b"hello")
    set_new_account_banner_after_enabled(db, True)
    status = new_account_banner_after_status(db)
    assert status.enabled is True
    assert status.exists is True
    assert status.size_bytes == 5


def test_status_does_not_read_file_content(db, monkeypatch):
    from pathlib import Path

    new_account_banner_after_path(db).write_bytes(b"hello")

    def _boom(self):
        raise AssertionError("new_account_banner_after_status must not read file content")

    monkeypatch.setattr(Path, "read_bytes", _boom)
    new_account_banner_after_status(db)  # must not raise
