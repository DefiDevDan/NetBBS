"""
Tests for the caller-facing [H]istory screen (issue #100) --
`netbbs.net.login_flow._last_sessions_screen`, backed by the persisted
`netbbs.session_history` table (covered at the library level in
tests/test_session_history.py). These drive the real `_main_menu` entry
point and the profile screen's own visibility toggle.
"""

from __future__ import annotations

import asyncio

from netbbs.auth.users import SYSOP_LEVEL, create_user
from netbbs.chat import ChatHub, MessageMailbox, PresenceRegistry
from netbbs.net.char_input import InputHistory
from netbbs.net.login_flow import _main_menu
from netbbs.session_history import (
    reconcile_interrupted_sessions,
    record_session_start,
    session_history_name_visible,
    set_session_history_name_visible,
)
from netbbs.storage.database import Database


class FakeSession:
    def __init__(self, inputs: list[str] | None = None):
        self._inputs = list(inputs or [])
        self.written: list[str] = []
        self.terminal_width = 80
        self.terminal_height = 24
        self.peer_address = "203.0.113.5"
        self.supports_truecolor = False

    async def write(self, text: str) -> None:
        self.written.append(text)

    async def write_line(self, text: str = "") -> None:
        self.written.append(text + "\n")

    async def read_line(self, echo: bool = True, history=None, completer=None) -> str:
        if not self._inputs:
            raise AssertionError("FakeSession ran out of scripted input (read_line)")
        return self._inputs.pop(0)

    async def read_key(self, echo: bool = True) -> str:
        if not self._inputs:
            raise AssertionError("FakeSession ran out of scripted input (read_key)")
        return self._inputs.pop(0)


def _written_text(session: FakeSession) -> str:
    return "".join(session.written)


async def _run_main_menu(session, db, user):
    await _main_menu(session, db, ChatHub(), PresenceRegistry(), MessageMailbox(), InputHistory(), user)


def db_(tmp_path):
    return Database(tmp_path / "node.db")


def test_history_screen_reports_no_sessions_yet(tmp_path):
    database = db_(tmp_path)
    alice = create_user(database, "alice", password="hunter2", user_level=10)
    session = FakeSession(["h", "l", "y"])

    asyncio.run(_run_main_menu(session, database, alice))

    assert "No session history yet." in _written_text(session)
    database.close()


def test_history_screen_shows_a_recorded_session(tmp_path):
    database = db_(tmp_path)
    alice = create_user(database, "alice", password="hunter2", user_level=10)
    bob = create_user(database, "bob", password="hunter2", user_level=10)
    record_session_start(database, bob)

    session = FakeSession(["h", "l", "y"])
    asyncio.run(_run_main_menu(session, database, alice))

    assert "bob" in _written_text(session)
    database.close()


def test_history_screen_shows_still_connected_for_an_open_session(tmp_path):
    database = db_(tmp_path)
    alice = create_user(database, "alice", password="hunter2", user_level=10)
    record_session_start(database, alice)

    session = FakeSession(["h", "l", "y"])
    asyncio.run(_run_main_menu(session, database, alice))

    assert "still connected" in _written_text(session)
    database.close()


def test_history_screen_shows_connection_lost_after_startup_reconciliation(tmp_path):
    """Issue #110's own acceptance criterion: a row left open by a
    process that never reached record_session_end (simulated here by a
    bare record_session_start with no matching end call, then reconciled
    exactly the way netbbs.__main__.run() does at its own startup) must
    never be shown as "still connected" -- it cannot possibly still be,
    across a restart -- but also must not be silently folded into a
    normal clean disconnect."""
    database = db_(tmp_path)
    alice = create_user(database, "alice", password="hunter2", user_level=10)
    bob = create_user(database, "bob", password="hunter2", user_level=10)
    record_session_start(database, bob)  # never ended -- simulates a crash/kill
    reconcile_interrupted_sessions(database)  # what a real restart would run

    session = FakeSession(["h", "l", "y"])
    asyncio.run(_run_main_menu(session, database, alice))

    text = _written_text(session)
    assert "still connected" not in text
    assert "connection lost" in text
    database.close()


