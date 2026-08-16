"""
Integration tests for `netbbs.link.realtime_channels` (design doc
§8.10.2, issue #148's first vertical) -- real loopback-socket Noise
sessions between two nodes, exercising the full path from a subscribe
request through to a locally-connected `ChatHub` participant actually
receiving a rendered live message/presence event.
"""

from __future__ import annotations

import asyncio

from netbbs.auth.users import create_user
from netbbs.chat.channels import create_channel
from netbbs.chat.hub import ChatHub, ParticipantId
from netbbs.chat.scrollback import record_message
from netbbs.link.channels import link_channel, materialize_carried_channel
from netbbs.link.node_identity import bootstrap_node_identity
from netbbs.link.protocol import LinkNode, RealtimeFrame, build_subscribe_frame
from netbbs.link.realtime_channels import LiveChannelBridge, ensure_live_subscription
from netbbs.link.trust import TrustDimension, TrustState, TrustSubject, set_trust_override
from netbbs.link.enforcement import ensure_node_subject
from netbbs.link.transport import (
    LINK_REALTIME_PROTOCOL_TAG,
    LinkRealtimeServer,
    LinkRealtimeSessionRegistry,
    dial_realtime_session,
)
from netbbs.storage.database import Database
from netbbs.storage.execution import DatabaseLane
from netbbs.timeutil import utc_now_iso


class _Node:
    """One node's full test rig: db/lane, identity, chat hub, real-time
    session registry, and live-channel bridge -- everything `LiveChannel
    Bridge`/`ensure_live_subscription` need, bundled the way a running
    node would actually hold them."""

    def __init__(self, tmp_path, name: str) -> None:
        self.db = Database(tmp_path / f"{name}.db")
        self.lane = DatabaseLane(self.db.path)
        self.identity = bootstrap_node_identity(name)
        self.hub = ChatHub()
        self.registry = LinkRealtimeSessionRegistry(own_fingerprint=self.identity.fingerprint)
        self.bridge = LiveChannelBridge(hub=self.hub, lane=self.lane)
        self.link_node = LinkNode(identity=self.identity)

    async def teardown(self) -> None:
        await self.registry.close_all(reason="test_done")
        await self.bridge.close()
        self.lane.close()
        self.db.close()


async def _wait_until(predicate, *, timeout: float = 2.0, interval: float = 0.02) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


def _establish_trust(db: Database, fingerprint: str) -> None:
    """A freshly-seen node subject defaults to `PROBATIONARY` (design
    doc §14/§4), which `LinkPolicyAction.REALTIME` never allows -- tests
    exercising the authorized happy path pre-establish trust the same
    way an operator's own vouching/reputation accrual would, mirroring
    `test_link_transport.py`'s existing quarantine-test setup exactly."""
    ensure_node_subject(db, fingerprint)
    subject = TrustSubject.node(fingerprint)
    for dimension in (TrustDimension.IDENTITY_INTEGRITY, TrustDimension.RESOURCE_BEHAVIOR):
        set_trust_override(
            db, subject, dimension, TrustState.ESTABLISHED,
            reason="pre-established for test", now_iso="2026-08-14T12:00:00+00:00",
        )


def _setup_linked_channel(origin: _Node, subscriber: _Node, *, name: str = "lobby"):
    """Create+Link a channel on `origin`, materialize the identical
    carried copy on `subscriber` -- the same relationship async catch-up
    already establishes, standing in for it here without a real
    HTTP hello/events round trip. Returns `(origin_channel,
    subscriber_channel)` -- same `channel_id`, independent local rows."""
    creator = create_user(origin.db, f"{name}-creator", password="hunter2", user_level=10)
    origin_channel = create_channel(origin.db, name, creator=creator)
    genesis = link_channel(origin.db, origin_channel, node_identity=origin.identity)
    subscriber_channel = materialize_carried_channel(subscriber.db, genesis)
    return origin_channel, subscriber_channel


