"""Regression coverage for bounded direct-chat in-memory state (#119)."""

import asyncio
import gc
import weakref

from netbbs.chat.direct_invites import DirectChatInvites
from netbbs.chat.hub import ChatHub, ParticipantId
from netbbs.net import chat_flow


class _SessionKey:
    pass


def test_arrival_event_does_not_keep_a_disconnected_session_alive():
    invites = DirectChatInvites()
    session = _SessionKey()
    session_ref = weakref.ref(session)

    invites.arrival_event(session)
    assert len(invites._arrival) == 1

    del session
    gc.collect()

    assert session_ref() is None
    assert len(invites._arrival) == 0


def test_completed_synthetic_dm_room_does_not_leave_hub_keys_behind():
    async def scenario():
        hub = ChatHub()
        room = "__dm__:deadbeef"
        first = ParticipantId(username="alice", session_key=1)
        second = ParticipantId(username="bob", session_key=2)

        hub.join(room, first)
        hub.join(room, second)
        await hub.broadcast(room, "hello")
        assert hub.last_activity(room) is None

        hub.leave(room, first)
        assert hub.participant_count(room) == 1
        hub.leave(room, second)

        assert room not in hub._channels
        assert room not in hub._last_activity
        await hub.broadcast(room, object())
        assert room not in hub._channels
        assert room not in hub._last_activity

    asyncio.run(scenario())


def test_ordinary_channel_activity_survives_zero_participant_broadcasts():
    async def scenario():
        hub = ChatHub()
        await hub.broadcast("lobby", "system notice")
        assert hub.last_activity("lobby") is not None

    asyncio.run(scenario())


def test_direct_chat_close_notice_displaces_lossy_traffic_in_a_full_queue():
    async def scenario():
        hub = ChatHub(queue_maxsize=1)
        room = "__dm__:deadbeef"
        alice = ParticipantId(username="alice", session_key=1)
        bob = ParticipantId(username="bob", session_key=2)
        hub.join(room, alice)
        bob_queue = hub.join(room, bob)

        await hub.broadcast(room, "ordinary traffic", exclude={alice})
        assert bob_queue.full()

        await hub.broadcast(
            room,
            chat_flow._DirectChatClosedNotice(),
            exclude={alice},
            priority=True,
        )

        assert isinstance(bob_queue.get_nowait(), chat_flow._DirectChatClosedNotice)

    asyncio.run(scenario())
