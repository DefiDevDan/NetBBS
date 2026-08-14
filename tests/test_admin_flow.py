"""
Tests for the shared SysOp admin menu, `netbbs.net.admin_flow.admin_menu`
-- the single implementation
both the in-BBS [S]ysOp main-menu option and the standalone `python -m
netbbs.admin` CLI tool call. Driven with a scripted `FakeSession`
(single ordered input queue serving both `read_key`/`read_line`, same
as a real terminal has no concept of "key mode" vs "line mode" beyond
what the caller asks for).
"""

from __future__ import annotations

import asyncio
import base64

import nacl.signing
import pytest

from netbbs.auth.users import SYSOP_LEVEL, count_sysops, create_user, list_users
from netbbs.net.admin_flow import admin_menu
from netbbs.link.trust import (
    TrustDimension,
    TrustState,
    TrustSubject,
    get_effective_trust_state,
    list_sole_authorities,
    list_trust_domains,
    register_subject,
)
from netbbs.link.remote_attestation import (
    build_remote_attestation,
    configure_attestation_authority,
    get_remote_attestation_state,
    ingest_remote_attestation,
    list_attestation_authorities,
)
from netbbs.net.char_input import EditorKey, EditorKeyKind
from netbbs.net.maintenance import MaintenanceMode
from netbbs.net.session import Session
from netbbs.net.session_registry import ActiveSessionRegistry
from netbbs.net.shutdown import NodeControls
from netbbs.rendering import ACCENT_COLOR, MENU_KEY_COLOR, METADATA_COLOR, colored
from netbbs.storage.database import Database
from netbbs.storage.execution import DatabaseLane
from tests.test_shutdown import _hold_registered

# Sentinel strings in FakeSession's single scripted-input queue that
# read_editor_key maps to
# non-CHAR EditorKeyKinds, rather than treating them as literal typed
# text -- keeps the whole file's "one ordered queue for every kind of
# read" convention intact instead of adding a second, incompatible
# queue just for editor-driven tests.
_EDITOR_KEY_SENTINELS: dict[str, EditorKeyKind] = {
    "ENTER": EditorKeyKind.ENTER,
    "BACKSPACE": EditorKeyKind.BACKSPACE,
    "DELETE": EditorKeyKind.DELETE,
    "TAB": EditorKeyKind.TAB,
    "ESCAPE": EditorKeyKind.ESCAPE,
    "UP": EditorKeyKind.UP,
    "DOWN": EditorKeyKind.DOWN,
    "LEFT": EditorKeyKind.LEFT,
    "RIGHT": EditorKeyKind.RIGHT,
    "HOME": EditorKeyKind.HOME,
    "END": EditorKeyKind.END,
    "PAGE_UP": EditorKeyKind.PAGE_UP,
    "PAGE_DOWN": EditorKeyKind.PAGE_DOWN,
}


class FakeSession(Session):
    def __init__(self, inputs: list[str] | None = None):
        self._inputs = list(inputs or [])
        self.written: list[str] = []
        self.terminal_width = 80
        self.terminal_height = 24
        self.peer_address = None

    async def write(self, text: str) -> None:
        self.written.append(text)

    async def read_line(self, echo: bool = True, history=None, completer=None) -> str:
        if not self._inputs:
            raise AssertionError("FakeSession ran out of scripted input (read_line)")
        return self._inputs.pop(0)

    async def read_key(self, echo: bool = True) -> str:
        if not self._inputs:
            raise AssertionError("FakeSession ran out of scripted input (read_key)")
        return self._inputs.pop(0)

    async def read_editor_key(self) -> EditorKey:
        if not self._inputs:
            raise AssertionError("FakeSession ran out of scripted input (read_editor_key)")
        raw = self._inputs.pop(0)
        if raw in _EDITOR_KEY_SENTINELS:
            return EditorKey(_EDITOR_KEY_SENTINELS[raw])
        if raw.startswith("CTRL+"):
            return EditorKey(EditorKeyKind.CTRL, char=raw[len("CTRL+") :].lower())
        if raw == "":
            return EditorKey(EditorKeyKind.ENTER)
        return EditorKey(EditorKeyKind.CHAR, char=raw)

    async def close(self) -> None:
        pass

    async def read_byte(self) -> int | None:
        raise NotImplementedError

    async def write_raw(self, data: bytes) -> None:
        raise NotImplementedError


def _written_text(session: FakeSession) -> str:
    return "".join(session.written)


def _openssh_line(verify_key: nacl.signing.VerifyKey) -> str:
    def encode_string(b: bytes) -> bytes:
        return len(b).to_bytes(4, "big") + b

    blob = encode_string(b"ssh-ed25519") + encode_string(bytes(verify_key))
    return "ssh-ed25519 " + base64.b64encode(blob).decode() + " test@comment"


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "node.db")
    yield database
    database.close()


@pytest.fixture
def lane(db):
    database_lane = DatabaseLane(db.path)
    yield database_lane
    database_lane.close()


@pytest.fixture
def sysop(db):
    return create_user(db, "sysop", password="hunter2", user_level=SYSOP_LEVEL)


def _run(session, lane, user):
    asyncio.run(admin_menu(session, lane, user))


def test_sysop_lands_on_an_operations_overview(db, lane, sysop):
    session = FakeSession(["b"])

    _run(session, lane, sysop)

    text = _written_text(session)
    assert "SysOp operations console" in text
    assert "[LOCAL ADMIN]" in text
    assert "[DISABLED]" in text
    assert "Moderation: 0 pending" in text
    assert "Backup: " in text and "never" in text
    assert "CONSOLE" in text
    assert "QUICK" in text


def test_live_sysop_overview_surfaces_node_and_link_health(db, lane, sysop):
    node_controls = _node_controls()
    link_context = _link_context()
    session = FakeSession(["b"])

    asyncio.run(
        admin_menu(
            session, lane, sysop,
            node_controls=node_controls, link_context=link_context,
        )
    )

    text = _written_text(session)
    assert "[ONLINE]" in text
    assert "Active sessions: 0" in text
    assert "[ATTENTION]" in text
    assert "Peers: 0" in text
    assert "Dead letters: 0" in text
    assert "ink status" in text
    assert "outbox" in text


def test_operations_are_a_coherent_top_level_console_area(db, lane, sysop):
    session = FakeSession(["o", "b", "b"])

    _run(session, lane, sysop)

    text = _written_text(session)
    assert "NetBBS / SysOp / Operations" in text
    assert "Observe the running node, investigate trouble, and recover work." in text
    assert "backup status" in text


def test_operations_console_wraps_actions_on_a_narrow_terminal(db, lane, sysop):
    session = FakeSession(["b"])
    session.terminal_width = 40

    _run(session, lane, sysop)

    text = _written_text(session)
    assert "SysOp operations console" in text
    assert "CONSOLE" in text
    assert "\r\n" in text[text.index("CONSOLE"):text.index("QUICK")]


# -- Phase-4 trust policy -------------------------------------------------


def test_sysop_menu_reaches_trust_domain_configuration(db, lane, sysop):
    session = FakeSession(
        ["s", "p", "d", "a", "friends", "Known independent operators", "0.75", "b", "b", "b"]
    )
    _run(session, lane, sysop)

    domains = list_trust_domains(db)
    assert [(item.domain_id, item.weight) for item in domains] == [("friends", 0.75)]
    text = _written_text(session)
    assert "NetBBS / System / Trust policy" in text
    assert "Trust domain saved and audited." in text


def test_sysop_can_apply_reasoned_override_through_real_menu_path(db, lane, sysop):
    subject = TrustSubject.node("remote-node")
    register_subject(db, subject, first_accepted_at="2026-08-01T00:00:00.000000Z")
    session = FakeSession(
        [
            "s", "p", "s", "0", "1",  # choose the only subject
            "o", "r", "b", "resource abuse reviewed",
            "b", "b", "b", "b",
        ]
    )
    _run(session, lane, sysop)

    state = get_effective_trust_state(db, subject, TrustDimension.RESOURCE_BEHAVIOR)
    assert state.state == TrustState.BLOCKED
    assert state.explanation["override_reason"] == "resource abuse reviewed"
    assert "Trust override applied and audited." in _written_text(session)


def test_declined_sole_authority_confirmation_leaves_policy_safe(db, lane, sysop):
    session = FakeSession(
        [
            "s", "p",
            "d", "a", "emergency", "Emergency operator", "1.0",
            "r", "a", "reporter", "emergency", "identity_integrity:signed_equivocation", "n", "n",
            "e", "a", "reporter", "i", "signed_equivocation", "because", "n",
            "b", "b", "b",
        ]
    )
    _run(session, lane, sysop)
    assert list_sole_authorities(db) == []
    assert "No change made." in _written_text(session)


def test_sysop_menu_reaches_separate_attestation_authority_configuration(
    db, lane, sysop
):
    session = FakeSession(
        [
            "s", "p", "i", "a", "identity-node", "age,name",
            "verified identity contractor", "b", "b", "b",
        ]
    )
    _run(session, lane, sysop)
    authority = list_attestation_authorities(db)[0]
    assert authority.fingerprint == "identity-node"
    assert authority.attributes == ("age", "name")
    assert "Attestation authority changed and audited." in _written_text(session)


def test_sysop_menu_can_reject_remote_attestation_for_one_user(db, lane, sysop):
    subject = TrustSubject.user("remote-home", "opaque-user")
    register_subject(db, subject, first_accepted_at="2026-08-01T00:00:00.000000Z")
    key = nacl.signing.SigningKey.generate()
    configure_attestation_authority(
        db, "identity-node", attributes=["name"], reason="reviewed",
        now_iso="2026-08-14T12:00:00.000000Z",
    )
    wire = build_remote_attestation(
        key,
        issuer_fingerprint="identity-node",
        subject=subject,
        attribute="name",
        attested_value="Remote Alice",
        subject_opt_in=True,
        issued_at="2026-08-14T11:59:00.000000Z",
        expires_at="2026-09-14T12:00:00.000000Z",
    )
    ingest_remote_attestation(
        db, wire, issuer_verify_key=key.verify_key,
        now_iso="2026-08-14T12:00:00.000000Z",
    )
    session = FakeSession(
        [
            "s", "p", "s", "0", "1",
            "i", "n", "r", "local document review",
            "b", "b", "b", "b",
        ]
    )
    _run(session, lane, sysop)
    state = get_remote_attestation_state(db, subject, "name")
    assert state.accepted is False
    assert state.reason_code == "sysop_reject"
    assert "Remote attestation override applied and audited." in _written_text(session)


# -- create user ----------------------------------------------------------


def test_create_user_with_password_only(db, lane, sysop):
    session = FakeSession(["u", "c", "alice", "y", "hunter2", "hunter2", "n", "10", "b", "b"])
    _run(session, lane, sysop)
    created = next(u for u in list_users(db) if u.username == "alice")
    assert created.user_level == 10
    assert "Created 'alice'" in _written_text(session)


def test_create_user_with_pubkey_only_raw_base64(db, lane, sysop):
    verify_key = nacl.signing.SigningKey.generate().verify_key
    raw_b64 = base64.b64encode(bytes(verify_key)).decode()
    session = FakeSession(["u", "c", "bob", "n", "y", raw_b64, "0", "b", "b"])
    _run(session, lane, sysop)
    created = next(u for u in list_users(db) if u.username == "bob")
    assert created.fingerprint is not None


def test_create_user_with_pubkey_only_openssh_line(db, lane, sysop):
    verify_key = nacl.signing.SigningKey.generate().verify_key
    session = FakeSession(["u", "c", "carol", "n", "y", _openssh_line(verify_key), "0", "b", "b"])
    _run(session, lane, sysop)
    created = next(u for u in list_users(db) if u.username == "carol")
    assert created.fingerprint is not None


def test_create_user_with_both_password_and_pubkey(db, lane, sysop):
    verify_key = nacl.signing.SigningKey.generate().verify_key
    raw_b64 = base64.b64encode(bytes(verify_key)).decode()
    session = FakeSession(["u", "c", "dave", "y", "hunter2", "hunter2", "y", raw_b64, "0", "b", "b"])
    _run(session, lane, sysop)
    created = next(u for u in list_users(db) if u.username == "dave")
    assert created.fingerprint is not None


def test_create_user_with_neither_is_cancelled(db, lane, sysop):
    session = FakeSession(["u", "c", "eve", "n", "n", "b", "b"])
    _run(session, lane, sysop)
    assert not any(u.username == "eve" for u in list_users(db))
    assert "needs a password" in _written_text(session)


def test_create_user_with_blank_username_is_cancelled(db, lane, sysop):
    session = FakeSession(["u", "c", "", "b", "b"])
    _run(session, lane, sysop)
    assert "cannot be blank" in _written_text(session)


# -- list / detail ---------------------------------------------------------


def test_list_users_and_select_shows_detail(db, lane, sysop):
    session = FakeSession(["u", "l", "0", "1", "b", "b", "b"])
    _run(session, lane, sysop)
    assert "sysop" in _written_text(session)
    assert "Level: 255" in _written_text(session)


def test_list_users_sort_by_highest_level_first_changes_pick_order(db, lane, sysop):
    """Design doc -- Thiesi's own dogfood-testing report: SysOps wanted
    more than the one fixed alphabetical order this screen always used
    to show. "H" (highest level first) puts sysop (255) ahead of alice
    (10), the reverse of alphabetical order for these two names."""
    create_user(db, "alice", password="hunter2", user_level=10)
    # Default is alphabetical ascending -- press "l" twice (once for
    # level ascending, again to flip to descending) to get highest
    # level first.
    session = FakeSession(["u", "l", "l", "l", "0", "1", "b", "b", "b"])
    _run(session, lane, sysop)
    assert "Level: 255" in _written_text(session)  # sysop, picked as item 01


def test_list_users_defaults_to_alphabetical_ascending_with_no_sort_prompt_needed(db, lane, sysop):
    """[L]ist users jumps straight to the listing now -- no separate
    one-shot sort-order prompt to answer first."""
    create_user(db, "alice", password="hunter2", user_level=10)
    session = FakeSession(["u", "l", "0", "1", "b", "b", "b"])
    _run(session, lane, sysop)
    assert "alice" in _written_text(session)  # item 01 alphabetically
    assert "Sorted by: Alphabetical ↑" in _written_text(session)


def test_user_picker_pressing_the_active_sort_key_again_toggles_direction(db, lane, sysop):
    """Thiesi's own follow-up request: A/R/L are live toggles -- the
    second press of the *same* key flips ascending/descending in place,
    without leaving the screen."""
    create_user(db, "alice", password="hunter2", user_level=10)
    # "a" while already on alphabetical-ascending (the default) flips to
    # descending -- sysop (level 255) now sorts before alice (Z before A
    # doesn't apply here, but "sysop" > "alice" alphabetically, so
    # descending puts sysop first).
    session = FakeSession(["u", "l", "a", "b", "b", "b"])
    _run(session, lane, sysop)
    text = _written_text(session)
    assert "Sorted by: Alphabetical ↓" in text
    # Use rindex, not index: the screen redraws in place, so the very
    # first (pre-toggle, ascending) render is still earlier in the
    # cumulative output -- only the *last* render reflects the toggle.
    assert text.rindex("sysop") < text.rindex("alice")


def test_user_picker_pressing_the_active_sort_key_a_third_time_returns_to_ascending(db, lane, sysop):
    session = FakeSession(["u", "l", "a", "a", "b", "b", "b"])
    _run(session, lane, sysop)
    assert "Sorted by: Alphabetical ↑" in _written_text(session)


def test_user_picker_switching_to_a_different_sort_mode_starts_ascending(db, lane, sysop):
    """Pressing a *different* mode's key always starts that mode
    ascending, regardless of what direction the previous mode was left
    in."""
    create_user(db, "alice", password="hunter2", user_level=10)
    session = FakeSession(["u", "l", "a", "l", "b", "b", "b"])  # a (desc) -> l (level, ascending)
    _run(session, lane, sysop)
    text = _written_text(session)
    assert "Sorted by: Level ↑" in text
    assert text.rindex("alice") < text.rindex("sysop")  # alice (10) before sysop (255)


