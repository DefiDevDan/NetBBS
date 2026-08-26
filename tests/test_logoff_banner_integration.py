"""Integration tests for the logoff banner (GitHub issue #177) actually
being shown by `netbbs.net.login_flow.run_authenticated_session` on a
clean sign-out -- distinct from tests/test_logoff_banner.py's own
isolated loader/status tests.

Drives a real login-then-logoff round trip via `handle_session`/
`FakeSession`, the same pattern tests/test_login_throttling.py already
uses for its own "log in as alice, then log off" scenario."""

from __future__ import annotations

import asyncio

import pytest

from netbbs.auth.users import create_user
from netbbs.chat import ChatHub, MessageMailbox, PresenceRegistry
from netbbs.net import login_flow
from netbbs.net.logoff_banner import logoff_banner_path, set_logoff_banner_enabled
from netbbs.net.maintenance import MaintenanceMode
from netbbs.net.nodeconfig import ThrottleConfig
from netbbs.net.session_registry import ActiveSessionRegistry
from netbbs.net.throttle import LoginThrottle
from netbbs.storage.database import Database


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "node.db")
    yield database
    database.close()


class FakeSession:
    def __init__(self, lines: list[str] | None = None, keys: list[str] | None = None):
        self._lines = iter(lines or [])
        self._keys = iter(keys or [])
        self.written: list[str] = []
        self.terminal_width = 80
        self.node_display_name = "NetBBS"
        self.node_name_gradient = None
        self.terminal_height = 24
        self.peer_address = "203.0.113.5"
        self.supports_truecolor = False

    async def write(self, text: str) -> None:
        self.written.append(text)

    async def write_line(self, text: str = "") -> None:
        self.written.append(text + "\n")

    async def read_line(self, echo: bool = True) -> str:
        return next(self._lines)

    async def read_key(self, echo: bool = True) -> str:
        return next(self._keys)

    @property
    def output(self) -> str:
        return "".join(self.written)


def _throttle_config(**overrides) -> ThrottleConfig:
    return ThrottleConfig(**overrides)


def _throttle(config: ThrottleConfig) -> LoginThrottle:
    return LoginThrottle(
        per_source_capacity=config.per_source_capacity,
        per_source_refill_per_minute=config.per_source_refill_per_minute,
        per_username_capacity=config.per_username_capacity,
        per_username_refill_per_minute=config.per_username_refill_per_minute,
        global_capacity=config.global_capacity,
        global_refill_per_minute=config.global_refill_per_minute,
        max_tracked_keys=config.max_tracked_keys,
        max_concurrent_unauthenticated_sessions=config.max_concurrent_unauthenticated_sessions,
    )


async def _run_login(session, db, config=None) -> None:
    config = config or _throttle_config()
    throttle = _throttle(config)
    await login_flow.handle_session(
        session, db, ChatHub(), PresenceRegistry(), MessageMailbox(), throttle, config,
        ActiveSessionRegistry(), MaintenanceMode(),
    )


def test_logoff_banner_shown_on_an_intentional_log_off(db):
    create_user(db, "alice", password="hunter2pw", user_level=10)
    logoff_banner_path(db).write_bytes(b"THANKS FOR VISITING")
    set_logoff_banner_enabled(db, True)
    # "n" answers the one-time post-login Unicode-style prompt; "l" then
    # "y" is the "Log off?" confirm (test_login_throttling.py's own
    # established key sequence for this exact round trip).
    session = FakeSession(["alice", "hunter2pw", "n", "y"], keys=["l"])

    asyncio.run(_run_login(session, db))

    assert "THANKS FOR VISITING" in session.output
    assert session.output.index("THANKS FOR VISITING") < session.output.index("Goodbye!")


def test_disabled_logoff_banner_leaves_the_goodbye_message_byte_for_byte_unchanged(db):
    create_user(db, "alice", password="hunter2pw", user_level=10)
    session = FakeSession(["alice", "hunter2pw", "n", "y"], keys=["l"])

    asyncio.run(_run_login(session, db))

    assert "Goodbye!" in session.output


def test_logoff_banner_not_shown_when_login_never_reaches_the_main_menu(db):
    # A failed/abandoned connection never runs the authenticated body at
    # all -- the logoff banner call site is unreachable, not merely
    # skipped.
    logoff_banner_path(db).write_bytes(b"THANKS FOR VISITING")
    set_logoff_banner_enabled(db, True)
    session = FakeSession(["nobody", "wrong-password", "", "", ""])

    asyncio.run(_run_login(session, db, _throttle_config(max_attempts_per_connection=2)))

    assert "THANKS FOR VISITING" not in session.output