def test_ensure_live_subscription_dials_the_origin_and_registers_the_subscription(tmp_path):
    async def scenario():
        origin = _Node(tmp_path, "origin-dial")
        subscriber = _Node(tmp_path, "subscriber-dial")
        origin_channel, subscriber_channel = _setup_linked_channel(origin, subscriber, name="dial-room")

        server = LinkRealtimeServer(
            host="127.0.0.1", port=0, identity=origin.identity, registry=origin.registry,
            on_frame=origin.bridge.on_frame, lane=origin.lane, enforce_trust_policy=True,
        )
        await server.start()
        try:
            _establish_trust(origin.db, subscriber.identity.fingerprint)
            _establish_trust(subscriber.db, origin.identity.fingerprint)
            # In-memory hello (LinkNode.handle_hello is transport-agnostic,
            # no socket needed) giving the subscriber a verified peer
            # record for origin advertising the real-time port just opened.
            origin_hello = origin.link_node.build_hello(
                addresses=[
                    {"protocol": LINK_REALTIME_PROTOCOL_TAG, "address": "127.0.0.1", "port": server.port}
                ],
                outgoing_only=False, created_at=utc_now_iso(),
            )
            subscriber.link_node.handle_hello(origin_hello)

            session = await ensure_live_subscription(
                channel=subscriber_channel, node_identity=subscriber.identity, link_node=subscriber.link_node,
                lane=subscriber.lane, registry=subscriber.registry, bridge=subscriber.bridge,
            )

            assert session is not None
            assert subscriber.registry.get(origin.identity.fingerprint) is session
            assert await _wait_until(lambda: origin_channel.channel_id in origin.bridge._subscribers)
        finally:
            await server.stop()
            await origin.teardown()
            await subscriber.teardown()

    asyncio.run(scenario())


def test_ensure_live_subscription_is_a_harmless_no_op_for_an_unlinked_channel(tmp_path):
    async def scenario():
        subscriber = _Node(tmp_path, "subscriber-unlinked")
        creator = create_user(subscriber.db, "unlinked-creator", password="hunter2", user_level=10)
        channel = create_channel(subscriber.db, "not-linked", creator=creator)
        try:
            session = await ensure_live_subscription(
                channel=channel, node_identity=subscriber.identity, link_node=subscriber.link_node,
                lane=subscriber.lane, registry=subscriber.registry, bridge=subscriber.bridge,
            )
            assert session is None
        finally:
            await subscriber.teardown()

    asyncio.run(scenario())


def test_live_channel_message_and_presence_reach_a_locally_connected_participant(tmp_path):
    async def scenario():
        origin = _Node(tmp_path, "origin-live")
        subscriber = _Node(tmp_path, "subscriber-live")
        origin_channel, subscriber_channel = _setup_linked_channel(origin, subscriber, name="townsquare")

        server = LinkRealtimeServer(
            host="127.0.0.1", port=0, identity=origin.identity, registry=origin.registry,
            on_frame=origin.bridge.on_frame, lane=origin.lane, enforce_trust_policy=True,
        )
        await server.start()
        try:
            _establish_trust(origin.db, subscriber.identity.fingerprint)
            # Subscriber's own `_handle_channel_message`/`_handle_presence_
            # delta` re-check authorization against *its own* db for the
            # sending peer (origin) on every delivered frame -- needs
            # origin trusted there too, not just origin trusting subscriber.
            _establish_trust(subscriber.db, origin.identity.fingerprint)
            session = await dial_realtime_session(
                "127.0.0.1", server.port, subscriber.identity, on_frame=subscriber.bridge.on_frame,
                registry=subscriber.registry,
            )
            subscriber.bridge.track_session(session)
            await session.send(build_subscribe_frame(subscriber_channel.channel_id))
            assert await _wait_until(lambda: origin_channel.channel_id in origin.bridge._subscribers)

            # A local caller on the *subscriber* node is watching this
            # linked channel -- register it with the hub exactly like a
            # real chat session's join already does.
            participant = ParticipantId(username="localwatcher", session_key=1)
            queue = subscriber.hub.join(subscriber_channel.name, participant)

            # Origin's own local user posts a message -- pushed live to
            # subscribers, the same call a real chat send loop makes.
            origin_user = create_user(origin.db, "origin-speaker", password="hunter2", user_level=10)
            recorded = record_message(
                origin.db, origin_channel, kind="message", author_label=origin_user.username,
                author_fingerprint=origin_user.fingerprint, body="hello from origin",
            )
            await origin.bridge.broadcast_local_message_live(origin_channel, recorded)

            delivered = await asyncio.wait_for(queue.get(), timeout=2.0)
            assert delivered.kind == "message"
            assert delivered.body == "hello from origin"
            assert delivered.author_label == f"origin-speaker@{origin.identity.fingerprint}"
            assert delivered.author_fingerprint is None  # never treated as locally verified

            await origin.bridge.broadcast_local_presence_live(
                origin_channel, change="join", username="origin-speaker"
            )
            presence_event = await asyncio.wait_for(queue.get(), timeout=2.0)
            assert presence_event.kind == "join"
            assert presence_event.author_label == f"origin-speaker@{origin.identity.fingerprint}"

            # Never persisted -- live delivery stays purely in-memory.
            assert origin.db.connection.execute(
                "SELECT COUNT(*) FROM channel_messages WHERE body = 'hello from origin'"
            ).fetchone()[0] == 1  # origin's own record_message call above, not a second copy
        finally:
            await server.stop()
            await origin.teardown()
            await subscriber.teardown()

    asyncio.run(scenario())