def test_user_picker_registration_toggle_shows_both_directions(db, lane, sysop):
    create_user(db, "alice", password="hunter2", user_level=10)
    session = FakeSession(["u", "l", "r", "b", "b", "b"])
    _run(session, lane, sysop)
    text = _written_text(session)
    assert "Sorted by: Registration date ↑" in text
    assert text.rindex("sysop") < text.rindex("alice")  # sysop created first (ascending)


def test_user_picker_search_still_works(db, lane, sysop):
    create_user(db, "alice", password="hunter2", user_level=10)
    session = FakeSession(["u", "l", "s", "alice", "b", "b", "b"])
    _run(session, lane, sysop)
    # A single match auto-selects straight into the detail screen.
    assert "Level: 10" in _written_text(session)


def test_user_picker_goto_still_works(db, lane, sysop):
    alice = create_user(db, "alice", password="hunter2", user_level=10)
    session = FakeSession(["u", "l", "g", str(alice.id), "b", "b", "b"])
    _run(session, lane, sysop)
    assert "Level: 10" in _written_text(session)


def test_user_picker_visibility_toggle_hides_disabled_users_on_first_press(db, lane, sysop):
    """The biggest node's own SysOp, dogfooding the sort toggles with a
    real ~50-user roster: [V] cycles all -> active-only -> disabled-only
    -> all. First press hides disabled accounts entirely."""
    from netbbs.auth.users import set_user_disabled

    alice = create_user(db, "alice", password="hunter2", user_level=10)
    bob = create_user(db, "bob", password="hunter2", user_level=10)
    set_user_disabled(db, bob, True, changed_by=sysop)

    session = FakeSession(["u", "l", "v", "b", "b", "b"])
    _run(session, lane, sysop)
    text = _written_text(session)
    marker = "Showing: Active users only (disabled hidden)"
    assert marker in text
    # rindex, not index/`in`: the screen redraws in place, and the
    # cumulative output still contains the very first, pre-toggle render
    # (where both users are visible) earlier in the text -- only what
    # comes after the *last* render reflects the current filter (same
    # pitfall this codebase already hit with the A/R/L sort toggle).
    after = text[text.rindex(marker):]
    assert "alice" in after
    assert "bob" not in after


def test_user_picker_visibility_toggle_shows_only_disabled_on_second_press(db, lane, sysop):
    from netbbs.auth.users import set_user_disabled

    alice = create_user(db, "alice", password="hunter2", user_level=10)
    bob = create_user(db, "bob", password="hunter2", user_level=10)
    set_user_disabled(db, bob, True, changed_by=sysop)

    session = FakeSession(["u", "l", "v", "v", "b", "b", "b"])
    _run(session, lane, sysop)
    text = _written_text(session)
    marker = "Showing: Disabled users only"
    assert marker in text
    after = text[text.rindex(marker):]
    assert "bob" in after
    assert "alice" not in after


def test_user_picker_visibility_toggle_returns_to_all_on_third_press(db, lane, sysop):
    from netbbs.auth.users import set_user_disabled

    alice = create_user(db, "alice", password="hunter2", user_level=10)
    bob = create_user(db, "bob", password="hunter2", user_level=10)
    set_user_disabled(db, bob, True, changed_by=sysop)

    session = FakeSession(["u", "l", "v", "v", "v", "b", "b", "b"])
    _run(session, lane, sysop)
    text = _written_text(session)
    marker = "Showing: All users"
    # rindex: "All users" is also the *initial* pre-toggle state, so a
    # naive `.index()` would match the very first render instead of the
    # one after the third press.
    after = text[text.rindex(marker):]
    assert "alice" in after
    assert "bob" in after


def test_user_picker_visibility_filter_scopes_search_and_goto(db, lane, sysop):
    """The whole point of hiding a class of accounts is to stop having to
    look at or reach them -- search and goto should respect the active
    visibility filter, not silently bypass it."""
    from netbbs.auth.users import set_user_disabled

    create_user(db, "alice", password="hunter2", user_level=10)
    bob = create_user(db, "bob", password="hunter2", user_level=10)
    set_user_disabled(db, bob, True, changed_by=sysop)

    # Active-only filter is on; searching for the hidden, disabled "bob"
    # finds nothing even though the account exists.
    session = FakeSession(["u", "l", "v", "s", "bob", "b", "b", "b"])
    _run(session, lane, sysop)
    assert "No matches." in _written_text(session)

    # Same filter; goto by bob's numeric ID is likewise out of range.
    session2 = FakeSession(["u", "l", "v", "g", str(bob.id), "b", "b", "b"])
    _run(session2, lane, sysop)
    assert "Out of range." in _written_text(session2)


def test_list_users_unrecognized_key_sounds_a_bell_and_changes_nothing(db, lane, sysop):
    """An unrecognized key on the listing screen itself follows the same
    bell-only, no-redraw convention netbbs.net.picker.pick_item already
    establishes -- not a lenient fallback, since there's no longer a
    separate one-shot prompt where that made sense."""
    create_user(db, "alice", password="hunter2", user_level=10)
    session = FakeSession(["u", "l", "z", "0", "1", "b", "b", "b"])
    _run(session, lane, sysop)
    assert "\b \b\a" in _written_text(session)
    assert "alice" in _written_text(session)  # still item 01 alphabetically -- sort unchanged


def test_central_editor_lets_a_sysop_promote_then_disable_the_same_user_without_repicking(db, lane, sysop):
    """The actual point of consolidating into one editor (design doc --
    Thiesi's own dogfood-testing report): promote, then disable, the
    exact same already-selected account without leaving the screen or
    picking them a second time through a separate flow."""
    create_user(db, "alice", password="hunter2", user_level=10)
    session = FakeSession(
        ["u", "l", "0", "1", "l", "20", "t", "y", "b", "b", "b"]
    )
    _run(session, lane, sysop)
    updated = next(u for u in list_users(db) if u.username == "alice")
    assert updated.user_level == 20
    assert updated.disabled_at is not None


# -- promote/demote ---------------------------------------------------------


def test_promote_demote_changes_level(db, lane, sysop):
    alice = create_user(db, "alice", password="hunter2", user_level=10)
    # alice sorts before sysop alphabetically -- item 01.
    session = FakeSession(["u", "p", "0", "1", "l", "20", "b", "b", "b"])
    _run(session, lane, sysop)
    updated = next(u for u in list_users(db) if u.username == "alice")
    assert updated.user_level == 20


def test_promote_demote_shows_lockout_guard_message(db, lane, sysop):
    # sysop is the only user, and the only active SysOp -- demoting
    # them must be refused, with the message shown on screen, not a
    # crash.
    session = FakeSession(["u", "p", "0", "1", "l", "10", "b", "b", "b"])
    _run(session, lane, sysop)
    assert "only active SysOp-level account" in _written_text(session)
    assert count_sysops(db) == 1


# -- enable/disable ---------------------------------------------------------


def test_disable_enable_toggles_status(db, lane, sysop):
    alice = create_user(db, "alice", password="hunter2", user_level=10)
    session = FakeSession(["u", "e", "0", "1", "t", "y", "b", "b", "b"])
    _run(session, lane, sysop)
    updated = next(u for u in list_users(db) if u.username == "alice")
    assert updated.disabled_at is not None


def test_disable_declining_confirmation_leaves_account_active(db, lane, sysop):
    alice = create_user(db, "alice", password="hunter2", user_level=10)
    session = FakeSession(["u", "e", "0", "1", "t", "n", "b", "b", "b"])
    _run(session, lane, sysop)
    updated = next(u for u in list_users(db) if u.username == "alice")
    assert updated.disabled_at is None


def test_disable_shows_lockout_guard_message(db, lane, sysop):
    session = FakeSession(["u", "e", "0", "1", "t", "y", "b", "b", "b"])
    _run(session, lane, sysop)
    assert "only active SysOp-level account" in _written_text(session)


# -- delete -----------------------------------------------------------------


def test_delete_with_correct_username_confirmation_deletes(db, lane, sysop):
    alice = create_user(db, "alice", password="hunter2", user_level=10)
    session = FakeSession(["u", "d", "0", "1", "d", "alice", "b", "b"])
    _run(session, lane, sysop)
    assert not any(u.username == "alice" for u in list_users(db))
    assert "deleted" in _written_text(session)


def test_delete_with_mismatched_confirmation_does_not_delete(db, lane, sysop):
    create_user(db, "alice", password="hunter2", user_level=10)
    session = FakeSession(["u", "d", "0", "1", "d", "not-alice", "b", "b", "b"])
    _run(session, lane, sysop)
    assert any(u.username == "alice" for u in list_users(db))
    assert "Cancelled" in _written_text(session)


def test_delete_with_blank_confirmation_does_not_delete(db, lane, sysop):
    create_user(db, "alice", password="hunter2", user_level=10)
    session = FakeSession(["u", "d", "0", "1", "d", "", "b", "b", "b"])
    _run(session, lane, sysop)
    assert any(u.username == "alice" for u in list_users(db))


def test_delete_warning_describes_retained_session_history_identity_data(db, lane, sysop):
    """Issue #111's own acceptance criterion: the deletion confirmation
    must accurately describe what happens to Last sessions identity data
    -- it survives, honoring whatever name-visibility choice was already
    in effect, not silently revealed or silently erased."""
    create_user(db, "alice", password="hunter2", user_level=10)
    session = FakeSession(["u", "d", "0", "1", "d", "not-alice", "b", "b", "b"])
    _run(session, lane, sysop)
    text = _written_text(session)
    assert "Last sessions" in text
    assert "name-visibility" in text or "visibility choice" in text


# -- GitHub issue #29: disable/delete revoke live sessions -----------------


def test_disable_disconnects_the_targets_live_session(db, lane, sysop):
    async def scenario():
        create_user(db, "alice", password="hunter2", user_level=10)
        node_controls = _node_controls()
        registry = node_controls.session_registry
        alice_session = FakeSession()
        alice_task = asyncio.create_task(_hold_registered(registry, alice_session))
        await asyncio.sleep(0)
        registry.mark_authenticated(alice_session, "alice")

        admin_session = FakeSession(["u", "e", "0", "1", "t", "y", "b", "b", "b"])
        registry.enter(admin_session)
        try:
            await admin_menu(admin_session, lane, sysop, node_controls=node_controls)
        finally:
            registry.leave(admin_session)

        assert alice_task.cancelled() or alice_task.done()
        assert "Disconnected 1" in _written_text(admin_session)

    asyncio.run(scenario())


def test_re_enabling_does_not_disconnect_anyone(db, lane, sysop):
    async def scenario():
        alice = create_user(db, "alice", password="hunter2", user_level=10)
        from netbbs.auth.users import set_user_disabled

        set_user_disabled(db, alice, True, changed_by=sysop)
        node_controls = _node_controls()
        registry = node_controls.session_registry
        alice_session = FakeSession()
        alice_task = asyncio.create_task(_hold_registered(registry, alice_session))
        await asyncio.sleep(0)
        registry.mark_authenticated(alice_session, "alice")

        admin_session = FakeSession(["u", "e", "0", "1", "t", "y", "b", "b", "b"])
        registry.enter(admin_session)
        try:
            await admin_menu(admin_session, lane, sysop, node_controls=node_controls)
        finally:
            registry.leave(admin_session)

        assert not alice_task.cancelled()
        assert "Disconnected" not in _written_text(admin_session)

        alice_task.cancel()
        await asyncio.gather(alice_task, return_exceptions=True)

    asyncio.run(scenario())


def test_delete_disconnects_the_targets_live_session(db, lane, sysop):
    async def scenario():
        create_user(db, "alice", password="hunter2", user_level=10)
        node_controls = _node_controls()
        registry = node_controls.session_registry
        alice_session = FakeSession()
        alice_task = asyncio.create_task(_hold_registered(registry, alice_session))
        await asyncio.sleep(0)
        registry.mark_authenticated(alice_session, "alice")

        admin_session = FakeSession(["u", "d", "0", "1", "d", "alice", "b", "b"])
        registry.enter(admin_session)
        try:
            await admin_menu(admin_session, lane, sysop, node_controls=node_controls)
        finally:
            registry.leave(admin_session)

        assert alice_task.cancelled() or alice_task.done()
        assert "Disconnected 1" in _written_text(admin_session)

    asyncio.run(scenario())


def test_disable_without_node_controls_does_not_raise(db, lane, sysop):
    """The standalone `python -m netbbs.admin` CLI has no live node
    state (node_controls=None) -- disabling a user there must still
    work, just without anything to disconnect."""
    create_user(db, "alice", password="hunter2", user_level=10)
    session = FakeSession(["u", "e", "0", "1", "t", "y", "b", "b", "b"])
    _run(session, lane, sysop)  # must not raise
    updated = next(u for u in list_users(db) if u.username == "alice")
    assert updated.disabled_at is not None


def test_disabling_your_own_account_excludes_your_own_session(db, lane, sysop):
    """Disabling the acting SysOp's own account must not try to
    cancel-and-await its own currently-running task (GitHub issue #29).
    A second SysOp-level account exists specifically so the "can't
    disable the only active SysOp" guard doesn't block this and mask
    the thing actually under test."""
    create_user(db, "zysop", password="hunter2", user_level=SYSOP_LEVEL)  # sorts after "sysop"

    async def scenario():
        node_controls = _node_controls()
        registry = node_controls.session_registry
        admin_session = FakeSession(["u", "e", "0", "1", "t", "y", "b", "b", "b"])
        registry.enter(admin_session)
        registry.mark_authenticated(admin_session, sysop.username)
        try:
            await asyncio.wait_for(
                admin_menu(admin_session, lane, sysop, node_controls=node_controls), timeout=2
            )
        finally:
            registry.leave(admin_session)
        # Reaching here at all (not hanging/erroring) is the assertion --
        # excluding the acting session from disconnect_username avoided
        # the self-cancellation hazard.
        updated = next(u for u in list_users(db) if u.username == sysop.username)
        assert updated.disabled_at is not None

    asyncio.run(scenario())


# -- invalid key: bell only convention ---------------------------------------


def test_invalid_key_writes_only_a_bell(db, lane, sysop):
    session = FakeSession(["z", "b"])
    _run(session, lane, sysop)
    bell_index = session.written.index("\b \b\a")
    assert session.written[bell_index] == "\b \b\a"
    assert session.written[:bell_index].count("Choice: ") == 1


# -- node management -------------------------------------------------------


def _node_controls() -> NodeControls:
    return NodeControls(
        session_registry=ActiveSessionRegistry(),
        maintenance=MaintenanceMode(),
        shutdown_event=asyncio.Event(),
        graceful_delay_seconds=60.0,
    )


def test_node_option_hidden_without_node_controls(db, lane, sysop):
    session = FakeSession(["s", "n", "b", "b"])
    _run(session, lane, sysop)  # _run's admin_menu call passes no node_controls
    bell_index = session.written.index("\b \b\a")
    assert session.written[bell_index] == "\b \b\a"


def test_who_lists_and_disconnects_another_session(db, lane, sysop):
    async def scenario():
        node_controls = _node_controls()
        registry = node_controls.session_registry
        other = FakeSession()
        other_task = asyncio.create_task(_hold_registered(registry, other))
        await asyncio.sleep(0)  # let the other session register

        admin_session = FakeSession(["s", "n", "w", "0", "1", "y", "", "b", "b", "b"])
        registry.enter(admin_session)
        try:
            await admin_menu(admin_session, lane, sysop, node_controls=node_controls)
        finally:
            registry.leave(admin_session)

        assert other_task.cancelled() or other_task.done()
        text = _written_text(admin_session)
        assert "disconnected" in text
        # Same pick_item semantic field palette asserted by caller Who.
        assert colored("  01. ", fg_color=MENU_KEY_COLOR) in text
        assert f"\x1b[38;5;{ACCENT_COLOR}m(unauthenticated)" in text
        assert f"\x1b[38;5;{METADATA_COLOR}m - connected since " in text

    asyncio.run(scenario())


