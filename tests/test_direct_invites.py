"""Tests for netbbs.chat.direct_invites -- the mutual invite/accept
handshake behind the direct-chat feature (design doc §6.3)."""

from __future__ import annotations

import asyncio

import pytest

from netbbs.auth.users import create_user
from netbbs.chat.direct_invites import DirectChatInvites
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
def bob(db):
    return create_user(db, "bob", password="hunter2", user_level=10)


def test_send_registers_a_pending_invite(alice):
    async def scenario():
        invites = DirectChatInvites()
        invite = invites.send(alice, "bob-session")
        assert invite is not None
        assert invite.inviter is alice
        assert invites.pending_for("bob-session") is invite

    asyncio.run(scenario())


def test_send_refuses_a_second_invite_to_a_busy_session(alice, bob):
    """Issue's own "busy, already deciding on another invite" rule: a
    session can only ever have one pending invite at a time."""
    async def scenario():
        invites = DirectChatInvites()
        first = invites.send(alice, "bob-session")
        second = invites.send(bob, "bob-session")
        assert first is not None
        assert second is None
        assert invites.pending_for("bob-session") is first

    asyncio.run(scenario())


def test_send_gives_each_invite_a_distinct_room_token(alice, bob):
    async def scenario():
        invites = DirectChatInvites()
        first = invites.send(alice, "bob-session")
        invites.respond("bob-session", accepted=True)
        second = invites.send(bob, "bob-session")
        assert first is not None and second is not None
        assert first.room_token != second.room_token

    asyncio.run(scenario())


def test_respond_accepted_resolves_the_outcome_and_clears_pending(alice):
    async def scenario():
        invites = DirectChatInvites()
        invite = invites.send(alice, "bob-session")
        assert invites.respond("bob-session", accepted=True) is True
        assert await invite.outcome == "accepted"
        assert invites.pending_for("bob-session") is None

    asyncio.run(scenario())


def test_respond_declined_resolves_the_outcome(alice):
    async def scenario():
        invites = DirectChatInvites()
        invite = invites.send(alice, "bob-session")
        assert invites.respond("bob-session", accepted=False) is True
        assert await invite.outcome == "declined"

    asyncio.run(scenario())


def test_respond_is_a_safe_no_op_when_nothing_is_pending():
    invites = DirectChatInvites()
    assert invites.respond("nobody-home", accepted=True) is False


def test_respond_twice_only_the_first_takes_effect(alice):
    """The second respond() call must not raise (asyncio.Future.set_
    result on an already-resolved future would) -- it's a safe no-op,
    same tolerance as everywhere else in this feature."""
    async def scenario():
        invites = DirectChatInvites()
        invites.send(alice, "bob-session")
        assert invites.respond("bob-session", accepted=True) is True
        assert invites.respond("bob-session", accepted=False) is False

    asyncio.run(scenario())


def test_cancel_resolves_the_outcome_as_cancelled(alice):
    async def scenario():
        invites = DirectChatInvites()
        invite = invites.send(alice, "bob-session")
        invites.cancel("bob-session")
        assert await invite.outcome == "cancelled"
        assert invites.pending_for("bob-session") is None

    asyncio.run(scenario())


def test_cancel_is_a_safe_no_op_when_nothing_is_pending():
    invites = DirectChatInvites()
    invites.cancel("nobody-home")  # must not raise


def test_cancel_after_respond_is_a_safe_no_op(alice):
    async def scenario():
        invites = DirectChatInvites()
        invite = invites.send(alice, "bob-session")
        invites.respond("bob-session", accepted=True)
        invites.cancel("bob-session")  # must not raise, must not overwrite the outcome
        assert await invite.outcome == "accepted"

    asyncio.run(scenario())


# -- arrival_event: the mechanism _main_menu's own read/invite race relies on --


def test_arrival_event_is_unset_before_any_invite_exists():
    invites = DirectChatInvites()
    assert not invites.arrival_event("bob-session").is_set()