def test_subscribe_to_an_unlinked_channel_is_rejected_without_registering_a_subscription(tmp_path):
    async def scenario():
        origin = _Node(tmp_path, "origin-reject")
        subscriber = _Node(tmp_path, "subscriber-reject")
        creator = create_user(origin.db, "reject-creator", password="hunter2", user_level=10)
        create_channel(origin.db, "private-room", creator=creator)  # exists locally, never Linked

        received_errors: list[RealtimeFrame] = []

        async def on_frame_subscriber(session, frame):
            if frame.type == "error":
                received_errors.append(frame)

        server = LinkRealtimeServer(
            host="127.0.0.1", port=0, identity=origin.identity, registry=origin.registry,
            on_frame=origin.bridge.on_frame, lane=origin.lane, enforce_trust_policy=True,
        )
        await server.start()
        try:
            _establish_trust(origin.db, subscriber.identity.fingerprint)
            session = await dial_realtime_session(
                "127.0.0.1", server.port, subscriber.identity, on_frame=on_frame_subscriber,
                registry=subscriber.registry,
            )
            await session.send(build_subscribe_frame("nonexistent-channel-id"))
            assert await _wait_until(lambda: len(received_errors) == 1)
            assert origin.bridge._subscribers == {}
            assert session.closed.is_set() is False  # one rejection is a strike, not a hard close
        finally:
            await server.stop()
            await origin.teardown()
            await subscriber.teardown()

    asyncio.run(scenario())


def test_a_quarantined_subscriber_stops_receiving_further_live_messages(tmp_path):
    async def scenario():
        origin = _Node(tmp_path, "origin-quarantine")
        subscriber = _Node(tmp_path, "subscriber-quarantine")
        origin_channel, subscriber_channel = _setup_linked_channel(origin, subscriber, name="watched-room")

        server = LinkRealtimeServer(
            host="127.0.0.1", port=0, identity=origin.identity, registry=origin.registry,
            on_frame=origin.bridge.on_frame, lane=origin.lane, enforce_trust_policy=True,
        )
        await server.start()
        try:
            _establish_trust(origin.db, subscriber.identity.fingerprint)
            session = await dial_realtime_session(
                "127.0.0.1", server.port, subscriber.identity, on_frame=subscriber.bridge.on_frame,
                registry=subscriber.registry,
            )
            await session.send(build_subscribe_frame(subscriber_channel.channel_id))
            assert await _wait_until(lambda: origin_channel.channel_id in origin.bridge._subscribers)

            participant = ParticipantId(username="localwatcher", session_key=1)
            queue = subscriber.hub.join(subscriber_channel.name, participant)

            subject = TrustSubject.node(subscriber.identity.fingerprint)
            ensure_node_subject(origin.db, subscriber.identity.fingerprint)
            set_trust_override(
                origin.db, subject, TrustDimension.RESOURCE_BEHAVIOR, TrustState.QUARANTINED,
                reason="quarantined mid-session for test", now_iso="2026-08-14T12:01:00+00:00",
            )

            origin_user = create_user(origin.db, "origin-speaker-q", password="hunter2", user_level=10)
            recorded = record_message(
                origin.db, origin_channel, kind="message", author_label=origin_user.username,
                author_fingerprint=origin_user.fingerprint, body="should never arrive",
            )
            await origin.bridge.broadcast_local_message_live(origin_channel, recorded)

            assert queue.empty()
            assert origin_channel.channel_id not in origin.bridge._subscribers
        finally:
            await server.stop()
            await origin.teardown()
            await subscriber.teardown()

    asyncio.run(scenario())