def test_who_refuses_to_disconnect_own_session(db, lane, sysop):
    async def scenario():
        node_controls = _node_controls()
        registry = node_controls.session_registry

        admin_session = FakeSession(["s", "n", "w", "0", "1", "b", "b", "b"])
        registry.enter(admin_session)
        try:
            await admin_menu(admin_session, lane, sysop, node_controls=node_controls)
        finally:
            registry.leave(admin_session)

        assert "use Logoff instead" in _written_text(admin_session)

    asyncio.run(scenario())


def test_who_screen_explains_what_selecting_a_session_does(db, lane, sysop):
    """Design doc -- node management, Thiesi's own dogfood-testing
    report: previously the screen never said anywhere that selecting a
    session disconnects it -- a SysOp only found out by doing it."""
    session = FakeSession(["s", "n", "w", "b", "b", "b"])
    asyncio.run(admin_menu(session, lane, sysop, node_controls=_node_controls()))
    assert "Select a session below to disconnect it." in _written_text(session)


def test_who_screen_delivers_a_custom_message_to_the_target_before_disconnecting(db, lane, sysop):
    async def scenario():
        node_controls = _node_controls()
        registry = node_controls.session_registry
        other = FakeSession()
        other_task = asyncio.create_task(_hold_registered(registry, other))
        await asyncio.sleep(0)

        admin_session = FakeSession(
            ["s", "n", "w", "0", "1", "y", "Reconnect in a few minutes.", "b", "b", "b"]
        )
        registry.enter(admin_session)
        try:
            await admin_menu(admin_session, lane, sysop, node_controls=node_controls)
        finally:
            registry.leave(admin_session)

        assert any("Reconnect in a few minutes." in line for line in other.written)
        assert other_task.cancelled() or other_task.done()

    asyncio.run(scenario())


def test_who_screen_with_no_custom_message_sends_nothing_extra_to_the_target(db, lane, sysop):
    async def scenario():
        node_controls = _node_controls()
        registry = node_controls.session_registry
        other = FakeSession()
        other_task = asyncio.create_task(_hold_registered(registry, other))
        await asyncio.sleep(0)

        # Blank message -- the target must receive nothing at all before
        # being disconnected, same as before this feature existed.
        admin_session = FakeSession(["s", "n", "w", "0", "1", "y", "", "b", "b", "b"])
        registry.enter(admin_session)
        try:
            await admin_menu(admin_session, lane, sysop, node_controls=node_controls)
        finally:
            registry.leave(admin_session)

        assert other.written == []

    asyncio.run(scenario())


def test_who_screen_shows_the_real_persisted_session_id_not_a_recomputed_position(db, lane, sysop):
    """Issue #113: the "(#N)" reference `pick_item` shows must be
    `ActiveSessionRegistry`'s own persistent, never-reused session_id --
    not something merely derived from current page position (which would
    always just be 1, 2, 3... and could never actually distinguish this
    from the pre-#113 id(session) behavior in a test). Session A enters
    and leaves first, freeing session_id 1; B and C then enter and stay,
    getting session_id 2 and 3. On a page listing only [B, C], a
    position-based scheme would show 01/02 -- the real IDs are 2 and 3."""
    async def scenario():
        node_controls = _node_controls()
        registry = node_controls.session_registry

        a_task = asyncio.create_task(_hold_registered(registry, FakeSession()))
        await asyncio.sleep(0)
        a_task.cancel()
        await asyncio.gather(a_task, return_exceptions=True)

        b, c = FakeSession(), FakeSession()
        b_task = asyncio.create_task(_hold_registered(registry, b))
        c_task = asyncio.create_task(_hold_registered(registry, c))
        await asyncio.sleep(0)

        # One extra "b" versus other Who-screen tests: those select a
        # session (which returns control to _who_screen without needing
        # its own "b"), this one backs straight out of the picker itself
        # first, then unwinds node/sysop menus same as always.
        admin_session = FakeSession(["s", "n", "w", "b", "b", "b", "b"])
        registry.enter(admin_session)
        try:
            await admin_menu(admin_session, lane, sysop, node_controls=node_controls)
        finally:
            registry.leave(admin_session)

        text = _written_text(admin_session)
        assert "(#2)" in text
        assert "(#3)" in text
        assert "(#1)" not in text

        for task in (b_task, c_task):
            task.cancel()
        await asyncio.gather(b_task, c_task, return_exceptions=True)

    asyncio.run(scenario())


def test_who_screen_goto_targets_the_exact_session_by_its_real_id(db, lane, sysop):
    """SysOp disconnect must still target the exact selected session
    (issue #113's own acceptance criterion) when reached via `Go to #`
    rather than a 2-digit page position -- proving the number shown is
    genuinely usable as `pick_item`'s own permanent per-item reference,
    not merely cosmetic."""
    async def scenario():
        node_controls = _node_controls()
        registry = node_controls.session_registry

        # A leaves first, so B and C's real session_id (2, 3) diverges
        # from their page position (1, 2) -- same setup as the display
        # test above, reused here to prove goto, not just display, uses
        # the real ID.
        a_task = asyncio.create_task(_hold_registered(registry, FakeSession()))
        await asyncio.sleep(0)
        a_task.cancel()
        await asyncio.gather(a_task, return_exceptions=True)

        b, c = FakeSession(), FakeSession()
        b_task = asyncio.create_task(_hold_registered(registry, b))
        c_task = asyncio.create_task(_hold_registered(registry, c))
        await asyncio.sleep(0)

        # "g" (goto), target session_id 2 (b, page position 01 here --
        # but selection must be driven by the typed ID, not position),
        # then confirm disconnecting it with no custom message.
        admin_session = FakeSession(["s", "n", "w", "g", "2", "y", "", "b", "b", "b"])
        registry.enter(admin_session)
        try:
            await admin_menu(admin_session, lane, sysop, node_controls=node_controls)
        finally:
            registry.leave(admin_session)

        await asyncio.sleep(0)
        assert b_task.cancelled() or b_task.done()
        assert not (c_task.cancelled() or c_task.done())

        c_task.cancel()
        await asyncio.gather(c_task, return_exceptions=True)

    asyncio.run(scenario())


async def _run_admin_session_as_its_own_task(session, lane, actor, node_controls, registry):
    """
    Runs `admin_menu` as an independent task with its own `enter()`/
    `leave()`, mirroring how a real connection's `handle_session` always
    runs as its own task in production -- never inline within whatever
    task later triggers a shutdown. Needed specifically for tests that
    go on to `await node_controls.shutdown_event.wait()` from the test's
    *own* task afterward: if `admin_session` were instead registered
    under that same outer task, `disconnect_all()`'s eventual
    cancellation would be cancelling the very task suspended waiting for
    the event it's about to set -- the identical self-referential hazard
    `run_shutdown_sequence`'s fire-and-forget design exists to avoid,
    just recreated inside the test instead of the code under test.
    """
    registry.enter(session)
    try:
        await admin_menu(session, lane, actor, node_controls=node_controls)
    finally:
        registry.leave(session)


def test_shutdown_screen_triggers_the_sequence_as_a_background_task(db, lane, sysop):
    async def scenario():
        node_controls = _node_controls()
        registry = node_controls.session_registry

        # Scripted with trailing "b", "b" to return all the way out --
        # FakeSession's reads never actually suspend, so admin_task runs
        # to completion (including its own registry.leave()) in a single
        # scheduling turn, before the background sequence gets a turn to
        # run at all. That's fine for what this test checks: that the
        # sequence was fired as non-blocking and genuinely takes effect
        # afterward -- "does disconnect_all() reach a still-mid-read
        # session" is already covered thoroughly in tests/test_shutdown.py
        # (via a session that genuinely blocks), not re-proven here.
        admin_session = FakeSession(["s", "n", "s", "i", "", "y", "b", "b", "b"])
        admin_task = asyncio.create_task(
            _run_admin_session_as_its_own_task(admin_session, lane, sysop, node_controls, registry)
        )

        await asyncio.wait_for(node_controls.shutdown_event.wait(), timeout=2.0)
        await asyncio.gather(admin_task, return_exceptions=True)

        assert "Shutdown sequence started." in _written_text(admin_session)
        assert node_controls.maintenance.is_active() is True
        assert len(registry) == 0

    asyncio.run(scenario())


def test_shutdown_screen_with_custom_message_replaces_the_default(db, lane, sysop):
    async def scenario():
        node_controls = _node_controls()
        registry = node_controls.session_registry

        other = FakeSession()
        other_task = asyncio.create_task(_hold_registered(registry, other))
        await asyncio.sleep(0)

        admin_session = FakeSession(
            ["s", "n", "s", "i", "Emergency patch, back shortly.", "y", "b", "b", "b"]
        )
        admin_task = asyncio.create_task(
            _run_admin_session_as_its_own_task(admin_session, lane, sysop, node_controls, registry)
        )

        await asyncio.wait_for(node_controls.shutdown_event.wait(), timeout=2.0)
        await asyncio.gather(other_task, admin_task, return_exceptions=True)

        assert any("Emergency patch" in line for line in other.written)
        assert not any("going down now" in line for line in other.written)

    asyncio.run(scenario())


def test_shutdown_screen_declined_confirmation_does_nothing(db, lane, sysop):
    async def scenario():
        node_controls = _node_controls()
        registry = node_controls.session_registry

        # "g" (graceful) now also prompts for a delay (blank keeps the
        # configured default) before the custom-message prompt -- design
        # doc, node management: [S]hutdown now behaves exactly like
        # [D]rain, an operator-chosen delay rather than a fixed config
        # value with no override.
        admin_session = FakeSession(["s", "n", "s", "g", "", "", "n", "b", "b", "b"])
        registry.enter(admin_session)
        try:
            await admin_menu(admin_session, lane, sysop, node_controls=node_controls)
        finally:
            registry.leave(admin_session)

        assert "Cancelled." in _written_text(admin_session)
        assert node_controls.shutdown_event.is_set() is False
        assert node_controls.maintenance.is_active() is False

    asyncio.run(scenario())


# -- maintenance mode and drain (design doc §13.8) --------------------------


def test_node_menu_shows_maintenance_and_drain_options(db, lane, sysop):
    node_controls = _node_controls()
    session = FakeSession(["s", "n", "b", "b", "b"])
    asyncio.run(admin_menu(session, lane, sysop, node_controls=node_controls))
    text = _written_text(session)
    # menu_key wraps just the letter itself in ANSI color codes -- the
    # rest of each label (everything after the bracketed key) is what
    # actually appears as a clean, uncolored substring.
    assert "aintenance mode" in text
    assert "rain" in text


def test_maintenance_mode_screen_turns_it_on(db, lane, sysop):
    node_controls = _node_controls()
    session = FakeSession(["s", "n", "m", "y", "b", "b", "b"])
    asyncio.run(admin_menu(session, lane, sysop, node_controls=node_controls))
    assert node_controls.maintenance.is_lockdown_active() is True
    assert "Maintenance mode is now ON." in _written_text(session)


def test_maintenance_mode_screen_turns_it_back_off(db, lane, sysop):
    node_controls = _node_controls()
    node_controls.maintenance.enable_lockdown()
    session = FakeSession(["s", "n", "m", "y", "b", "b", "b"])
    asyncio.run(admin_menu(session, lane, sysop, node_controls=node_controls))
    assert node_controls.maintenance.is_lockdown_active() is False
    assert "Maintenance mode is now off." in _written_text(session)


def test_maintenance_mode_screen_declined_confirmation_does_nothing(db, lane, sysop):
    node_controls = _node_controls()
    session = FakeSession(["s", "n", "m", "n", "b", "b", "b"])
    asyncio.run(admin_menu(session, lane, sysop, node_controls=node_controls))
    assert node_controls.maintenance.is_lockdown_active() is False


def test_maintenance_mode_screen_does_not_touch_shutdown_lockout(db, lane, sysop):
    """Design doc §13.8: [M]aintenance mode's lockdown flag is entirely
    separate from shutdown's own `is_active()` lockout."""
    node_controls = _node_controls()
    session = FakeSession(["s", "n", "m", "y", "b", "b", "b"])
    asyncio.run(admin_menu(session, lane, sysop, node_controls=node_controls))
    assert node_controls.maintenance.is_lockdown_active() is True
    assert node_controls.maintenance.is_active() is False


async def _wait_until_done(task: asyncio.Task, *, timeout: float = 2.0) -> None:
    """Polls `task.done()` rather than `await`ing/`wait_for`ing the task
    itself a second time -- a task already finished via cancellation
    re-raises `CancelledError` to *any* subsequent awaiter, not just the
    one it was originally cancelled under, so a caller that only wants
    to know "has this settled yet" (to then check `.cancelled()`
    separately) must not re-await it directly."""
    deadline = asyncio.get_event_loop().time() + timeout
    while not task.done():
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError("task never finished")
        await asyncio.sleep(0.01)


def test_drain_screen_triggers_the_sequence_as_a_background_task(db, lane, sysop):
    async def scenario():
        node_controls = _node_controls()
        registry = node_controls.session_registry

        other = FakeSession()
        other_task = asyncio.create_task(_hold_registered(registry, other))
        await asyncio.sleep(0)

        admin_session = FakeSession(["s", "n", "d", "0", "", "y", "b", "b", "b"])
        admin_task = asyncio.create_task(
            _run_admin_session_as_its_own_task(admin_session, lane, sysop, node_controls, registry)
        )
        await asyncio.wait_for(admin_task, timeout=2.0)
        await _wait_until_done(other_task)

        assert "Drain started" in _written_text(admin_session)
        assert other_task.cancelled()

    asyncio.run(scenario())


def test_drain_screen_never_disconnects_the_issuing_sysop(db, lane, sysop):
    async def scenario():
        node_controls = _node_controls()
        registry = node_controls.session_registry

        admin_session = FakeSession(["s", "n", "d", "0", "", "y", "b", "b", "b"])
        registry.enter(admin_session)
        try:
            await admin_menu(admin_session, lane, sysop, node_controls=node_controls)
        finally:
            registry.leave(admin_session)

        assert "Drain started" in _written_text(admin_session)

    asyncio.run(scenario())


def test_drain_screen_with_custom_message_replaces_the_default(db, lane, sysop):
    async def scenario():
        node_controls = _node_controls()
        registry = node_controls.session_registry

        other = FakeSession()
        other_task = asyncio.create_task(_hold_registered(registry, other))
        await asyncio.sleep(0)

        admin_session = FakeSession(
            ["s", "n", "d", "0", "Reconnect after the upgrade.", "y", "b", "b", "b"]
        )
        admin_task = asyncio.create_task(
            _run_admin_session_as_its_own_task(admin_session, lane, sysop, node_controls, registry)
        )
        await asyncio.wait_for(admin_task, timeout=2.0)
        await _wait_until_done(other_task)

        assert any("Reconnect after the upgrade" in line for line in other.written)

    asyncio.run(scenario())


def test_drain_screen_rejects_a_negative_delay(db, lane, sysop):
    session = FakeSession(["s", "n", "d", "-5", "b", "b", "b"])
    asyncio.run(admin_menu(session, lane, sysop, node_controls=_node_controls()))
    assert "cannot be negative" in _written_text(session)


def test_drain_screen_rejects_a_non_numeric_delay(db, lane, sysop):
    session = FakeSession(["s", "n", "d", "soon", "b", "b", "b"])
    asyncio.run(admin_menu(session, lane, sysop, node_controls=_node_controls()))
    assert "Not a number" in _written_text(session)


