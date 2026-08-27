"""Tests for netbbs.net.board_list_banner -- the loader/status functions,
in isolation from the netbbs.net.admin_flow UI that will drive them and
the netbbs.net.login_flow integration point (GitHub issue #176).

Mirrors tests/test_main_menu_banner.py's own structure -- same mechanism,
duplicated on purpose (see board_list_banner.py's module docstring) --
no "default banner" variant here either, just "no masthead" (`""`) as
the safe fallback."""

from __future__ import annotations

import pytest

from netbbs.net.board_list_banner import (
    MAX_BOARD_LIST_BANNER_SIZE_BYTES,
    BoardListBannerStatus,
    board_list_banner_path,
    board_list_banner_status,
    is_board_list_banner_enabled,
    load_board_list_banner,
    set_board_list_banner_enabled,
)
from netbbs.rendering import RESET
from netbbs.storage.database import Database


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "node.db")
    yield database
    database.close()


# -- board_list_banner_path ----------------------------------------------


def test_banner_path_is_colocated_with_db_and_named_by_convention(db):
    assert board_list_banner_path(db) == db.path.parent / f"{db.path.stem}_board_list_banner.ans"


def test_banner_path_does_not_auto_create_anything(db):
    assert not board_list_banner_path(db).exists()


def test_banner_path_is_independent_of_welcome_banner_path(db):
    from netbbs.net.welcome_banner import banner_path

    assert board_list_banner_path(db) != banner_path(db)


# -- enabled flag ---------------------------------------------------------


def test_disabled_by_default(db):
    assert is_board_list_banner_enabled(db) is False


def test_set_enabled_then_read_back(db):
    set_board_list_banner_enabled(db, True)
    assert is_board_list_banner_enabled(db) is True


def test_set_disabled_after_enabled(db):
    set_board_list_banner_enabled(db, True)
    set_board_list_banner_enabled(db, False)
    assert is_board_list_banner_enabled(db) is False


# -- load_board_list_banner -------------------------------------------------


def test_disabled_by_default_returns_no_masthead(db):
    assert load_board_list_banner(db) == ""


def test_enabled_but_file_missing_falls_back_to_no_masthead(db):
    set_board_list_banner_enabled(db, True)
    assert load_board_list_banner(db) == ""


def test_enabled_with_valid_utf8_file_returns_file_content(db):
    board_list_banner_path(db).write_bytes("MY CUSTOM BOARD MASTHEAD".encode("utf-8"))
    set_board_list_banner_enabled(db, True)
    result = load_board_list_banner(db)
    assert "MY CUSTOM BOARD MASTHEAD" in result
    assert result.endswith(RESET)


def test_enabled_with_cp437_file_decodes_correctly(db):
    board_list_banner_path(db).write_bytes(bytes([0xB0, 0xB1, 0xB2, 0xDB]))
    set_board_list_banner_enabled(db, True)
    result = load_board_list_banner(db)
    assert "░▒▓█" in result


def test_oversized_file_falls_back_to_no_masthead(db):
    board_list_banner_path(db).write_bytes(b"x" * (MAX_BOARD_LIST_BANNER_SIZE_BYTES + 1))
    set_board_list_banner_enabled(db, True)
    assert load_board_list_banner(db) == ""


def test_file_at_exactly_the_size_limit_is_not_rejected(db):
    board_list_banner_path(db).write_bytes(b"x" * MAX_BOARD_LIST_BANNER_SIZE_BYTES)
    set_board_list_banner_enabled(db, True)
    assert load_board_list_banner(db) != ""


def test_unreadable_file_falls_back_to_no_masthead(db, monkeypatch):
    from pathlib import Path

    board_list_banner_path(db).write_bytes(b"custom")
    set_board_list_banner_enabled(db, True)

    real_read_bytes = Path.read_bytes

    def _boom(self):
        if self == board_list_banner_path(db):
            raise OSError("simulated read failure")
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", _boom)
    assert load_board_list_banner(db) == ""


# -- board_list_banner_status -----------------------------------------------


def test_status_when_disabled_and_missing(db):
    status = board_list_banner_status(db)
    assert status == BoardListBannerStatus(
        enabled=False, path=board_list_banner_path(db), exists=False, size_bytes=None
    )


def test_status_when_enabled_and_present(db):
    board_list_banner_path(db).write_bytes(b"hello")
    set_board_list_banner_enabled(db, True)
    status = board_list_banner_status(db)
    assert status.enabled is True
    assert status.exists is True
    assert status.size_bytes == 5


def test_status_does_not_read_file_content(db, monkeypatch):
    from pathlib import Path

    board_list_banner_path(db).write_bytes(b"hello")

    def _boom(self):
        raise AssertionError("board_list_banner_status must not read file content")

    monkeypatch.setattr(Path, "read_bytes", _boom)
    board_list_banner_status(db)  # must not raise
