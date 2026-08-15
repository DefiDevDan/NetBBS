"""
Live linked-channel chat bridge (design doc §8.10.2, issue #148's first
vertical) -- the seam between `netbbs.link.transport`'s Noise session
layer (which knows nothing about channels) and `netbbs.chat`'s local
domain state (which knows nothing about Link).

`LiveChannelBridge` is one instance per running node, shared by every
`LinkRealtimeSession` this node holds in either direction (the same
`on_frame` callback goes to `LinkRealtimeServer`, `dial_realtime_
session`, and `LinkRealtimeConnector` alike). It owns exactly the state
a bare session doesn't know about: which peer sessions are currently
subscribed to which of *this node's own* channels. Inbound frames turn
into the same `netbbs.chat.hub.ChatHub` broadcast a local participant's
own message/join/leave already produces -- a remote live event renders
through the exact same path (`_render_channel_message`) scrollback
replay does, per that renderer's own docstring (GitHub issue #64). This
module never touches `channel_messages`/scrollback itself: a live frame
is ephemeral by design (§8.10), never a substitute for the durable
async `channel_message` event `netbbs.link.channels.queue_channel_
message_if_linked` already queues separately.

Deliberately does not decide *when* to dial a peer on its own --
`ensure_live_subscription` is a plain function a caller (a channel-join
flow) invokes; nothing here runs a background connector loop.
"""

from __future__ import annotations

import asyncio

from netbbs.chat.channels import Channel
from netbbs.chat.hub import ChatHub
from netbbs.chat.scrollback import ChannelMessage as LocalChannelMessage
from netbbs.link.channels import channel_origin_fingerprint, get_channel_by_channel_id, is_channel_linked
from netbbs.link.enforcement import LinkPolicyAction, decide_node_action, ensure_node_subject
from netbbs.link.node_identity import NodeIdentity
from netbbs.link.protocol import (
    LinkNode,
    LinkProtocolError,
    RealtimeFrame,
    build_channel_message_frame,
    build_presence_delta_frame,
    build_presence_snapshot_frame,
    build_subscribe_frame,
)
from netbbs.link.transport import (
    LinkRealtimeSession,
    LinkRealtimeSessionRegistry,
    LinkTransportError,
    dial_realtime_session,
    dialable_realtime_addresses_for_peer,
)
from netbbs.storage.database import Database
from netbbs.storage.execution import DatabaseLane
from netbbs.timeutil import utc_now_iso

# design doc §8.10.1: "Subscriptions, remote presence entries ... are
# bounded per peer and node."
_MAX_SUBSCRIBERS_PER_CHANNEL = 200
_MAX_PRESENCE_SNAPSHOT_ENTRIES = 200


def _decide_channel_subscribe_authorization(db: Database, *, channel_id: str, peer_fingerprint: str) -> Channel:
    """Design doc §8.10.2: "checks that the channel exists, is linked,
    is locally allowed by trust policy, and is available to the
    subscribing peer" -- called again on every delivered message, not
    only at subscribe time, since a subscription is not a permanent
    grant. Raises `LinkProtocolError` (a bounded strike at the session
    layer, not a hard close -- see `LinkRealtimeSession._reader_loop`)
    for any failure, deliberately without distinguishing which reason
    applies: none of "unknown channel," "not linked," or "not trusted"
    are anything a rejected peer needs to be told apart."""
    channel = get_channel_by_channel_id(db, channel_id)
    if channel is None or not is_channel_linked(db, channel):
        raise LinkProtocolError(f"channel {channel_id!r} is not a linked channel this node carries")
    ensure_node_subject(db, peer_fingerprint)
    if not decide_node_action(db, peer_fingerprint, LinkPolicyAction.REALTIME).allowed:
        raise LinkProtocolError(f"node {peer_fingerprint!r} is not currently allowed real-time traffic")
    return channel