def test_history_screen_hides_name_when_target_opted_out(tmp_path):
    database = db_(tmp_path)
    alice = create_user(database, "alice", password="hunter2", user_level=10)
    bob = create_user(database, "bob", password="hunter2", user_level=10)
    set_session_history_name_visible(database, bob, False)
    record_session_start(database, bob)

    session = FakeSession(["h", "l", "y"])
    asyncio.run(_run_main_menu(session, database, alice))

    text = _written_text(session)
    assert "(name hidden)" in text
    assert "bob" not in text
    database.close()


def test_history_screen_sysop_always_sees_real_names(tmp_path):
    """Issue #100's own acceptance criterion: SysOps see real names
    unconditionally, regardless of the target's own opt-out."""
    database = db_(tmp_path)
    sysop = create_user(database, "sysop", password="hunter2", user_level=SYSOP_LEVEL)
    bob = create_user(database, "bob", password="hunter2", user_level=10)
    set_session_history_name_visible(database, bob, False)
    record_session_start(database, bob)

    session = FakeSession(["h", "l", "y"])
    asyncio.run(_run_main_menu(session, database, sysop))

    text = _written_text(session)
    assert "bob" in text
    assert "(name hidden)" not in text
    database.close()


def test_history_screen_shows_denormalized_label_for_a_deleted_account(tmp_path):
    """bob never opted out, so the persisted `name_visible_fallback`
    (issue #111) this row was recorded with is `True` -- the label is
    shown as-is once the account is gone, same observable result as
    before #111, just now via the persisted fallback rather than an
    unconditional "no account, no opt-out possible" shortcut."""
    from netbbs.auth.users import delete_user

    database = db_(tmp_path)
    alice = create_user(database, "alice", password="hunter2", user_level=10)
    sysop = create_user(database, "sysop", password="hunter2", user_level=SYSOP_LEVEL)
    bob = create_user(database, "bob", password="hunter2", user_level=10)
    record_session_start(database, bob)
    delete_user(database, bob, deleted_by=sysop)

    session = FakeSession(["h", "l", "y"])
    asyncio.run(_run_main_menu(session, database, alice))

    assert "bob" in _written_text(session)
    database.close()


def test_history_screen_keeps_a_deleted_accounts_opted_out_name_hidden(tmp_path):
    """Issue #111's own concrete privacy-reversal scenario, reproduced
    end to end through the real screen: bob opts out, a session is
    recorded, the account is deleted -- an ordinary caller must still
    see "(name hidden)", never "bob", in the exact same historical
    entry."""
    from netbbs.auth.users import delete_user

    database = db_(tmp_path)
    alice = create_user(database, "alice", password="hunter2", user_level=10)
    sysop = create_user(database, "sysop", password="hunter2", user_level=SYSOP_LEVEL)
    bob = create_user(database, "bob", password="hunter2", user_level=10)
    set_session_history_name_visible(database, bob, False)
    record_session_start(database, bob)
    delete_user(database, bob, deleted_by=sysop)

    session = FakeSession(["h", "l", "y"])
    asyncio.run(_run_main_menu(session, database, alice))

    text = _written_text(session)
    assert "(name hidden)" in text
    assert "bob" not in text
    database.close()


def test_history_screen_sysop_sees_real_name_even_for_a_deleted_opted_out_account(tmp_path):
    """SysOp administrative visibility (issue #100) is unconditional --
    unaffected by both the target's opt-out and the account's own
    deletion (issue #111 must not accidentally hide names from SysOps
    too, only from ordinary callers)."""
    from netbbs.auth.users import delete_user

    database = db_(tmp_path)
    sysop = create_user(database, "sysop", password="hunter2", user_level=SYSOP_LEVEL)
    bob = create_user(database, "bob", password="hunter2", user_level=10)
    set_session_history_name_visible(database, bob, False)
    record_session_start(database, bob)
    delete_user(database, bob, deleted_by=sysop)

    session = FakeSession(["h", "l", "y"])
    asyncio.run(_run_main_menu(session, database, sysop))

    text = _written_text(session)
    assert "bob" in text
    assert "(name hidden)" not in text
    database.close()


def test_profile_screen_toggles_session_history_name_visibility(tmp_path):
    database = db_(tmp_path)
    alice = create_user(database, "alice", password="hunter2", user_level=10)
    assert session_history_name_visible(database, alice) is True  # default

    session = FakeSession(["p", "h", "b", "l", "y"])
    asyncio.run(_run_main_menu(session, database, alice))

    assert session_history_name_visible(database, alice) is False
    assert "Name in Last sessions is now hidden." in _written_text(session)
    database.close()
