"""
Tests for `netbbs.link.protocol.LinkNode.handle_inventory_request` (issue
#106): verification-only, mirroring `tests/test_link_relay_consent.py`'s
own scope and structure for `handle_relay_consent_request` exactly, since
both methods share the identical three-part shape (completed-peer check,
claimed-identity cross-check, signature verification) and neither mutates
any state -- these tests check verification outcomes directly, never a
real HTTP round trip (see `tests/test_link_transport.py` for the real-
socket proof that a refusal here actually becomes a 403 and that a valid
request still lets a peer discover carried content).
"""

from __future__ import annotations

import pytest

from netbbs.link.events import sign_inventory_request
from netbbs.link.protocol import InventoryRequest, LinkNode, LinkProtocolError
from tests.link_harness import FakeClock, spawn_node


@pytest.fixture
def clock():
    return FakeClock()


def _two_nodes_with_completed_hello(tmp_path, clock):
    alice = spawn_node(tmp_path, "alice")
    bob = spawn_node(tmp_path, "bob")
    alice_node = LinkNode(identity=alice.identity)
    bob_node = LinkNode(identity=bob.identity)

    alice_hello = alice_node.build_hello(addresses=None, outgoing_only=True, created_at=clock.now_iso())
    bob_hello = bob_node.build_hello(
        addresses=[{"protocol": "http", "address": "198.51.100.7", "port": 7862}],
        outgoing_only=False,
        created_at=clock.now_iso(),
    )
    bob_node.handle_hello(alice_hello)
    alice_node.handle_hello(bob_hello)

    return alice, bob, alice_node, bob_node


def _signed_empty_request(*, signing_identity, requester_fingerprint) -> InventoryRequest:
    signature = sign_inventory_request(
        signing_identity=signing_identity,
        requester_fingerprint=requester_fingerprint,
        boards={}, channels={}, file_areas={},
    )
    return InventoryRequest(
        requester_fingerprint=requester_fingerprint, signature=signature,
        boards={}, channels={}, file_areas={},
    )


def test_handle_inventory_request_accepts_a_valid_request_from_a_completed_peer(tmp_path, clock):
    """The bootstrap-discovery case (issue #94) remains reachable: a
    completed peer's genuinely empty, correctly-signed inventory request
    passes verification -- nothing here refuses it just for asking about
    nothing."""
    alice, bob, alice_node, bob_node = _two_nodes_with_completed_hello(tmp_path, clock)

    request = _signed_empty_request(
        signing_identity=alice.identity.signing_key, requester_fingerprint=alice.fingerprint
    )

    bob_node.handle_inventory_request(alice.fingerprint, request)  # does not raise

    alice.close()
    bob.close()


def test_handle_inventory_request_refuses_a_stranger(tmp_path, clock):
    """The exact case issue #106 exists for: before any resource
    enumeration is even considered, the caller must already be a
    completed peer -- a validly self-signed request from someone bob has
    never said hello to is still refused."""
    alice = spawn_node(tmp_path, "alice")
    bob = spawn_node(tmp_path, "bob")
    bob_node = LinkNode(identity=bob.identity)  # bob never completed a hello with alice

    request = _signed_empty_request(
        signing_identity=alice.identity.signing_key, requester_fingerprint=alice.fingerprint
    )

    with pytest.raises(LinkProtocolError):
        bob_node.handle_inventory_request(alice.fingerprint, request)

    alice.close()
    bob.close()


def test_handle_inventory_request_rejects_a_mismatched_requester_claim(tmp_path, clock):
    """A completed peer cannot enumerate on some other identity's
    behalf: alice sends the request (and the URL names her as sender),
    but the signed payload itself claims mallory's fingerprint."""
    alice, bob, alice_node, bob_node = _two_nodes_with_completed_hello(tmp_path, clock)
    mallory = spawn_node(tmp_path, "mallory")

    request = _signed_empty_request(
        signing_identity=alice.identity.signing_key, requester_fingerprint=mallory.fingerprint
    )

    with pytest.raises(LinkProtocolError):
        bob_node.handle_inventory_request(alice.fingerprint, request)

    alice.close()
    bob.close()
    mallory.close()


def test_handle_inventory_request_rejects_a_forged_signature(tmp_path, clock):
    """Merely claiming a known, completed peer's fingerprint is not
    enough -- the request must actually be signed by that peer's own
    current key, not an arbitrary stranger's. This is the crux of issue
    #106: fingerprints are discoverable (e.g. via `/peers`), so the
    check that actually matters is proof of key possession, not the
    claim alone."""
    alice, bob, alice_node, bob_node = _two_nodes_with_completed_hello(tmp_path, clock)
    mallory = spawn_node(tmp_path, "mallory")

    # Signed by mallory, but claiming to be from alice (a real completed peer).
    request = _signed_empty_request(
        signing_identity=mallory.identity.signing_key, requester_fingerprint=alice.fingerprint
    )

    with pytest.raises(LinkProtocolError):
        bob_node.handle_inventory_request(alice.fingerprint, request)

    alice.close()
    bob.close()
    mallory.close()