def test_drain_screen_declined_confirmation_does_nothing(db, lane, sysop):
    async def scenario():
        node_controls = _node_controls()
        registry = node_controls.session_registry

        other = FakeSession()
        other_task = asyncio.create_task(_hold_registered(registry, other))
        await asyncio.sleep(0)

        admin_session = FakeSession(["s", "n", "d", "0", "", "n", "b", "b", "b"])
        registry.enter(admin_session)
        try:
            await admin_menu(admin_session, lane, sysop, node_controls=node_controls)
        finally:
            registry.leave(admin_session)

        assert "Cancelled." in _written_text(admin_session)
        assert not other_task.done()  # drain never fired -- the other session is untouched

        other_task.cancel()
        await asyncio.gather(other_task, return_exceptions=True)

    asyncio.run(scenario())


# -- cancelling/replacing a scheduled drain or shutdown (design doc -- node --
# -- management, the stacking-bug fix Thiesi's own dogfood testing found) ----


def test_drain_screen_offers_to_cancel_an_already_scheduled_drain(db, lane, sysop):
    """The actual fix for the reported bug: running [D]rain again while
    one is already scheduled must offer an explicit cancel choice
    rather than silently launching a second, uncoordinated countdown."""
    async def scenario():
        node_controls = _node_controls()
        registry = node_controls.session_registry
        loop = asyncio.get_running_loop()
        first_task = asyncio.create_task(asyncio.Event().wait())
        node_controls.drain_scheduler.schedule(first_task, deadline=loop.time() + 60.0, message=None)

        # "d" -> already-scheduled notice -> "y" (cancel it) -> back x3
        admin_session = FakeSession(["s", "n", "d", "y", "b", "b", "b"])
        registry.enter(admin_session)
        try:
            await admin_menu(admin_session, lane, sysop, node_controls=node_controls)
        finally:
            registry.leave(admin_session)

        text = _written_text(admin_session)
        assert "already scheduled" in text
        assert "Scheduled drain cancelled." in text
        assert node_controls.drain_scheduler.is_scheduled() is False
        assert first_task.cancelled()

    asyncio.run(scenario())


def test_drain_screen_declining_the_cancel_offer_replaces_the_existing_schedule(db, lane, sysop):
    async def scenario():
        node_controls = _node_controls()
        registry = node_controls.session_registry
        loop = asyncio.get_running_loop()
        first_task = asyncio.create_task(asyncio.Event().wait())
        node_controls.drain_scheduler.schedule(first_task, deadline=loop.time() + 60.0, message="old message")

        # "d" -> already-scheduled notice -> "n" (don't cancel, continue)
        # -> the ordinary delay/message/confirm prompts for a new one.
        admin_session = FakeSession(["s", "n", "d", "n", "0", "", "y", "b", "b", "b"])
        registry.enter(admin_session)
        try:
            await admin_menu(admin_session, lane, sysop, node_controls=node_controls)
        finally:
            registry.leave(admin_session)
        await asyncio.sleep(0)  # let the replaced task's cancellation actually settle

        assert "Drain started" in _written_text(admin_session)
        assert first_task.cancelled()  # the old one was replaced, not left running
        # The new drain's own delay_seconds=0 means it already ran to
        # completion by this point -- is_scheduled() correctly reports
        # False once a task finishes normally, same as any other
        # completed drain; nothing meaningful is left to observe about
        # its own transient scheduled state here.

    asyncio.run(scenario())


def test_shutdown_screen_now_prompts_for_a_delay_like_drain_does(db, lane, sysop):
    """Design doc -- node management, Thiesi's own request: [S]hutdown
    behaves exactly like [D]rain now, an operator-chosen delay instead
    of a fixed config value with no override."""
    async def scenario():
        node_controls = _node_controls()
        registry = node_controls.session_registry

        admin_session = FakeSession(["s", "n", "s", "g", "0.2", "", "y", "b", "b", "b"])
        registry.enter(admin_session)
        try:
            await admin_menu(admin_session, lane, sysop, node_controls=node_controls)
        finally:
            registry.leave(admin_session)

        assert "Shutdown sequence started." in _written_text(admin_session)
        remaining = node_controls.shutdown_scheduler.remaining_seconds()
        assert remaining is not None and remaining <= 0.25

        node_controls.shutdown_scheduler.cancel()

    asyncio.run(scenario())


def test_shutdown_screen_offers_to_cancel_an_already_scheduled_shutdown(db, lane, sysop):
    async def scenario():
        node_controls = _node_controls()
        node_controls.maintenance.activate()  # a real scheduled shutdown would have done this
        loop = asyncio.get_running_loop()
        first_task = asyncio.create_task(asyncio.Event().wait())
        node_controls.shutdown_scheduler.schedule(first_task, deadline=loop.time() + 60.0, message=None)

        admin_session = FakeSession(["s", "n", "s", "y", "b", "b", "b"])
        node_controls.session_registry.enter(admin_session)
        try:
            await admin_menu(admin_session, lane, sysop, node_controls=node_controls)
        finally:
            node_controls.session_registry.leave(admin_session)

        text = _written_text(admin_session)
        assert "already scheduled" in text
        assert "Scheduled shutdown cancelled." in text
        assert node_controls.shutdown_scheduler.is_scheduled() is False
        assert first_task.cancelled()
        # Cancelling a *scheduled* shutdown must reopen new-login
        # admission -- see MaintenanceMode.deactivate()'s own docstring.
        assert node_controls.maintenance.is_active() is False

    asyncio.run(scenario())


def test_shutdown_screen_refuses_to_cancel_a_signal_triggered_shutdown(db, lane, sysop):
    """Issue #108: a SIGTERM/SIGINT-triggered shutdown (`cancellable=
    False`, matching what `netbbs.__main__._install_signal_handlers`
    actually registers) must not be cancellable -- or silently
    replaceable -- from the in-BBS node menu. Contrast with
    `test_shutdown_screen_offers_to_cancel_an_already_scheduled_
    shutdown` above, the SysOp-created case, which remains fully
    cancellable."""
    async def scenario():
        node_controls = _node_controls()
        node_controls.maintenance.activate()  # a real triggered shutdown would have done this
        loop = asyncio.get_running_loop()
        first_task = asyncio.create_task(asyncio.Event().wait())
        node_controls.shutdown_scheduler.schedule(
            first_task, deadline=loop.time() + 60.0, message=None, source="sigterm", cancellable=False
        )

        # No "y" in this script at all -- the "Cancel it?" prompt must
        # never be reached, so there is nothing here to answer.
        admin_session = FakeSession(["s", "n", "s", "b", "b", "b"])
        node_controls.session_registry.enter(admin_session)
        try:
            await admin_menu(admin_session, lane, sysop, node_controls=node_controls)
        finally:
            node_controls.session_registry.leave(admin_session)

        text = _written_text(admin_session)
        assert "triggered externally" in text
        assert "SIGTERM" in text
        assert "cannot be cancelled or replaced" in text
        assert "Cancel it?" not in text
        assert "Scheduled shutdown cancelled." not in text
        # Nothing was touched: still scheduled, task still alive, maintenance untouched.
        assert node_controls.shutdown_scheduler.is_scheduled() is True
        assert not first_task.cancelled()
        assert node_controls.maintenance.is_active() is True

        first_task.cancel()
        await asyncio.gather(first_task, return_exceptions=True)

    asyncio.run(scenario())


def test_node_menu_shows_maintenance_and_schedule_status(db, lane, sysop):
    async def scenario():
        node_controls = _node_controls()
        node_controls.maintenance.enable_lockdown()
        loop = asyncio.get_running_loop()
        drain_task = asyncio.create_task(asyncio.Event().wait())
        node_controls.drain_scheduler.schedule(drain_task, deadline=loop.time() + 90.0, message=None)

        session = FakeSession(["s", "n", "b", "b", "b"])
        await admin_menu(session, lane, sysop, node_controls=node_controls)

        text = _written_text(session)
        assert "Maintenance mode: ON" in text
        assert "Drain scheduled" in text

        drain_task.cancel()
        await asyncio.gather(drain_task, return_exceptions=True)

    asyncio.run(scenario())


def test_node_menu_status_line_notes_a_signal_triggered_shutdown_cannot_be_cancelled(db, lane, sysop):
    """Issue #108: the `[N]ode` menu's own status line (distinct from
    `_shutdown_screen`'s message, checked above) must also surface *why*
    a scheduled shutdown can't be cancelled here, not just that one is
    scheduled -- a SysOp glancing at this screen shouldn't need to enter
    `[S]hutdown` at all to learn that."""
    async def scenario():
        node_controls = _node_controls()
        loop = asyncio.get_running_loop()
        shutdown_task = asyncio.create_task(asyncio.Event().wait())
        node_controls.shutdown_scheduler.schedule(
            shutdown_task, deadline=loop.time() + 30.0, message=None, source="sigint", cancellable=False
        )

        session = FakeSession(["s", "n", "b", "b", "b"])
        await admin_menu(session, lane, sysop, node_controls=node_controls)

        text = _written_text(session)
        assert "Shutdown scheduled" in text
        assert "SIGINT" in text
        assert "cannot be cancelled" in text

        shutdown_task.cancel()
        await asyncio.gather(shutdown_task, return_exceptions=True)

    asyncio.run(scenario())


# -- [L]ock & drain (design doc §13.8, Thiesi's own dogfood-testing report) --
# -- the combined toggle that engages maintenance mode and a drain together --


def test_node_menu_shows_lock_and_drain_option(db, lane, sysop):
    node_controls = _node_controls()
    session = FakeSession(["s", "n", "b", "b", "b"])
    asyncio.run(admin_menu(session, lane, sysop, node_controls=node_controls))
    assert "ock & drain" in _written_text(session)


def test_lock_and_drain_screen_engages_lockdown_and_schedules_drain(db, lane, sysop):
    async def scenario():
        node_controls = _node_controls()
        registry = node_controls.session_registry

        other = FakeSession()
        other_task = asyncio.create_task(_hold_registered(registry, other))
        await asyncio.sleep(0)

        admin_session = FakeSession(["s", "n", "l", "0", "", "y", "b", "b", "b"])
        admin_task = asyncio.create_task(
            _run_admin_session_as_its_own_task(admin_session, lane, sysop, node_controls, registry)
        )
        await asyncio.wait_for(admin_task, timeout=2.0)
        await _wait_until_done(other_task)

        assert node_controls.maintenance.is_lockdown_active() is True
        assert "Locked --" in _written_text(admin_session)
        assert other_task.cancelled()

    asyncio.run(scenario())


def test_lock_and_drain_screen_rejects_a_negative_delay(db, lane, sysop):
    node_controls = _node_controls()
    session = FakeSession(["s", "n", "l", "-5", "b", "b", "b"])
    asyncio.run(admin_menu(session, lane, sysop, node_controls=node_controls))
    assert "cannot be negative" in _written_text(session)
    assert node_controls.maintenance.is_lockdown_active() is False


def test_lock_and_drain_screen_rejects_a_non_numeric_delay(db, lane, sysop):
    node_controls = _node_controls()
    session = FakeSession(["s", "n", "l", "soon", "b", "b", "b"])
    asyncio.run(admin_menu(session, lane, sysop, node_controls=node_controls))
    assert "Not a number" in _written_text(session)
    assert node_controls.maintenance.is_lockdown_active() is False


def test_lock_and_drain_screen_declined_final_confirmation_leaves_lockdown_off(db, lane, sysop):
    node_controls = _node_controls()
    session = FakeSession(["s", "n", "l", "0", "", "n", "b", "b", "b"])
    asyncio.run(admin_menu(session, lane, sysop, node_controls=node_controls))
    assert "Cancelled." in _written_text(session)
    assert node_controls.maintenance.is_lockdown_active() is False


def test_lock_and_drain_screen_offers_to_cancel_a_bare_already_scheduled_drain(db, lane, sysop):
    """Engaging while a plain [D]rain (no lockdown) is already scheduled
    reuses [D]rain's own "already scheduled -- cancel it?" sub-flow
    verbatim, for consistency."""
    async def scenario():
        node_controls = _node_controls()
        loop = asyncio.get_running_loop()
        drain_task = asyncio.create_task(asyncio.Event().wait())
        node_controls.drain_scheduler.schedule(drain_task, deadline=loop.time() + 60.0, message=None)

        session = FakeSession(["s", "n", "l", "y", "b", "b", "b"])
        await admin_menu(session, lane, sysop, node_controls=node_controls)

        text = _written_text(session)
        assert "already scheduled" in text
        assert "Scheduled drain cancelled." in text
        assert node_controls.maintenance.is_lockdown_active() is False
        assert node_controls.drain_scheduler.is_scheduled() is False
        assert drain_task.cancelled()

    asyncio.run(scenario())


def test_lock_and_drain_screen_cancels_lockdown_and_drain_while_still_counting(db, lane, sysop):
    async def scenario():
        node_controls = _node_controls()
        node_controls.maintenance.enable_lockdown(source="lock_and_drain")
        loop = asyncio.get_running_loop()
        drain_task = asyncio.create_task(asyncio.Event().wait())
        node_controls.drain_scheduler.schedule(
            drain_task, deadline=loop.time() + 60.0, message=None, source="lock_and_drain"
        )

        session = FakeSession(["s", "n", "l", "y", "b", "b", "b"])
        await admin_menu(session, lane, sysop, node_controls=node_controls)

        text = _written_text(session)
        assert "Lock & drain cancelled" in text
        assert node_controls.maintenance.is_lockdown_active() is False
        assert node_controls.drain_scheduler.is_scheduled() is False
        assert drain_task.cancelled()

    asyncio.run(scenario())


def test_lock_and_drain_screen_cancel_after_drain_already_finished(db, lane, sysop):
    """Issue #109's own acceptance criterion: once *this composite
    command's own* lockdown is on (`lockdown_source() ==
    "lock_and_drain"`), a second press still offers to unlock even once
    the drain itself has already finished on its own (no entry left in
    `drain_scheduler` at all here) -- ownership of the lock, not the
    drain's own liveness, is what keeps this "active"."""
    node_controls = _node_controls()
    node_controls.maintenance.enable_lockdown(source="lock_and_drain")
    session = FakeSession(["s", "n", "l", "y", "b", "b", "b"])
    asyncio.run(admin_menu(session, lane, sysop, node_controls=node_controls))

    text = _written_text(session)
    assert "already finished" in text
    assert "Lock & drain cancelled" in text
    assert node_controls.maintenance.is_lockdown_active() is False


def test_lock_and_drain_screen_declining_cancel_leaves_it_active(db, lane, sysop):
    async def scenario():
        node_controls = _node_controls()
        node_controls.maintenance.enable_lockdown(source="lock_and_drain")
        loop = asyncio.get_running_loop()
        drain_task = asyncio.create_task(asyncio.Event().wait())
        node_controls.drain_scheduler.schedule(
            drain_task, deadline=loop.time() + 60.0, message=None, source="lock_and_drain"
        )

        session = FakeSession(["s", "n", "l", "n", "b", "b", "b"])
        await admin_menu(session, lane, sysop, node_controls=node_controls)

        text = _written_text(session)
        assert "Leaving lock & drain active." in text
        assert node_controls.maintenance.is_lockdown_active() is True
        assert node_controls.drain_scheduler.is_scheduled() is True

        drain_task.cancel()
        await asyncio.gather(drain_task, return_exceptions=True)

    asyncio.run(scenario())