def test_send_sets_the_arrival_event_for_a_waiter_already_waiting(alice):
    """The live-interrupt case: a waiter blocked on arrival_event()
    *before* any invite exists must wake the moment one arrives."""
    async def scenario():
        invites = DirectChatInvites()
        event = invites.arrival_event("bob-session")
        wait_task = asyncio.create_task(event.wait())
        await asyncio.sleep(0)
        assert not wait_task.done()

        invites.send(alice, "bob-session")
        await asyncio.sleep(0)
        assert wait_task.done()

    asyncio.run(scenario())


def test_arrival_event_stays_set_until_explicitly_cleared(alice):
    """The queued case: a session busy elsewhere the whole time still
    finds the event set whenever it eventually checks."""
    async def scenario():
        invites = DirectChatInvites()
        invites.send(alice, "bob-session")
        # No one was waiting when send() ran -- the event must still be
        # set for a much later check to find.
        assert invites.arrival_event("bob-session").is_set()

        invites.clear_arrival("bob-session")
        assert not invites.arrival_event("bob-session").is_set()

    asyncio.run(scenario())


def test_clear_arrival_is_a_safe_no_op_for_an_unknown_session():
    invites = DirectChatInvites()
    invites.clear_arrival("nobody-home")  # must not raise


def test_arrival_event_is_reused_across_multiple_invites_to_the_same_session(alice, bob):
    """One persistent per-session event, not a fresh one per invite --
    otherwise a waiter started before the *first* invite would never
    notice a *second* one arriving after the first was resolved."""
    async def scenario():
        invites = DirectChatInvites()
        event = invites.arrival_event("bob-session")

        invites.send(alice, "bob-session")
        invites.respond("bob-session", accepted=True)
        invites.clear_arrival("bob-session")
        assert not event.is_set()

        invites.send(bob, "bob-session")
        assert invites.arrival_event("bob-session") is event
        assert event.is_set()

    asyncio.run(scenario())


# -- timeout ------------------------------------------------------------


def test_timeout_resolves_to_timed_out_and_clears_pending(alice, monkeypatch):
    """Short-circuits the real 60s wait via monkeypatching the module's
    own timeout constant -- same dependency-injection-free approach
    `netbbs.net.shutdown`'s own tests use for `loop.call_later`-driven
    behavior, just via the constant here since call_later itself takes
    no injectable clock."""
    import netbbs.chat.direct_invites as direct_invites_module

    monkeypatch.setattr(direct_invites_module, "_INVITE_TIMEOUT_SECONDS", 0.01)

    async def scenario():
        invites = direct_invites_module.DirectChatInvites()
        invite = invites.send(alice, "bob-session")
        assert await asyncio.wait_for(invite.outcome, timeout=2.0) == "timed_out"
        assert invites.pending_for("bob-session") is None

    asyncio.run(scenario())


def test_timeout_never_touches_a_newer_invite_in_the_same_slot(alice, bob, monkeypatch):
    """The ownership guard (issue #107-style): if the first invite is
    answered and a second one takes the same slot before the first
    invite's own timer fires, that stale timer must not touch the new
    invite."""
    import netbbs.chat.direct_invites as direct_invites_module

    async def scenario():
        invites = direct_invites_module.DirectChatInvites()

        monkeypatch.setattr(direct_invites_module, "_INVITE_TIMEOUT_SECONDS", 0.02)
        first = invites.send(alice, "bob-session")
        invites.respond("bob-session", accepted=False)  # resolved well before its own timeout

        # second's own timeout is deliberately much longer than the sleep
        # below -- so it can't legitimately expire on its own, isolating
        # whatever effect first's still-armed stale timer has on it.
        monkeypatch.setattr(direct_invites_module, "_INVITE_TIMEOUT_SECONDS", 10.0)
        second = invites.send(bob, "bob-session")

        await asyncio.sleep(0.1)  # let the first invite's stale timer fire, if it's going to

        assert await first.outcome == "declined"  # unchanged by the stale timer
        assert not second.outcome.done()  # the new invite is untouched
        assert invites.pending_for("bob-session") is second

    asyncio.run(scenario())