class LiveChannelBridge:
    """See module docstring. `hub`/`lane` are this node's own
    already-running singletons (one `ChatHub`, one `DatabaseLane`) --
    this class adds no storage or broadcast mechanism of its own."""

    def __init__(self, *, hub: ChatHub, lane: DatabaseLane) -> None:
        self._hub = hub
        self._lane = lane
        # channel_id -> {peer_fingerprint: session}
        self._subscribers: dict[str, dict[str, LinkRealtimeSession]] = {}
        self._watchers: set[asyncio.Task] = set()

    def track_session(self, session: LinkRealtimeSession) -> None:
        """Spawn the bounded (one per session) watcher that purges
        `session` from every channel's subscriber set once it closes --
        a peer that disconnects without unsubscribing must not linger
        as a phantom subscriber forever. Safe to call more than once for
        the same session (a no-op watcher only ever removes what it
        finds)."""
        watcher = asyncio.get_running_loop().create_task(self._untrack_on_close(session))
        self._watchers.add(watcher)
        watcher.add_done_callback(self._watchers.discard)

    async def _untrack_on_close(self, session: LinkRealtimeSession) -> None:
        await session.closed.wait()
        for channel_id, subscribers in list(self._subscribers.items()):
            if subscribers.pop(session.remote_fingerprint, None) is not None and not subscribers:
                del self._subscribers[channel_id]

    async def close(self) -> None:
        if self._watchers:
            await asyncio.gather(*self._watchers, return_exceptions=True)

    async def on_frame(self, session: LinkRealtimeSession, frame: RealtimeFrame) -> None:
        if frame.type == "subscribe":
            await self._handle_subscribe(session, frame)
        elif frame.type == "unsubscribe":
            self._handle_unsubscribe(session, frame)
        elif frame.type == "channel_message":
            await self._handle_channel_message(session, frame)
        elif frame.type == "presence_delta":
            await self._handle_presence_delta(session, frame)
        elif frame.type == "presence_snapshot":
            await self._handle_presence_snapshot(session, frame)
        # "error": nothing actionable locally yet from a peer-reported
        # rejection of a frame this node sent.

    async def _handle_subscribe(self, session: LinkRealtimeSession, frame: RealtimeFrame) -> None:
        channel_id = frame.payload["channel_id"]
        channel = await self._lane.run(
            _decide_channel_subscribe_authorization, channel_id=channel_id,
            peer_fingerprint=session.remote_fingerprint,
        )
        subscribers = self._subscribers.setdefault(channel_id, {})
        if session.remote_fingerprint not in subscribers and len(subscribers) >= _MAX_SUBSCRIBERS_PER_CHANNEL:
            raise LinkProtocolError(f"channel {channel_id!r} is already at its live-subscriber limit")
        subscribers[session.remote_fingerprint] = session
        self.track_session(session)

        seen_usernames: set[str] = set()
        entries = []
        for participant in self._hub.participant_ids(channel.name):
            if participant.username in seen_usernames:
                continue
            seen_usernames.add(participant.username)
            entries.append({"user_id": participant.username, "display_label": participant.username})
        await session.send(
            build_presence_snapshot_frame(channel_id, entries[:_MAX_PRESENCE_SNAPSHOT_ENTRIES])
        )

    def _handle_unsubscribe(self, session: LinkRealtimeSession, frame: RealtimeFrame) -> None:
        channel_id = frame.payload["channel_id"]
        subscribers = self._subscribers.get(channel_id)
        if subscribers is None:
            return
        subscribers.pop(session.remote_fingerprint, None)
        if not subscribers:
            del self._subscribers[channel_id]

    async def _handle_channel_message(self, session: LinkRealtimeSession, frame: RealtimeFrame) -> None:
        channel = await self._lane.run(
            _decide_channel_subscribe_authorization, channel_id=frame.payload["channel_id"],
            peer_fingerprint=session.remote_fingerprint,
        )
        message = LocalChannelMessage(
            id=-1, channel_id=channel.id, kind="message",
            author_label=f"{frame.payload['user_id']}@{session.remote_fingerprint}",
            author_fingerprint=None, body=frame.payload["body"], created_at=frame.payload["created_at"],
        )
        await self._hub.broadcast(channel.name, message)

    async def _handle_presence_delta(self, session: LinkRealtimeSession, frame: RealtimeFrame) -> None:
        channel = await self._lane.run(
            _decide_channel_subscribe_authorization, channel_id=frame.payload["channel_id"],
            peer_fingerprint=session.remote_fingerprint,
        )
        kind = "join" if frame.payload["change"] == "join" else "leave"
        message = LocalChannelMessage(
            id=-1, channel_id=channel.id, kind=kind,
            author_label=f"{frame.payload['user_id']}@{session.remote_fingerprint}",
            author_fingerprint=None, body=None, created_at=utc_now_iso(),
        )
        await self._hub.broadcast(channel.name, message)

    async def _handle_presence_snapshot(self, session: LinkRealtimeSession, frame: RealtimeFrame) -> None:
        # Accepted and validated; a merged live remote-roster display
        # (e.g. a channel /who list annotated with connected peers) is
        # deferred UI work -- this vertical's presence requirement is
        # satisfied by presence_delta's live join/leave notices.
        await self._lane.run(
            _decide_channel_subscribe_authorization, channel_id=frame.payload["channel_id"],
            peer_fingerprint=session.remote_fingerprint,
        )

    async def _live_subscribers(self, channel: Channel) -> list[LinkRealtimeSession]:
        """Currently-registered subscriber sessions for `channel`,
        filtered by a fresh trust re-check (design doc §8.10.2:
        "Authorization is checked ... again at message delivery" --
        a subscription from before a peer was quarantined must stop
        receiving pushes, not just future subscribe attempts). A peer
        that no longer passes is dropped from the subscriber set
        outright, not merely skipped this once."""
        subscribers = self._subscribers.get(channel.channel_id)
        if not subscribers:
            return []
        live: list[LinkRealtimeSession] = []
        for fingerprint, session in list(subscribers.items()):
            allowed = await self._lane.run(
                lambda db: decide_node_action(db, fingerprint, LinkPolicyAction.REALTIME).allowed
            )
            if allowed:
                live.append(session)
            else:
                subscribers.pop(fingerprint, None)
        if not subscribers:
            del self._subscribers[channel.channel_id]
        return live

    async def broadcast_local_message_live(self, channel: Channel, message: LocalChannelMessage) -> None:
        """Push a just-locally-authored channel message out to every
        currently live-subscribed peer session for `channel` -- the
        outbound half of `_handle_channel_message`. One slow/dead peer
        session degrades to just that session closing (`LinkRealtime
        Session.send` already handles a full queue) and must never block
        delivery to anyone else or to the local caller who just sent
        the message."""
        sessions = await self._live_subscribers(channel)
        if not sessions:
            return
        frame = build_channel_message_frame(
            channel.channel_id, message.author_label, message.author_label,
            message.body or "", message.created_at,
        )
        for session in sessions:
            try:
                await session.send(frame)
            except LinkTransportError:
                pass

    async def broadcast_local_presence_live(self, channel: Channel, *, change: str, username: str) -> None:
        sessions = await self._live_subscribers(channel)
        if not sessions:
            return
        frame = build_presence_delta_frame(channel.channel_id, change, username, username)
        for session in sessions:
            try:
                await session.send(frame)
            except LinkTransportError:
                pass