def test_lock_and_drain_screen_still_starts_a_drain_when_maintenance_was_enabled_independently(db, lane, sysop):
    """Issue #109's own concrete bug report: a SysOp enables plain
    `[M]aintenance mode` first, then presses `[L]ock & drain` intending
    to clear current non-SysOps. The old, `is_lockdown_active()`-only
    check reported the composite as "already active" and started no
    drain at all. It must now recognize this lockdown wasn't its own and
    still start the requested drain."""
    async def scenario():
        node_controls = _node_controls()
        node_controls.maintenance.enable_lockdown()  # plain [M], default source="maintenance"

        session = FakeSession(["s", "n", "l", "0", "", "y", "b", "b", "b"])
        await admin_menu(session, lane, sysop, node_controls=node_controls)

        text = _written_text(session)
        assert "already on (enabled independently" in text
        assert "Drain started" in text
        assert "left as-is" in text
        assert "Lock & drain is active" not in text
        assert "Locked --" not in text

        # The drain was genuinely started and tagged as this command's
        # own, but the pre-existing lock was never reclaimed.
        assert node_controls.drain_scheduler.is_scheduled() is True
        assert node_controls.drain_scheduler.source() == "lock_and_drain"
        assert node_controls.maintenance.is_lockdown_active() is True
        assert node_controls.maintenance.lockdown_source() == "maintenance"

    asyncio.run(scenario())


def test_lock_and_drain_screen_never_disables_maintenance_that_predates_it(db, lane, sysop):
    """Issue #109's own acceptance criterion, made explicit: once a
    drain has been added on top of independently-enabled maintenance
    (the scenario above), a later visit to this screen must not report
    itself as "active" (it still doesn't own the lock) and must never
    offer -- let alone perform -- disabling that pre-existing lock."""
    async def scenario():
        node_controls = _node_controls()
        node_controls.maintenance.enable_lockdown()  # plain [M], pre-dates lock & drain
        loop = asyncio.get_running_loop()
        drain_task = asyncio.create_task(asyncio.Event().wait())
        node_controls.drain_scheduler.schedule(
            drain_task, deadline=loop.time() + 60.0, message=None, source="lock_and_drain"
        )

        # Revisiting the screen: not "Lock & drain is active" (it never
        # owned the lock), but the ordinary "a drain is already
        # scheduled -- cancel it?" sub-flow, answered yes.
        session = FakeSession(["s", "n", "l", "y", "b", "b", "b"])
        await admin_menu(session, lane, sysop, node_controls=node_controls)

        text = _written_text(session)
        assert "Lock & drain is active" not in text
        assert "Scheduled drain cancelled." in text

        # The drain this command owned is gone; the independently-
        # enabled lock it never owned is completely untouched.
        assert node_controls.drain_scheduler.is_scheduled() is False
        assert drain_task.cancelled()
        assert node_controls.maintenance.is_lockdown_active() is True
        assert node_controls.maintenance.lockdown_source() == "maintenance"

    asyncio.run(scenario())


# -- boards & areas -------------------------------------------------------


def test_create_board_flow(db, lane, sysop):
    inputs = [
        "m", "m", "c",
        "General", "A general board", "0", "0",
        "n",  # assign a Community? no
        "n",  # assign category? no
        "n",  # pinned? no
        "y",  # moderated? yes
        "",   # max age blank = unlimited
        "",   # min age blank = no gate
        "",   # name requirement blank = no gate
        "b", "b", "b",
    ]
    session = FakeSession(inputs)
    _run(session, lane, sysop)
    from netbbs.boards.boards import list_boards

    boards = list_boards(db)
    assert [b.name for b in boards] == ["General"]
    assert boards[0].moderated is True
    assert "Created board" in _written_text(session)


def test_edit_and_delete_board_flow(db, lane, sysop):
    from netbbs.boards.boards import create_board, list_boards

    create_board(db, "General", creator=sysop)

    # list -> pick(01) -> e(dit) -> new name, blank desc(keep), blank
    # read level(keep), blank write level(keep), n(don't change
    # Community), n(don't change category), y(pin), n(mod),
    # 'none'(unlimited), blank(keep min age), blank(keep name
    # requirement) -> back to detail -> d(elete) -> retype new name ->
    # back x3
    inputs = [
        "m", "m", "l", "0", "1", "e",
        "General2", "", "", "",
        "n", "n", "y", "n", "none",
        "", "",
        "d", "General2",
        "b", "b", "b",
    ]
    session = FakeSession(inputs)
    _run(session, lane, sysop)
    text = _written_text(session)
    assert "Updated 'General2'" in text
    assert "'General2' deleted." in text
    assert list_boards(db) == []


def test_sysop_approves_a_pending_post_with_zero_grants(db, lane, sysop):
    """Proves the has_permission SysOp bypass reaches this real admin
    UI path, not just the library function in isolation."""
    from netbbs.boards.boards import create_board
    from netbbs.boards.posts import create_post, get_post

    alice = create_user(db, "alice", password="hunter2", user_level=10)
    board = create_board(db, "General", creator=sysop, moderated=True)
    post = create_post(db, board, alice, "Hello", "Body text")
    assert post.status == "pending"

    inputs = ["m", "m", "l", "0", "1", "p", "0", "1", "a", "b", "b", "b", "b"]
    session = FakeSession(inputs)
    _run(session, lane, sysop)
    assert "Approved" in _written_text(session)
    assert get_post(db, post.post_id).status == "approved"


# -- linked boards ------------------------------------------------------------


def _link_context():
    from netbbs.link.node_identity import bootstrap_node_identity
    from netbbs.link.protocol import LinkNode
    from netbbs.link.boards import LinkContext

    node_identity = bootstrap_node_identity("roanoke")
    return LinkContext(node_identity=node_identity, link_node=LinkNode(identity=node_identity))


def test_link_this_board_flow(db, lane, sysop):
    from netbbs.boards.boards import create_board
    from netbbs.link.boards import is_board_linked

    board = create_board(db, "General", creator=sysop)
    link_context = _link_context()

    inputs = [
        "m", "m", "l", "0", "1",  # navigate to board detail
        "l",  # [L]ink this board
        "", "",  # recommended min read/write level: keep current (0)
        "",  # recommend moderated? blank = no recommendation
        "",  # recommended max post age: blank = no recommendation
        "", "",  # min age / name requirement: keep current (none)
        "",  # is this a fork of an existing Linked board? blank = no
        "b", "b", "b", "b",
    ]
    session = FakeSession(inputs)
    asyncio.run(admin_menu(session, lane, sysop, link_context=link_context))

    text = _written_text(session)
    assert "Linked 'General'" in text
    assert is_board_linked(db, board)
    assert board.board_id in link_context.link_node.boards
    genesis = link_context.link_node.boards[board.board_id]
    assert genesis.content_id in link_context.link_node.known_event_ids
    assert genesis.payload["origin_fingerprint"] == link_context.node_identity.fingerprint


def test_link_this_board_is_not_offered_once_already_linked(db, lane, sysop):
    from netbbs.boards.boards import create_board
    from netbbs.link.boards import link_board

    board = create_board(db, "General", creator=sysop)
    link_context = _link_context()
    link_board(db, board, node_identity=link_context.node_identity)

    inputs = ["m", "m", "l", "0", "1", "b", "b", "b", "b"]
    session = FakeSession(inputs)
    asyncio.run(admin_menu(session, lane, sysop, link_context=link_context))

    text = _written_text(session)
    assert "Linked: yes" in text
    assert "ink this board" not in text  # the [L]ink option itself is hidden


# -- linked file areas ---------------------------------------------------


def test_link_this_file_area_flow(db, lane, sysop):
    """`netbbs.link.files.link_file_area` existed since issue #89 but,
    unlike `link_board`, was never actually reachable from any live UI
    action -- this proves the missing `[L]ink this file area` call site
    added to the file-area admin screen."""
    from netbbs.files.areas import create_file_area
    from netbbs.link.files import is_area_linked

    area = create_file_area(db, "Docs", creator=sysop)
    link_context = _link_context()

    inputs = [
        "m", "f", "l", "0", "1",  # navigate to file area detail
        "l",  # [L]ink this file area
        "", "",  # recommended min read/write level: keep current (0)
        "",  # recommend moderated? blank = no recommendation
        "",  # recommended max file age: blank = no recommendation
        "", "",  # min age / name requirement: keep current (none)
        "b", "b", "b", "b",
    ]
    session = FakeSession(inputs)
    asyncio.run(admin_menu(session, lane, sysop, link_context=link_context))

    text = _written_text(session)
    assert "Linked 'Docs'" in text
    assert is_area_linked(db, area)
    assert area.area_id in link_context.link_node.file_areas
    genesis = link_context.link_node.file_areas[area.area_id]
    assert genesis.content_id in link_context.link_node.known_event_ids
    assert genesis.payload["origin_fingerprint"] == link_context.node_identity.fingerprint


def test_link_this_file_area_is_not_offered_once_already_linked(db, lane, sysop):
    from netbbs.files.areas import create_file_area
    from netbbs.link.files import link_file_area

    from netbbs.files.areas import list_file_areas

    create_file_area(db, "Docs", creator=sysop)
    link_context = _link_context()
    area = list_file_areas(db)[0]
    link_file_area(db, area, node_identity=link_context.node_identity)

    inputs = ["m", "f", "l", "0", "1", "b", "b", "b", "b"]
    session = FakeSession(inputs)
    asyncio.run(admin_menu(session, lane, sysop, link_context=link_context))

    text = _written_text(session)
    assert "Linked: yes" in text
    assert "ink this file area" not in text  # the [L]ink option itself is hidden


# -- linked channels ------------------------------------------------------


def test_link_this_channel_flow(db, lane, sysop):
    """`netbbs.link.channels.link_channel` existed since issue #87 but,
    unlike `link_board`, was never actually reachable from any live UI
    action -- this proves the missing `[L]ink this channel` call site
    added to the channel admin screen."""
    from netbbs.chat.channels import create_channel
    from netbbs.link.channels import is_channel_linked

    channel = create_channel(db, "Lobby", creator=sysop)
    link_context = _link_context()

    inputs = [
        "m", "n", "l", "0", "1",  # navigate to channel detail
        "l",  # [L]ink this channel
        "",  # recommended minimum level: keep current (0)
        "", "",  # min age / name requirement: keep current (none)
        "b", "b", "b", "b",
    ]
    session = FakeSession(inputs)
    asyncio.run(admin_menu(session, lane, sysop, link_context=link_context))

    text = _written_text(session)
    assert "Linked 'Lobby'" in text
    assert is_channel_linked(db, channel)
    assert channel.channel_id in link_context.link_node.channels
    genesis = link_context.link_node.channels[channel.channel_id]
    assert genesis.content_id in link_context.link_node.known_event_ids
    assert genesis.payload["origin_fingerprint"] == link_context.node_identity.fingerprint


def test_link_this_channel_is_not_offered_once_already_linked(db, lane, sysop):
    from netbbs.chat.channels import create_channel, list_channels
    from netbbs.link.channels import link_channel

    create_channel(db, "Lobby", creator=sysop)
    link_context = _link_context()
    channel = list_channels(db)[0]
    link_channel(db, channel, node_identity=link_context.node_identity)

    inputs = ["m", "n", "l", "0", "1", "b", "b", "b", "b"]
    session = FakeSession(inputs)
    asyncio.run(admin_menu(session, lane, sysop, link_context=link_context))

    text = _written_text(session)
    assert "Linked: yes" in text
    assert "ink this channel" not in text  # the [L]ink option itself is hidden


def _add_fake_peer(link_context, *, descriptor=None):
    """A minimal but real, correctly-shaped `PeerRecord` for a second
    node -- enough for `_transfer_board_origin_screen` to recognize a
    transfer target as a known peer (design doc §13, issue #53).
    `descriptor` defaults to `None` (every existing caller doesn't
    need one) -- pass a real `EndpointDescriptor` (issue #60's Link
    status screen reads `.payload` off it) when a test needs one."""
    from netbbs.link.node_identity import bootstrap_node_identity
    from netbbs.link.protocol import PeerRecord

    peer_identity = bootstrap_node_identity("elsewhere")
    peer = PeerRecord(
        fingerprint=peer_identity.fingerprint,
        root_public_key=bytes(peer_identity.root.verify_key),
        transitions=peer_identity.transitions,
        descriptor=descriptor,
    )
    link_context.link_node.peers[peer.fingerprint] = peer
    return peer


def test_transfer_board_origin_flow(db, lane, sysop):
    from netbbs.boards.boards import create_board
    from netbbs.link.boards import link_board

    board = create_board(db, "General", creator=sysop)
    link_context = _link_context()
    link_board(db, board, node_identity=link_context.node_identity)
    peer = _add_fake_peer(link_context)

    inputs = [
        "m", "m", "l", "0", "1",  # navigate to board detail
        "t",  # [T]ransfer origin
        peer.fingerprint,  # new origin's fingerprint
        "y",  # confirm
        "b", "b", "b", "b",
    ]
    session = FakeSession(inputs)
    asyncio.run(admin_menu(session, lane, sysop, link_context=link_context))

    text = _written_text(session)
    assert "Offer sent" in text
    assert board.board_id in link_context.link_node.pending_origin_transfers
    offer = link_context.link_node.pending_origin_transfers[board.board_id]
    assert offer.payload["new_origin_fingerprint"] == peer.fingerprint
    assert offer.payload["old_origin_fingerprint"] == link_context.node_identity.fingerprint


def test_close_board_flow(db, lane, sysop):
    from netbbs.boards.boards import create_board
    from netbbs.link.boards import is_board_closed, link_board

    board = create_board(db, "General", creator=sysop)
    link_context = _link_context()
    link_board(db, board, node_identity=link_context.node_identity)

    inputs = [
        "m", "m", "l", "0", "1",  # navigate to board detail
        "c",  # [C]lose board
        "archived",  # optional reason
        "y",  # confirm
        "b", "b", "b", "b",
    ]
    session = FakeSession(inputs)
    asyncio.run(admin_menu(session, lane, sysop, link_context=link_context))

    text = _written_text(session)
    assert "closed" in text
    assert is_board_closed(db, board)
    assert board.board_id in link_context.link_node.board_closures


def test_close_board_option_is_hidden_once_already_closed(db, lane, sysop):
    from netbbs.boards.boards import create_board
    from netbbs.link.boards import close_board_if_linked, link_board

    board = create_board(db, "General", creator=sysop)
    link_context = _link_context()
    link_board(db, board, node_identity=link_context.node_identity)
    close_board_if_linked(db, board, node_identity=link_context.node_identity)

    inputs = ["m", "m", "l", "0", "1", "b", "b", "b", "b"]
    session = FakeSession(inputs)
    asyncio.run(admin_menu(session, lane, sysop, link_context=link_context))

    text = _written_text(session)
    assert "lose board" not in text
    assert "ransfer origin" not in text  # closure also suppresses transfer
    assert "Closed: yes" in text


def test_transfer_origin_is_not_offered_once_an_offer_is_outstanding(db, lane, sysop):
    from netbbs.boards.boards import create_board
    from netbbs.link.boards import link_board, offer_board_origin_transfer

    board = create_board(db, "General", creator=sysop)
    link_context = _link_context()
    link_board(db, board, node_identity=link_context.node_identity)
    peer = _add_fake_peer(link_context)
    offer = offer_board_origin_transfer(
        db, board, node_identity=link_context.node_identity, new_origin_fingerprint=peer.fingerprint
    )
    link_context.link_node.pending_origin_transfers[board.board_id] = offer

    inputs = ["m", "m", "l", "0", "1", "b", "b", "b", "b"]
    session = FakeSession(inputs)
    asyncio.run(admin_menu(session, lane, sysop, link_context=link_context))

    text = _written_text(session)
    assert "ransfer origin" not in text
    assert "your own outstanding transfer offer" in text