def test_disconnect_without_unsubscribe_is_purged_by_the_watcher(tmp_path):
    async def scenario():
        origin = _Node(tmp_path, "origin-disconnect")
        subscriber = _Node(tmp_path, "subscriber-disconnect")
        origin_channel, subscriber_channel = _setup_linked_channel(origin, subscriber, name="fickle-room")

        server = LinkRealtimeServer(
            host="127.0.0.1", port=0, identity=origin.identity, registry=origin.registry,
            on_frame=origin.bridge.on_frame, lane=origin.lane, enforce_trust_policy=True,
        )
        await server.start()
        try:
            _establish_trust(origin.db, subscriber.identity.fingerprint)
            session = await dial_realtime_session(
                "127.0.0.1", server.port, subscriber.identity, on_frame=subscriber.bridge.on_frame,
                registry=subscriber.registry,
            )
            await session.send(build_subscribe_frame(subscriber_channel.channel_id))
            assert await _wait_until(lambda: origin_channel.channel_id in origin.bridge._subscribers)

            await session.close(reason="test_forced_disconnect")

            assert await _wait_until(lambda: origin_channel.channel_id not in origin.bridge._subscribers)
        finally:
            await server.stop()
            await origin.teardown()
            await subscriber.teardown()

    asyncio.run(scenario())


def test_local_interest_reference_counts_holders_per_channel():
    """Issue #159: `register_local_interest`/`release_local_interest`
    are the subscriber-side mirror of `_subscribers` above (which tracks
    the *origin*-side "who subscribes to my channels"). Plain in-memory
    bookkeeping, no I/O -- covered directly rather than only through the
    full `_chat_loop` integration test in `test_chat_flow_link.py`."""
    bridge = LiveChannelBridge(hub=ChatHub(), lane=None)
    alice_holder, bob_holder = 1, 2

    # First registration for a channel is reported as such; a second,
    # different holder for the *same* channel is not -- someone else
    # already established local interest.
    assert bridge.register_local_interest("channel-a", alice_holder) is True
    assert bridge.register_local_interest("channel-a", bob_holder) is False

    # Registering the same holder twice (e.g. a caller re-entering the
    # same channel view) is idempotent, not a second holder.
    assert bridge.register_local_interest("channel-a", alice_holder) is False

    # Releasing one of two holders is never "the last" -- the other is
    # still relying on the same feed.
    assert bridge.release_local_interest("channel-a", alice_holder) is False
    # Releasing an already-released (or never-registered) holder is a
    # safe no-op, not an error and not falsely "the last."
    assert bridge.release_local_interest("channel-a", alice_holder) is False
    assert bridge.release_local_interest("channel-a", 999) is False

    # The one remaining holder leaving is genuinely the last.
    assert bridge.release_local_interest("channel-a", bob_holder) is True
    # A channel with zero holders left releases its own bookkeeping
    # entirely, so the next registration is a fresh "first" again --
    # this and the two independent channels below both prove holder
    # state never leaks across different channel_ids.
    assert bridge.register_local_interest("channel-a", alice_holder) is True
    assert bridge.register_local_interest("channel-b", alice_holder) is True