async def ensure_live_subscription(
    *,
    channel: Channel,
    node_identity: NodeIdentity,
    link_node: LinkNode,
    lane: DatabaseLane,
    registry: LinkRealtimeSessionRegistry,
    bridge: LiveChannelBridge,
    dial_timeout_seconds: float = 10.0,
) -> LinkRealtimeSession | None:
    """
    If `channel` is Linked, ensure this node holds (or can establish) a
    live session to its origin node and has sent it a `subscribe` --
    best-effort, never raises. A caller who can't get live delivery
    still has the existing async catch-up path (design doc §8.10.2:
    "the caller sees that live traffic may have been missed"), so
    degrading silently to `None` is the correct signal here, not a
    caller-visible error.

    Reuses an already-live session to the origin from `registry` if one
    exists (this node may already be connected to it for another
    channel); otherwise dials the origin's advertised real-time
    address(es) in order, first success wins.

    Takes `lane`, never a raw `Database` -- an interactive caller (a
    channel-join flow) must never touch a `sqlite3.Connection` directly
    off the event loop (see `netbbs.storage.execution.DatabaseLane`'s
    own docstring); the one synchronous read this needs (`channel_
    origin_fingerprint`) is dispatched through it like every other
    business-logic call from `netbbs.net`.
    """
    origin_fingerprint = await lane.run(channel_origin_fingerprint, channel)
    if origin_fingerprint is None or origin_fingerprint == node_identity.fingerprint:
        return None  # not linked, or this node is the origin -- nothing to dial
    session = registry.get(origin_fingerprint)
    if session is None:
        for host, port in dialable_realtime_addresses_for_peer(link_node, origin_fingerprint):
            try:
                session = await asyncio.wait_for(
                    dial_realtime_session(
                        host, port, node_identity, on_frame=bridge.on_frame, registry=registry,
                        lane=lane, enforce_trust_policy=True,
                    ),
                    timeout=dial_timeout_seconds,
                )
            except Exception:
                continue
            bridge.track_session(session)
            break
        else:
            return None
    try:
        await session.send(build_subscribe_frame(channel.channel_id))
    except LinkTransportError:
        return None
    return session