def test_accept_board_origin_transfer_flow(db, lane, sysop):
    from netbbs.boards.boards import create_board
    from netbbs.link.boards import link_board, offer_board_origin_transfer
    from netbbs.link.node_identity import bootstrap_node_identity

    # A remote node ("elsewhere") is the current origin of a board this
    # node already carries (materialized locally the same way a real
    # sync pass would -- see test_link_boards.py's own materialize_
    # carried_board coverage for that half in isolation).
    remote_identity = bootstrap_node_identity("elsewhere")
    board = create_board(db, "General", creator=sysop)
    link_context = _link_context()
    genesis = link_board(db, board, node_identity=remote_identity)
    # Overwrite the row to look carried, not self-originated, matching
    # what materialize_carried_board would have produced.
    import json
    db.connection.execute(
        "UPDATE boards SET link_genesis_json = ? WHERE id = ?", (json.dumps(genesis.to_dict()), board.id)
    )
    db.connection.commit()

    offer = offer_board_origin_transfer(
        db, board, node_identity=remote_identity, new_origin_fingerprint=link_context.node_identity.fingerprint
    )
    link_context.link_node.pending_origin_transfers[board.board_id] = offer

    inputs = [
        "m", "m", "l", "0", "1",  # navigate to board detail
        "a",  # [A]ccept transfer
        "y",  # confirm
        "b", "b", "b", "b",
    ]
    session = FakeSession(inputs)
    asyncio.run(admin_menu(session, lane, sysop, link_context=link_context))

    text = _written_text(session)
    assert "Accepted" in text
    assert board.board_id not in link_context.link_node.pending_origin_transfers
    assert link_context.link_node.board_origin[board.board_id] == link_context.node_identity.fingerprint

    from netbbs.link.boards import board_origin_fingerprint
    assert board_origin_fingerprint(db, board) == link_context.node_identity.fingerprint


def test_approving_a_pending_post_on_a_linked_board_queues_a_board_post(db, lane, sysop):
    from netbbs.boards.boards import create_board
    from netbbs.boards.posts import create_post
    from netbbs.link.boards import link_board

    alice = create_user(db, "alice", password="hunter2", user_level=10)
    board = create_board(db, "General", creator=sysop, moderated=True)
    link_context = _link_context()
    link_board(db, board, node_identity=link_context.node_identity)
    post = create_post(db, board, alice, "Hello", "Body text")

    inputs = ["m", "m", "l", "0", "1", "p", "0", "1", "a", "b", "b", "b", "b"]
    session = FakeSession(inputs)
    asyncio.run(admin_menu(session, lane, sysop, link_context=link_context))

    row = db.connection.execute(
        "SELECT link_event_json FROM posts WHERE post_id = ?", (post.post_id,)
    ).fetchone()
    assert row["link_event_json"] is not None


def test_create_and_delete_area_flow(db, lane, sysop):
    inputs = [
        "m", "f", "c",
        "Docs", "Documents area", "0", "0",
        "n",  # assign a Community? no
        "n", "n", "n", "",
        "", "",  # min age, name requirement -- both blank, no gate
        "l", "0", "1", "d", "Docs",
        "b", "b", "b",
    ]
    session = FakeSession(inputs)
    _run(session, lane, sysop)
    from netbbs.files.areas import list_file_areas

    text = _written_text(session)
    assert "Created file area 'Docs'." in text
    assert "'Docs' deleted." in text
    assert list_file_areas(db) == []


def test_gc_screen_reclaims_an_orphaned_blob(db, lane, sysop):
    """GitHub issue #35: dry-run report, then explicit confirm, then
    actual reclaim -- driven end to end through the admin UI."""
    import os
    import time

    from netbbs.files.areas import create_file_area
    from netbbs.files.entries import delete_file, upload_file
    from netbbs.files.storage import storage_path_for

    area = create_file_area(db, "Docs", creator=sysop)
    entry = upload_file(db, area, sysop, "file.txt", b"hello")
    blob_path = storage_path_for(db, entry.sha256)
    delete_file(db, entry, deleted_by=sysop)
    backdated = time.time() - 7200  # past the default 1-hour safety age
    os.utime(blob_path, (backdated, backdated))

    inputs = ["m", "f", "g", "y", "b", "b", "b"]
    session = FakeSession(inputs)
    _run(session, lane, sysop)

    text = _written_text(session)
    assert "Would reclaim 1 orphaned blob" in text
    assert "Reclaimed 1 orphaned blob" in text
    assert not blob_path.exists()


def test_gc_screen_declining_confirmation_does_not_delete(db, lane, sysop):
    import os
    import time

    from netbbs.files.areas import create_file_area
    from netbbs.files.entries import delete_file, upload_file
    from netbbs.files.storage import storage_path_for

    area = create_file_area(db, "Docs", creator=sysop)
    entry = upload_file(db, area, sysop, "file.txt", b"hello")
    blob_path = storage_path_for(db, entry.sha256)
    delete_file(db, entry, deleted_by=sysop)
    backdated = time.time() - 7200
    os.utime(blob_path, (backdated, backdated))

    inputs = ["m", "f", "g", "n", "b", "b", "b"]
    session = FakeSession(inputs)
    _run(session, lane, sysop)

    assert blob_path.exists()


def test_gc_screen_with_nothing_to_reclaim_skips_the_confirmation_prompt(db, lane, sysop):
    inputs = ["m", "f", "g", "b", "b", "b"]  # no "y"/"n" needed
    session = FakeSession(inputs)
    _run(session, lane, sysop)
    assert "Would reclaim 0 orphaned blob" in _written_text(session)


def test_sysop_approves_a_pending_file_with_zero_grants(db, lane, sysop):
    from netbbs.files.areas import create_file_area
    from netbbs.files.entries import get_file, upload_file

    alice = create_user(db, "alice", password="hunter2", user_level=10)
    area = create_file_area(db, "Docs", creator=sysop, moderated=True)
    entry = upload_file(db, area, alice, "readme.txt", b"hello")
    assert entry.status == "pending"

    inputs = ["m", "f", "l", "0", "1", "p", "0", "1", "a", "b", "b", "b", "b"]
    session = FakeSession(inputs)
    _run(session, lane, sysop)
    assert "Approved" in _written_text(session)
    assert get_file(db, entry.file_id).status == "approved"


def test_create_and_delete_board_category_flow(db, lane, sysop):
    from netbbs.boards.categories import list_top_level_categories

    inputs = [
        "m", "c", "m", "c",
        "Vintage", "Old computers", "n",  # not a sub-category
        "l", "0", "1", "Vintage",
        "b", "b", "b", "b",
    ]
    session = FakeSession(inputs)
    _run(session, lane, sysop)
    text = _written_text(session)
    assert "Created category 'Vintage'." in text
    assert "'Vintage' deleted." in text
    assert list_top_level_categories(db) == []


def test_grant_and_revoke_moderator_flow(db, lane, sysop):
    from netbbs.boards.boards import create_board
    from netbbs.moderation.roles import BoardPermission, has_permission

    alice = create_user(db, "alice", password="hunter2", user_level=10)
    board = create_board(db, "General", creator=sysop)

    grant_inputs = ["m", "g", "0", "1", "b", "0", "1", "a", "y", "b", "b"]
    session = FakeSession(grant_inputs)
    _run(session, lane, sysop)
    assert "Granted" in _written_text(session)
    assert has_permission(db, alice, object_type="board", object_id=board.id, permission=BoardPermission.APPROVE)

    revoke_inputs = ["m", "r", "0", "1", "b", "0", "1", "y", "b", "b"]
    session2 = FakeSession(revoke_inputs)
    _run(session2, lane, sysop)
    assert "Revoked" in _written_text(session2)
    assert not has_permission(
        db, alice, object_type="board", object_id=board.id, permission=BoardPermission.APPROVE
    )


def test_grant_blanket_across_all_boards(db, lane, sysop):
    from netbbs.boards.boards import create_board
    from netbbs.moderation.roles import BoardPermission, has_permission

    alice = create_user(db, "alice", password="hunter2", user_level=10)
    board = create_board(db, "General", creator=sysop)

    # scope 'x' = blanket across all boards, no board picker needed;
    # 'n' declines scoping the blanket grant to one Community.
    inputs = ["m", "g", "0", "1", "x", "n", "f", "y", "b", "b"]
    session = FakeSession(inputs)
    _run(session, lane, sysop)
    assert "Granted" in _written_text(session)
    assert has_permission(db, alice, object_type="board", object_id=board.id, permission=BoardPermission.DELETE)


# -- channels -------------------------------------------------------------


def test_create_channel_flow(db, lane, sysop):
    inputs = [
        "m", "n", "c",
        "Lobby", "A general channel", "0",
        "n",  # assign a Community? no
        "n",  # assign category? no
        "n",  # pinned? no
        "n",  # hidden? no
        "n",  # members-only? no
        "", "",  # min age, name requirement -- both blank, no gate
        "b", "b", "b",
    ]
    session = FakeSession(inputs)
    _run(session, lane, sysop)
    from netbbs.chat.channels import list_channels

    channels = list_channels(db)
    assert [c.name for c in channels] == ["Lobby"]
    assert "Created channel" in _written_text(session)


def test_edit_and_delete_channel_flow(db, lane, sysop):
    from netbbs.chat.channels import create_channel, list_channels

    create_channel(db, "Lobby", creator=sysop)

    # list -> pick(01) -> e(dit) -> new name, blank desc(keep), blank
    # min level(keep), n(don't change Community), n(don't change
    # category), y(pin), n(hidden), n(members-only), n(allow invites),
    # blank(min age), blank(name requirement) -> back to detail ->
    # d(elete) -> retype new name -> back x3
    inputs = [
        "m", "n", "l", "0", "1", "e",
        "Lobby2", "", "",
        "n", "n", "y", "n", "n", "n",
        "", "",
        "d", "Lobby2",
        "b", "b", "b",
    ]
    session = FakeSession(inputs)
    _run(session, lane, sysop)
    text = _written_text(session)
    assert "Updated 'Lobby2'" in text
    assert "'Lobby2' deleted." in text
    assert list_channels(db) == []


def test_create_and_delete_channel_category_flow(db, lane, sysop):
    from netbbs.chat.categories import list_top_level_categories

    inputs = [
        "m", "c", "c", "c",
        "Vintage", "Old radios", "n",  # not a sub-category
        "l", "0", "1", "Vintage",
        "b", "b", "b", "b",
    ]
    session = FakeSession(inputs)
    _run(session, lane, sysop)
    text = _written_text(session)
    assert "Created category 'Vintage'." in text
    assert "'Vintage' deleted." in text
    assert list_top_level_categories(db) == []


def test_grant_and_revoke_moderator_flow_for_channel(db, lane, sysop):
    """Proves the has_permission SysOp bypass and the channel-scope
    additions to _pick_moderator_scope/preset selection reach this real
    admin UI path, not just the library functions in isolation."""
    from netbbs.chat.channels import create_channel
    from netbbs.moderation.roles import ChannelPermission, has_permission

    alice = create_user(db, "alice", password="hunter2", user_level=10)
    channel = create_channel(db, "Lobby", creator=sysop)

    grant_inputs = ["m", "g", "0", "1", "n", "0", "1", "f", "y", "b", "b"]
    session = FakeSession(grant_inputs)
    _run(session, lane, sysop)
    assert "Granted" in _written_text(session)
    assert has_permission(
        db, alice, object_type="channel", object_id=channel.id, permission=ChannelPermission.MODERATE
    )

    revoke_inputs = ["m", "r", "0", "1", "n", "0", "1", "y", "b", "b"]
    session2 = FakeSession(revoke_inputs)
    _run(session2, lane, sysop)
    assert "Revoked" in _written_text(session2)
    assert not has_permission(
        db, alice, object_type="channel", object_id=channel.id, permission=ChannelPermission.MODERATE
    )


def test_grant_blanket_across_all_channels(db, lane, sysop):
    from netbbs.chat.channels import create_channel
    from netbbs.moderation.roles import ChannelPermission, has_permission

    alice = create_user(db, "alice", password="hunter2", user_level=10)
    channel = create_channel(db, "Lobby", creator=sysop)

    # scope 'z' = blanket across all channels, no channel picker needed;
    # 'n' declines scoping the blanket grant to one Community.
    inputs = ["m", "g", "0", "1", "z", "n", "f", "y", "b", "b"]
    session = FakeSession(inputs)
    _run(session, lane, sysop)
    assert "Granted" in _written_text(session)
    assert has_permission(
        db, alice, object_type="channel", object_id=channel.id, permission=ChannelPermission.MANAGE_MEMBERS
    )


# -- Communities (design doc §16) -------------------------------------------


def test_create_community_flow(db, lane, sysop):
    from netbbs.communities import list_communities

    # content menu -> Communities -> create -> name, description ->
    # lands on detail screen (create auto-navigates there, unlike board
    # create) -> back out of detail -> back to community menu -> back x2
    inputs = ["m", "o", "c", "Vintage Computing", "Old iron", "b", "b", "b", "b"]
    session = FakeSession(inputs)
    _run(session, lane, sysop)

    communities = list_communities(db)
    assert [c.name for c in communities] == ["Vintage Computing"]
    assert "Created Community 'Vintage Computing'." in _written_text(session)


def test_edit_and_delete_community_flow(db, lane, sysop):
    from netbbs.communities import create_community, list_communities

    create_community(db, "Politics", creator=sysop)

    # content menu -> Communities -> list -> pick(01) -> e(dit): keep
    # name/desc, hidden=y, default read/write level blank(keep=None),
    # default min age blank(keep=None), default name requirement
    # blank(keep=None) -> back to detail -> d(elete) -> retype name ->
    # deletion returns straight up to the community menu (redraws) ->
    # back x3 (community menu, content menu, admin menu)
    inputs = [
        "m", "o", "l", "0", "1", "e",
        "", "", "y", "", "", "", "",
        "d", "Politics",
        "b", "b", "b",
    ]
    session = FakeSession(inputs)
    _run(session, lane, sysop)

    text = _written_text(session)
    assert "Updated 'Politics'" in text
    assert "'Politics' deleted." in text
    assert list_communities(db) == []


def test_create_board_assigns_a_community(db, lane, sysop):
    from netbbs.boards.boards import list_boards
    from netbbs.communities import create_community

    community = create_community(db, "Vintage Computing", creator=sysop)

    inputs = [
        "m", "m", "c",
        "Amiga", "Old computers", "0", "0",
        "y", "0", "1",  # assign a Community? yes -> pick #01
        "n",  # assign category? no
        "n", "n", "", "", "",
        "b", "b", "b",
    ]
    session = FakeSession(inputs)
    _run(session, lane, sysop)

    board = next(b for b in list_boards(db) if b.name == "Amiga")
    assert board.community_id == community.id


def test_admin_category_picker_leak_prevention(db, lane, sysop):
    from netbbs.boards.boards import create_board
    from netbbs.boards.categories import create_category
    from netbbs.communities import create_community

    politics = create_community(db, "Politics", creator=sysop)
    create_community(db, "Vintage Computing", creator=sysop)  # #02, alphabetically after Politics
    hardware = create_category(db, "Hardware", created_by=sysop)
    create_board(db, "elections", community_id=politics.id, category_id=hardware.id, creator=sysop)

    # content menu -> boards -> create: name, description, read/write
    # levels, assign a Community (yes, pick Vintage Computing, #02),
    # assign a category (yes) -- "Hardware" is only used by a Politics
    # board, so it must not be offered here (design doc §16's
    # admin-side leak prevention): the picker reports no categories
    # exist for this Community rather than showing Hardware.
    inputs = [
        "m", "m", "c",
        "Amiga", "Old computers", "0", "0",
        "y", "0", "2",
        "y",
        "n", "n", "", "", "",
        "b", "b", "b",
    ]
    session = FakeSession(inputs)
    _run(session, lane, sysop)

    text = _written_text(session)
    assert "No categories exist yet." in text
    assert "Hardware" not in text


def test_grant_blanket_scoped_to_a_community(db, lane, sysop):
    from netbbs.boards.boards import create_board
    from netbbs.communities import create_community
    from netbbs.moderation.roles import BoardPermission, has_permission

    alice = create_user(db, "alice", password="hunter2", user_level=10)
    community = create_community(db, "Politics", creator=sysop)
    board = create_board(db, "Elections", community_id=community.id, creator=sysop)
    other_board = create_board(db, "General", creator=sysop)  # not in the Community

    # scope 'x' = blanket across all boards, then 'y' to scope it to one
    # Community, pick #01 (the only one).
    inputs = ["m", "g", "0", "1", "x", "y", "0", "1", "f", "y", "b", "b"]
    session = FakeSession(inputs)
    _run(session, lane, sysop)

    assert "Granted" in _written_text(session)
    assert has_permission(db, alice, object_type="board", object_id=board.id, permission=BoardPermission.DELETE)
    assert not has_permission(
        db, alice, object_type="board", object_id=other_board.id, permission=BoardPermission.DELETE
    )


# -- welcome banner --------------------------------------------------------


def test_welcome_banner_option_appears_in_the_system_submenu(db, lane, sysop):
    # menu_key("W", "elcome banner") highlights the "W" separately, so
    # the contiguous literal text is "elcome banner", not "Welcome banner".
    # Welcome banner now lives in the [S]ystem submenu, not the top-level
    # admin menu.
    session = FakeSession(["s", "b", "b"])
    _run(session, lane, sysop)
    assert "elcome banner" in _written_text(session)


def test_enable_with_no_file_present_shows_friendly_error_and_leaves_flag_disabled(db, lane, sysop):
    from netbbs.net.welcome_banner import is_welcome_banner_enabled

    session = FakeSession(["s", "w", "e", "b", "b", "b"])
    _run(session, lane, sysop)
    assert "No banner file found" in _written_text(session)
    assert is_welcome_banner_enabled(db) is False


def test_enable_with_oversized_file_shows_friendly_error_and_leaves_flag_disabled(db, lane, sysop):
    from netbbs.net.welcome_banner import MAX_BANNER_SIZE_BYTES, banner_path, is_welcome_banner_enabled

    banner_path(db).write_bytes(b"x" * (MAX_BANNER_SIZE_BYTES + 1))
    session = FakeSession(["s", "w", "e", "b", "b", "b"])
    _run(session, lane, sysop)
    assert "over the" in _written_text(session)
    assert "byte limit" in _written_text(session)
    assert is_welcome_banner_enabled(db) is False


def test_enable_with_valid_file_present_succeeds_and_sets_flag(db, lane, sysop):
    from netbbs.net.welcome_banner import banner_path, is_welcome_banner_enabled

    banner_path(db).write_bytes(b"MY CUSTOM BANNER")
    session = FakeSession(["s", "w", "e", "b", "b", "b"])
    _run(session, lane, sysop)
    assert "Welcome banner enabled" in _written_text(session)
    assert is_welcome_banner_enabled(db) is True


def test_disable_reverts_flag_without_deleting_file(db, lane, sysop):
    from netbbs.net.welcome_banner import banner_path, is_welcome_banner_enabled, set_welcome_banner_enabled

    banner_path(db).write_bytes(b"MY CUSTOM BANNER")
    set_welcome_banner_enabled(db, True)

    session = FakeSession(["s", "w", "d", "b", "b", "b"])
    _run(session, lane, sysop)
    assert "Reverted to the default banner" in _written_text(session)
    assert is_welcome_banner_enabled(db) is False
    assert banner_path(db).read_bytes() == b"MY CUSTOM BANNER"


def test_preview_screen_renders_resolved_banner_content(db, lane, sysop):
    from netbbs.net.welcome_banner import banner_path, set_welcome_banner_enabled

    banner_path(db).write_bytes(b"MY DISTINCTIVE BANNER TEXT")
    set_welcome_banner_enabled(db, True)

    session = FakeSession(["s", "w", "p", "b", "b", "b"])
    _run(session, lane, sysop)
    text = _written_text(session)
    assert "MY DISTINCTIVE BANNER TEXT" in text
    assert "(showing your custom file)" in text
    assert "generated truecolor/256-color showcase is intentionally bypassed" in text


def test_preview_screen_when_disabled_shows_default_and_says_so(db, lane, sysop):
    session = FakeSession(["s", "w", "p", "b", "b", "b"])
    _run(session, lane, sysop)
    text = _written_text(session)
    assert "showing the DEFAULT banner" in text
    assert "rendering: 256-color fallback" in text
    assert "enabled=False" in text


def test_edit_option_opens_the_ansi_editor_and_a_save_round_trips_into_banner_path(db, lane, sysop):
    from netbbs.net.welcome_banner import banner_path
    from netbbs.rendering.ansi_art import decode_ansi_bytes
    from netbbs.rendering.ansi_parse import parse_ansi_into_buffer
    from netbbs.rendering.screen_buffer import ScreenBuffer

    session = FakeSession(["s", "w", "x", "A", "CTRL+O", "b", "b", "b"])
    _run(session, lane, sysop)
    assert "Saved" in _written_text(session)

    saved = banner_path(db)
    assert saved.exists()
    buf = ScreenBuffer(80, 24)
    parse_ansi_into_buffer(decode_ansi_bytes(saved.read_bytes()), buf)
    assert buf.get_cell(0, 0).char == "A"

    rows = db.connection.execute(
        "SELECT actor_user_id FROM moderation_log WHERE action = 'edit_welcome_banner'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["actor_user_id"] == sysop.id


def test_edit_then_quit_without_saving_leaves_banner_file_untouched(db, lane, sysop):
    from netbbs.net.welcome_banner import banner_path

    banner_path(db).write_bytes(b"ORIGINAL")

    session = FakeSession(["s", "w", "x", "A", "CTRL+X", "d", "b", "b", "b"])
    _run(session, lane, sysop)
    assert "No changes saved" in _written_text(session)
    assert banner_path(db).read_bytes() == b"ORIGINAL"


# -- self-service registration -----------------------------------------------


def test_list_users_shows_pending_approval_status(db, lane, sysop):
    from netbbs.auth.users import create_user

    create_user(db, "carol", password="hunter2pw", pending_approval=True)
    # carol sorts before sysop alphabetically -- item 01.
    session = FakeSession(["u", "l", "0", "1", "b", "b", "b"])
    _run(session, lane, sysop)
    assert "pending approval" in _written_text(session)


def test_approving_a_pending_user_clears_the_gate(db, lane, sysop):
    from netbbs.auth.users import create_user, list_users

    create_user(db, "carol", password="hunter2pw", pending_approval=True)
    session = FakeSession(["u", "l", "0", "1", "a", "y", "b", "b", "b"])
    _run(session, lane, sysop)
    updated = next(u for u in list_users(db) if u.username == "carol")
    assert updated.pending_approval is False
    assert "approved" in _written_text(session)


def test_declining_the_approve_prompt_leaves_it_pending(db, lane, sysop):
    from netbbs.auth.users import create_user, list_users

    create_user(db, "carol", password="hunter2pw", pending_approval=True)
    session = FakeSession(["u", "l", "0", "1", "a", "n", "b", "b", "b"])
    _run(session, lane, sysop)
    updated = next(u for u in list_users(db) if u.username == "carol")
    assert updated.pending_approval is True


def test_detail_screen_for_a_non_pending_user_has_no_approve_prompt(db, lane, sysop):
    # sysop themselves is the sole (non-pending) user -- picking their
    # own entry must not prompt for approval at all.
    session = FakeSession(["u", "l", "0", "1", "b", "b", "b"])
    _run(session, lane, sysop)
    assert "Approve this account" not in _written_text(session)


def test_detail_screen_can_grant_verify_identity_permission(db, lane, sysop):
    from netbbs.auth.users import list_users

    create_user(db, "carol", password="hunter2pw")
    # carol sorts before sysop alphabetically -- item 01.
    session = FakeSession(["u", "l", "0", "1", "i", "y", "b", "b", "b"])
    _run(session, lane, sysop)
    updated = next(u for u in list_users(db) if u.username == "carol")
    assert updated.can_verify_identity is True
    assert "can now verify identity: yes" in _written_text(session)


def test_detail_screen_can_revoke_verify_identity_permission(db, lane, sysop):
    from netbbs.auth.users import list_users, set_can_verify_identity

    carol = create_user(db, "carol", password="hunter2pw")
    set_can_verify_identity(db, carol, True, changed_by=sysop)
    session = FakeSession(["u", "l", "0", "1", "i", "y", "b", "b", "b"])
    _run(session, lane, sysop)
    updated = next(u for u in list_users(db) if u.username == "carol")
    assert updated.can_verify_identity is False
    assert "can now verify identity: no" in _written_text(session)


def test_registration_settings_screen_defaults_to_open(db, lane, sysop):
    from netbbs.config import RegistrationMode, get_registration_mode

    assert get_registration_mode(db) is RegistrationMode.OPEN
    session = FakeSession(["u", "r", "b", "b", "b"])
    _run(session, lane, sysop)
    assert get_registration_mode(db) is RegistrationMode.OPEN
    assert "open" in _written_text(session).lower()


def test_registration_settings_screen_can_switch_to_approval_required(db, lane, sysop):
    from netbbs.config import RegistrationMode, get_registration_mode

    session = FakeSession(["u", "r", "a", "b", "b"])
    _run(session, lane, sysop)
    assert get_registration_mode(db) is RegistrationMode.APPROVAL_REQUIRED
    assert "approval required" in _written_text(session).lower()


def test_registration_settings_screen_can_switch_to_closed(db, lane, sysop):
    from netbbs.config import RegistrationMode, get_registration_mode

    session = FakeSession(["u", "r", "c", "b", "b"])
    _run(session, lane, sysop)
    assert get_registration_mode(db) is RegistrationMode.CLOSED
    assert "closed" in _written_text(session).lower()


def test_registration_settings_screen_choosing_back_leaves_mode_unchanged(db, lane, sysop):
    from netbbs.config import RegistrationMode, get_registration_mode, set_registration_mode

    set_registration_mode(db, RegistrationMode.APPROVAL_REQUIRED)
    session = FakeSession(["u", "r", "b", "b", "b"])
    _run(session, lane, sysop)
    assert get_registration_mode(db) is RegistrationMode.APPROVAL_REQUIRED


def test_registration_settings_screen_choosing_current_mode_is_a_no_op(db, lane, sysop):
    session = FakeSession(["u", "r", "o", "b", "b"])
    _run(session, lane, sysop)
    assert "Already set to that mode." in _written_text(session)


def test_registration_settings_screen_shows_pending_count(db, lane, sysop):
    from netbbs.auth.users import create_user

    create_user(db, "carol", password="hunter2pw", pending_approval=True)
    session = FakeSession(["u", "r", "b", "b", "b"])
    _run(session, lane, sysop)
    assert "1 account(s) awaiting approval" in _written_text(session)


# -- self-update (design doc §17) --------------------------------------------


def _fake_release(tag: str):
    from netbbs.selfupdate import ReleaseInfo

    return ReleaseInfo(tag_name=tag, tarball_url=f"https://example.invalid/{tag}.tar.gz", published_at="2026-01-01T00:00:00Z")


def test_update_screen_shows_no_prior_check(db, lane, sysop):
    session = FakeSession(["s", "u", "n", "n", "b", "b"])
    _run(session, lane, sysop)
    assert "No check has been run on this node yet." in _written_text(session)


def test_update_screen_declining_check_leaves_state_unchanged(db, lane, sysop):
    from netbbs.selfupdate import get_last_check_summary

    session = FakeSession(["s", "u", "n", "n", "b", "b"])
    _run(session, lane, sysop)
    assert get_last_check_summary(db) == (None, None)


def test_update_screen_reports_up_to_date(db, lane, sysop, monkeypatch):
    import netbbs.net.admin_flow as admin_flow
    from netbbs import __version__
    from netbbs.selfupdate import get_last_check_summary

    async def fake_check(*, fetch=None):
        return _fake_release(f"v{__version__}")

    monkeypatch.setattr(admin_flow, "check_latest_release", fake_check)

    session = FakeSession(["s", "u", "y", "n", "b", "b"])
    _run(session, lane, sysop)

    text = _written_text(session)
    assert "[UP TO DATE]" in text
    assert __version__ in text
    _, outcome = get_last_check_summary(db)
    assert outcome == f"up to date ({__version__})"


def test_update_screen_reports_newer_release_without_auto_applying(db, lane, sysop, monkeypatch):
    import netbbs.net.admin_flow as admin_flow
    from netbbs.selfupdate import get_last_check_summary

    async def fake_check(*, fetch=None):
        return _fake_release("v999.0.0")

    monkeypatch.setattr(admin_flow, "check_latest_release", fake_check)

    session = FakeSession(["s", "u", "y", "n", "b", "b"])
    _run(session, lane, sysop)

    text = _written_text(session)
    assert "[UPDATE AVAILABLE]" in text
    assert "v999.0.0" in text
    assert "Automatic download/apply is not yet available" in text
    _, outcome = get_last_check_summary(db)
    assert outcome == "newer release available: v999.0.0"


def test_update_screen_handles_check_failure_gracefully(db, lane, sysop, monkeypatch):
    """A real SysOp report of a transient network/TLS error traced a gap:
    a failed manual check used to leave `record_check_outcome` uncalled
    entirely, so this screen's own "Last check: ..." line never showed
    that anything had gone wrong. Now recorded the same way a success
    is."""
    import netbbs.net.admin_flow as admin_flow
    from netbbs.selfupdate import UpdateError, get_last_check_summary

    async def fake_check(*, fetch=None):
        raise UpdateError("could not reach the release API: timed out")

    monkeypatch.setattr(admin_flow, "check_latest_release", fake_check)

    session = FakeSession(["s", "u", "y", "n", "b", "b"])
    _run(session, lane, sysop)
    assert "Could not check for updates: could not reach the release API: timed out" in _written_text(session)
    checked_at, outcome = get_last_check_summary(db)
    assert checked_at is not None
    assert outcome == "check failed: could not reach the release API: timed out"


def test_update_screen_toggles_auto_check(db, lane, sysop):
    from netbbs.selfupdate import get_auto_update_check_enabled

    assert get_auto_update_check_enabled(db) is True
    session = FakeSession(["s", "u", "n", "y", "b", "b"])
    _run(session, lane, sysop)
    assert get_auto_update_check_enabled(db) is False
    assert "off" in _written_text(session)


def test_update_screen_declining_toggle_leaves_auto_check_unchanged(db, lane, sysop):
    from netbbs.selfupdate import get_auto_update_check_enabled

    session = FakeSession(["s", "u", "n", "n", "b", "b"])
    _run(session, lane, sysop)
    assert get_auto_update_check_enabled(db) is True


# -- node-wide timestamp display format/timezone ----------------------------


def test_system_menu_shows_the_timestamp_format_option(db, lane, sysop):
    session = FakeSession(["s", "b", "b"])
    _run(session, lane, sysop)
    assert "imestamp format" in _written_text(session)


def test_timestamp_settings_screen_shows_current_format_and_timezone(db, lane, sysop):
    session = FakeSession(["s", "t", "", "", "b", "b"])
    _run(session, lane, sysop)
    text = _written_text(session)
    assert "Current format:" in text
    assert "Current timezone:" in text


def test_timestamp_settings_screen_can_set_a_new_timezone(db, lane, sysop):
    from netbbs.timeutil import resolve_display_preferences

    session = FakeSession(["s", "t", "", "Europe/Berlin", "b", "b"])
    _run(session, lane, sysop)
    _, tz = resolve_display_preferences(db)
    assert tz == "Europe/Berlin"
    assert "Display timezone is now: Europe/Berlin" in _written_text(session)


def test_timestamp_settings_screen_can_set_a_new_format(db, lane, sysop):
    from netbbs.timeutil import resolve_display_preferences

    session = FakeSession(["s", "t", "%Y-%m-%d %H:%M", "", "b", "b"])
    _run(session, lane, sysop)
    fmt, _ = resolve_display_preferences(db)
    assert fmt == "%Y-%m-%d %H:%M"
    assert "Display format is now:" in _written_text(session)


def test_timestamp_settings_screen_blank_leaves_both_unchanged(db, lane, sysop):
    from netbbs.timeutil import resolve_display_preferences

    before = resolve_display_preferences(db)
    session = FakeSession(["s", "t", "", "", "b", "b"])
    _run(session, lane, sysop)
    assert resolve_display_preferences(db) == before


def test_timestamp_settings_screen_rejects_an_invalid_timezone(db, lane, sysop):
    from netbbs.timeutil import resolve_display_preferences

    before = resolve_display_preferences(db)
    session = FakeSession(["s", "t", "", "Not/A/Real/Zone", "b", "b"])
    _run(session, lane, sysop)
    assert resolve_display_preferences(db) == before  # rejected -- nothing changed
    assert "invalid timezone" in _written_text(session).lower()


def test_timestamp_settings_screen_rejects_an_invalid_format(db, lane, sysop):
    from netbbs.timeutil import resolve_display_preferences

    before = resolve_display_preferences(db)
    session = FakeSession(["s", "t", "%Q nonsense", "", "b", "b"])
    _run(session, lane, sysop)
    assert resolve_display_preferences(db) == before
    assert "invalid" in _written_text(session).lower()


def test_timestamp_settings_screen_setting_a_timezone_fixes_the_chat_status_line_clock(db, lane, sysop):
    """End-to-end proof this closes the actual gap Thiesi reported: the
    chat status line's clock (`netbbs.net.chat_flow._render_chat_status_
    line`) reads the node's configured display timezone via the exact
    same `format_for_display` resolution this screen writes to."""
    from netbbs.chat.channels import create_channel
    from netbbs.chat.hub import ChatHub
    from netbbs.chat.presence import PresenceRegistry
    from netbbs.net.chat_flow import _render_chat_status_line
    from netbbs.timeutil import format_for_display, utc_now_iso

    session = FakeSession(["s", "t", "", "Europe/Berlin", "b", "b"])
    _run(session, lane, sysop)

    channel = create_channel(db, "lobby", creator=sysop)
    groups = _render_chat_status_line(db, ChatHub(), PresenceRegistry(), channel, sysop)
    clock_text = groups[-1][0].text
    # Europe/Berlin is never UTC+0 -- if the status line were still
    # reading the hardcoded UTC default despite this screen's write,
    # these two would be identical.
    utc_clock_text = format_for_display(utc_now_iso(), override_format="%H:%M", override_timezone="UTC")
    assert clock_text != utc_clock_text


# -- backup status (design doc §13.4, issue #60's first operational slice) --


def test_backup_status_shows_no_backup_yet_message(db, lane, sysop):
    session = FakeSession(["s", "k", "b", "b"])
    _run(session, lane, sysop)
    assert "No backup has been taken on this node yet." in _written_text(session)


def test_backup_status_shows_last_backup_summary(db, lane, sysop):
    from netbbs.backup import create_backup

    identity_dir = db.path.parent / "netbbs_identity"
    destination = db.path.parent / "backup1"
    create_backup(db_path=db.path, identity_dir=identity_dir, destination=destination)

    session = FakeSession(["s", "k", "b", "b"])
    _run(session, lane, sysop)
    text = _written_text(session)
    assert "Last backup:" in text
    assert str(destination) in text


# -- outbox: work-item inspection/replay/cancel (design doc §13.7) ----------


def test_outbox_option_hidden_without_link_context(db, lane, sysop):
    session = FakeSession(["s", "o", "b", "b"])
    _run(session, lane, sysop)  # _run's admin_menu call passes no link_context
    bell_index = session.written.index("\b \b\a")
    assert session.written[bell_index] == "\b \b\a"


def test_outbox_shows_no_items_yet_message(db, lane, sysop):
    link_context = _link_context()
    session = FakeSession(["s", "o", "b", "b"])
    asyncio.run(admin_menu(session, lane, sysop, link_context=link_context))
    assert "No outbound work items recorded yet." in _written_text(session)


def test_outbox_replays_a_dead_lettered_item(db, lane, sysop):
    from netbbs.link.work_items import KIND_LINK_MAIL_DELIVERY, _MAX_ATTEMPTS, enqueue_work_item, record_failure

    item = enqueue_work_item(db, kind=KIND_LINK_MAIL_DELIVERY, reference_id="msg1", target_fingerprint="fp1")
    for _ in range(_MAX_ATTEMPTS):
        item = record_failure(db, item, error="unreachable")
    assert item.status == "dead_lettered"

    link_context = _link_context()
    session = FakeSession(["s", "o", "0", "1", "y", "b", "b"])
    asyncio.run(admin_menu(session, lane, sysop, link_context=link_context))

    text = _written_text(session)
    assert "dead_lettered, 10 attempt(s)" in text
    assert "Replayed -- status is now 'pending'." in text


def test_outbox_cancels_a_retrying_item(db, lane, sysop):
    from netbbs.link.work_items import KIND_LINK_MAIL_ACK, enqueue_work_item, record_failure

    item = enqueue_work_item(db, kind=KIND_LINK_MAIL_ACK, reference_id="ack1", target_fingerprint="fp1")
    record_failure(db, item, error="connection refused")

    link_context = _link_context()
    session = FakeSession(["s", "o", "0", "1", "y", "b", "b"])
    asyncio.run(admin_menu(session, lane, sysop, link_context=link_context))

    text = _written_text(session)
    assert "Cancelled -- status is now 'cancelled'." in text


# -- Link status (issue #60, narrow scope) -----------------------------------


def test_link_status_option_hidden_without_link_context(db, lane, sysop):
    session = FakeSession(["s", "l", "b", "b"])
    _run(session, lane, sysop)  # _run's admin_menu call passes no link_context
    bell_index = session.written.index("\b \b\a")
    assert session.written[bell_index] == "\b \b\a"


def test_link_status_screen_shows_summary_counts(db, lane, sysop):
    import dataclasses

    from netbbs.link.boards import LinkConfigSnapshot

    link_context = _link_context()
    link_context = dataclasses.replace(
        link_context,
        link_config=LinkConfigSnapshot(
            outgoing_only=True,
            advertised_host=None,
            advertised_port=None,
            seeds=("http://seed.example:7862",),
            sync_interval_seconds=300.0,
            relay_serving_enabled=True,
            max_relay_clients=20,
            max_peers=1000,
            max_carried_boards=500,
            max_carried_channels=500,
        ),
    )
    link_context.link_node.boards["board-1"] = object()
    link_context.link_node.known_event_ids.add("event-1")

    session = FakeSession(["s", "l", "b", "b"])
    asyncio.run(admin_menu(session, lane, sysop, link_context=link_context))

    text = _written_text(session)
    assert link_context.node_identity.fingerprint in text
    assert "Mode: " in text
    assert "[OUTGOING ONLY]" in text
    assert "Configured seeds: 1" in text
    assert "Linked boards: 1" in text
    assert "Known events: 1" in text
    assert "No verified peers." in text


def test_repair_carried_posts_screen_reports_nothing_to_do_when_caught_up(db, lane, sysop):
    link_context = _link_context()

    session = FakeSession(["s", "r", "b", "b"])
    asyncio.run(admin_menu(session, lane, sysop, link_context=link_context))

    text = _written_text(session)
    assert "Repair carried posts" in text
    assert "nothing to do" in text


def test_repair_carried_posts_screen_materializes_a_missing_gap(db, lane, sysop):
    import json

    from netbbs.boards.boards import create_board
    from netbbs.link.boards import link_board
    from netbbs.link.events import build_board_post

    link_context = _link_context()
    board = create_board(db, "General", creator=sysop)
    link_board(db, board, node_identity=link_context.node_identity)

    post = build_board_post(
        signing_identity=link_context.node_identity.signing_key,
        home_node_fingerprint=link_context.node_identity.fingerprint,
        local_user_id="wanderer",
        board_id=board.board_id,
        subject="hello",
        body="world",
        created_at="2026-01-01T00:00:00Z",
    )
    # Simulate the pre-materialization-feature gap directly (this
    # screen's own job is exercising rebuild_carried_post_materialization
    # through the UI, not proving that function's own logic -- see
    # tests/test_link_boards.py for that).
    db.connection.execute(
        "INSERT INTO link_events (content_id, sender_fingerprint, object_type, envelope_json, received_at) "
        "VALUES (?, ?, 'board_post', ?, ?)",
        (post.content_id, "some-peer-fingerprint", json.dumps(post.to_dict()), "2026-01-01T00:00:00Z"),
    )
    db.connection.commit()

    session = FakeSession(["s", "r", "b", "b"])
    asyncio.run(admin_menu(session, lane, sysop, link_context=link_context))

    text = _written_text(session)
    assert "materialized 1 missing row" in text
    row = db.connection.execute("SELECT subject FROM posts WHERE post_id = ?", (post.content_id,)).fetchone()
    assert row["subject"] == "hello"


def test_diagnostic_log_screen_reports_nothing_logged_yet(db, lane, sysop):
    link_context = _link_context()

    session = FakeSession(["s", "d", "b", "b"])
    asyncio.run(admin_menu(session, lane, sysop, link_context=link_context))

    text = _written_text(session)
    assert "Diagnostic log:" in text
    assert "Nothing logged yet." in text


def test_diagnostic_log_screen_lists_and_shows_entry_detail(db, lane, sysop):
    link_context = _link_context()
    db.connection.execute(
        "INSERT INTO link_diagnostic_log (level, logger_name, message, created_at) "
        "VALUES ('WARNING', 'netbbs.link.sync', 'could not complete hello with seed X', '2026-01-01T00:00:00Z')"
    )
    db.connection.commit()

    session = FakeSession(["s", "d", "y", "0", "1", "b", "b"])  # "y" keeps the newest-first default
    asyncio.run(admin_menu(session, lane, sysop, link_context=link_context))

    text = _written_text(session)
    assert "netbbs.link.sync" in text
    assert "could not complete hello with seed X" in text
    assert "WARNING" in text


def test_diagnostic_log_screen_order_toggle_reverses_display_order(db, lane, sysop):
    """Issue #101a: declining "newest first?" shows the oldest entry
    first instead -- the only other order the toggle offers."""
    link_context = _link_context()
    for i in range(2):
        db.connection.execute(
            "INSERT INTO link_diagnostic_log (level, logger_name, message, created_at) "
            "VALUES ('WARNING', 'netbbs.link.sync', ?, ?)",
            (f"failure {i}", f"2026-01-0{i + 1}T00:00:00Z"),
        )
    db.connection.commit()

    session = FakeSession(["s", "d", "n", "b", "b", "b"])  # "n" -> oldest first
    asyncio.run(admin_menu(session, lane, sysop, link_context=link_context))

    text = _written_text(session)
    # The oldest entry ("failure 0") must appear before the newest
    # ("failure 1") in the rendered list -- proves the toggle actually
    # reordered the displayed rows, not just relabeled them.
    assert text.index("failure 0") < text.index("failure 1")


def test_diagnostic_log_screen_colors_level_by_severity(db, lane, sysop):
    """Issue #101c: the detail view's Level field is colorized, and an
    ERROR entry reads as more urgent (ALERT_COLOR) than a WARNING one
    (WARNING_COLOR) -- not both flattened to the same color."""
    from netbbs.rendering import ALERT_COLOR

    link_context = _link_context()
    db.connection.execute(
        "INSERT INTO link_diagnostic_log (level, logger_name, message, created_at) "
        "VALUES ('ERROR', 'netbbs.link.sync', 'dial failed', '2026-01-01T00:00:00Z')"
    )
    db.connection.commit()

    session = FakeSession(["s", "d", "y", "0", "1", "b", "b"])
    asyncio.run(admin_menu(session, lane, sysop, link_context=link_context))

    text = _written_text(session)
    assert f"Level: {colored('ERROR', fg_color=ALERT_COLOR, bold=True)}" in text


def test_diagnostic_log_tail_screen_shows_seeded_entries_and_stops_on_any_key(db, lane, sysop):
    """Issue #101b: entering [F]ollow shows the existing log immediately
    (the "seed"), and any keystroke ends the tail and returns to the
    System menu -- doesn't require a specific stop key."""
    link_context = _link_context()
    db.connection.execute(
        "INSERT INTO link_diagnostic_log (level, logger_name, message, created_at) "
        "VALUES ('WARNING', 'netbbs.link.sync', 'seeded entry', '2026-01-01T00:00:00Z')"
    )
    db.connection.commit()

    session = FakeSession(["s", "f", "x", "b", "b"])
    asyncio.run(admin_menu(session, lane, sysop, link_context=link_context))

    text = _written_text(session)
    assert "Diagnostic log (live)" in text
    assert "seeded entry" in text
    assert "Settings:" in text  # back at Settings -- tail actually ended


def test_diagnostic_log_tail_screen_appends_entries_written_while_watching(db, lane, monkeypatch):
    """The actual "live" property: an entry written *after* the tail
    screen is already open shows up without backing out and reopening
    it. Drives `_diagnostic_log_tail_screen` directly (not through the
    full scripted admin_menu) since this needs real concurrency --
    inserting a row *while* the tail loop's poll is in flight -- that a
    single ordered FakeSession input queue can't express."""
    from netbbs.net import admin_flow

    poll_interval = 0.02
    monkeypatch.setattr(admin_flow, "_DIAGNOSTIC_TAIL_POLL_INTERVAL_SECONDS", poll_interval)

    db.connection.execute(
        "INSERT INTO link_diagnostic_log (level, logger_name, message, created_at) "
        "VALUES ('WARNING', 'netbbs.link.sync', 'seeded entry', '2026-01-01T00:00:00Z')"
    )
    db.connection.commit()

    class _SlowKeySession(FakeSession):
        # Long enough for several 0.02s poll ticks to fire first -- the
        # whole point is to observe the tail loop pick up a row inserted
        # *after* it started, not just its initial seed.
        async def read_key(self, echo: bool = True) -> str:
            await asyncio.sleep(poll_interval * 5)
            return await super().read_key(echo=echo)

    session = _SlowKeySession(["x"])

    async def scenario():
        task = asyncio.create_task(admin_flow._diagnostic_log_tail_screen(session, lane))
        await asyncio.sleep(poll_interval * 2)
        db.connection.execute(
            "INSERT INTO link_diagnostic_log (level, logger_name, message, created_at) "
            "VALUES ('ERROR', 'netbbs.link.sync', 'new failure while watching', '2026-01-01T00:00:01Z')"
        )
        db.connection.commit()
        await asyncio.wait_for(task, timeout=5.0)

    asyncio.run(scenario())

    text = _written_text(session)
    assert "seeded entry" in text
    assert "new failure while watching" in text


def test_link_status_screen_lists_and_shows_peer_detail(db, lane, sysop):
    from netbbs.link.events import build_endpoint_descriptor
    from netbbs.link.node_identity import bootstrap_node_identity
    from netbbs.link.protocol import PeerRecord

    link_context = _link_context()
    peer_identity = bootstrap_node_identity("elsewhere")
    descriptor = build_endpoint_descriptor(
        signing_identity=peer_identity.signing_key,
        subject_fingerprint=peer_identity.fingerprint,
        addresses=[{"protocol": "tcp", "address": "203.0.113.5", "port": 7862}],
        outgoing_only=False,
        created_at="2026-01-01T00:00:00+00:00",
    )
    peer = PeerRecord(
        fingerprint=peer_identity.fingerprint,
        root_public_key=bytes(peer_identity.root.verify_key),
        transitions=peer_identity.transitions,
        descriptor=descriptor,
    )
    link_context.link_node.peers[peer.fingerprint] = peer

    session = FakeSession(["s", "l", "0", "1", "b", "b"])
    asyncio.run(admin_menu(session, lane, sysop, link_context=link_context))

    text = _written_text(session)
    assert peer.fingerprint in text
    assert "Reliability: 0.50" in text
    assert "Last contact: never" in text
    assert "Addresses:" in text
    assert "203.0.113.5" in text
