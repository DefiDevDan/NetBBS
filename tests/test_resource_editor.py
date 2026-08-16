"""
Tests for `netbbs.net.resource_editor` -- the shared draft-based
create/edit screen driver (design doc, dogfood feature request) behind
`netbbs.net.admin_flow`'s board/channel/file-area/Community screens.
"""

from __future__ import annotations

import asyncio

import pytest

from netbbs.net.char_input import CANCEL_KEY, HELP_KEY, EditorKey, EditorKeyKind
from netbbs.net.resource_editor import (
    FieldSpec,
    bool_field,
    choice_field,
    choice_step,
    edit_resource_draft,
    text_field,
)
from netbbs.net.session import Session
from netbbs.rendering import menu_key


class FieldError(Exception):
    pass


class FakeSession(Session):
    def __init__(self, inputs: list[str] | None = None):
        self._inputs = list(inputs or [])
        self.written: list[str] = []
        self.terminal_width = 80
        self.terminal_height = 24
        self.peer_address = None

    async def write(self, text: str) -> None:
        self.written.append(text)

    async def write_line(self, text: str = "") -> None:
        self.written.append(text + "\n")

    async def read_key(self, echo: bool = True) -> str:
        return self._inputs.pop(0)

    async def read_line(self, echo: bool = True, history=None, completer=None, **kwargs) -> str:
        return self._inputs.pop(0)

    async def read_editor_key(self):
        raise NotImplementedError

    async def close(self) -> None:
        pass

    async def read_byte(self) -> int | None:
        raise NotImplementedError

    async def write_raw(self, data: bytes) -> None:
        raise NotImplementedError


_EDITOR_KEY_SENTINELS: dict[str, EditorKeyKind] = {
    "ENTER": EditorKeyKind.ENTER,
    "UP": EditorKeyKind.UP,
    "DOWN": EditorKeyKind.DOWN,
    "LEFT": EditorKeyKind.LEFT,
    "RIGHT": EditorKeyKind.RIGHT,
    "BACKSPACE": EditorKeyKind.BACKSPACE,
}


class NavigableFakeSession(FakeSession):
    """Same shape as `FakeSession`, but with a real `read_editor_key`
    (same sentinel convention `tests/test_prose_editor.py`/
    `tests/test_login_flow_fullscreen_editor.py` already use) -- for
    exercising `edit_resource_draft`'s arrow-navigation path, which
    plain `FakeSession`'s `NotImplementedError` stub always falls back
    away from on purpose (proving the *fallback* still works, not the
    arrow path itself)."""

    async def read_editor_key(self) -> EditorKey:
        raw = self._inputs.pop(0)
        if raw in _EDITOR_KEY_SENTINELS:
            return EditorKey(_EDITOR_KEY_SENTINELS[raw])
        if raw.startswith("CTRL+"):
            return EditorKey(EditorKeyKind.CTRL, char=raw[len("CTRL+") :].lower())
        return EditorKey(EditorKeyKind.CHAR, char=raw)


def _written_text(session: FakeSession) -> str:
    return "".join(session.written)


def _name_field() -> FieldSpec:
    return FieldSpec(
        key="name",
        hotkey="n",
        menu_text=menu_key("N", "ame"),
        label="Name",
        render=lambda draft: draft.get("name") or "(blank)",
        prompt=text_field("name", required=True),
    )


def _name_field_with_help() -> FieldSpec:
    return FieldSpec(
        key="name",
        hotkey="n",
        menu_text=menu_key("N", "ame"),
        label="Name",
        render=lambda draft: draft.get("name") or "(blank)",
        prompt=text_field("name", required=True),
        help="A short, unique identifier -- shown throughout the app.",
    )


def _pinned_field() -> FieldSpec:
    return FieldSpec(
        key="pinned",
        hotkey="p",
        menu_text=menu_key("P", "inned"),
        label="Pinned",
        render=lambda draft: "yes" if draft.get("pinned") else "no",
        prompt=bool_field("pinned", "Pinned?"),
    )


_NAME_REQUIREMENT_VALUES = [None, "verified", "verified_and_displayed"]


def _name_requirement_field() -> FieldSpec:
    return FieldSpec(
        key="name_requirement",
        hotkey="q",
        menu_text=menu_key("Q", "uirement", prefix="Name req"),
        label="Name requirement",
        render=lambda draft: draft.get("name_requirement") or "none",
        prompt=choice_field("name_requirement", _NAME_REQUIREMENT_VALUES),
        step=choice_step("name_requirement", _NAME_REQUIREMENT_VALUES),
    )


async def _save_ok(draft: dict) -> str:
    return "saved"


async def _save_dict(draft: dict) -> dict:
    return dict(draft)


def test_save_returns_whatever_save_returns(lane=None):
    async def save(draft):
        return f"saved:{draft['name']}"

    session = FakeSession(["s"])
    result = asyncio.run(
        edit_resource_draft(
            session, lane,
            title="Create thing", fields=[_name_field()], draft={"name": "lobby"},
            save=save, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result == "saved:lobby"


def test_back_discards_the_draft_and_never_calls_save():
    save_calls = []

    async def save(draft):
        save_calls.append(draft)
        return "should not happen"

    session = FakeSession(["b"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Create thing", fields=[_name_field()], draft={"name": "lobby"},
            save=save, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result is None
    assert save_calls == []


def test_ctrl_c_is_an_alias_for_back():
    """Dogfood feature request, issue #157: an incremental Ctrl-C
    alias for this screen's own [B]ack action."""
    save_calls = []

    async def save(draft):
        save_calls.append(draft)
        return "should not happen"

    session = FakeSession([CANCEL_KEY])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Create thing", fields=[_name_field()], draft={"name": "lobby"},
            save=save, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result is None
    assert save_calls == []


# -- dogfood follow-up: confirm before discarding a changed draft ----------


def test_back_on_an_unmodified_draft_needs_no_confirmation():
    # A draft that was never actually touched (the common "opened the
    # wrong menu" case) must back out in one keystroke, same as before
    # this fix -- the confirmation only exists to protect real,
    # unsaved work.
    session = FakeSession(["b"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Create thing", fields=[_name_field()], draft={"name": "lobby"},
            save=lambda draft: None, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result is None
    assert "Discard unsaved changes?" not in _written_text(session)


def test_back_on_a_changed_draft_asks_before_discarding():
    session = FakeSession(["n", "Renamed", "b", "y"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Create thing", fields=[_name_field()], draft={"name": "lobby"},
            save=lambda draft: None, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result is None
    assert "Discard unsaved changes?" in _written_text(session)


def test_declining_the_discard_confirmation_returns_to_the_same_draft():
    # A SysOp who already typed real changes must not lose them to one
    # misplaced [B]ack keystroke -- declining keeps editing with the
    # draft intact.
    save_calls = []

    async def save(draft):
        save_calls.append(dict(draft))
        return "saved"

    session = FakeSession(["n", "Renamed", "b", "n", "s"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Create thing", fields=[_name_field()], draft={"name": "lobby"},
            save=save, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result == "saved"
    assert save_calls == [{"name": "Renamed"}]


def test_selecting_a_field_hotkey_runs_its_prompt_and_updates_the_draft():
    async def save(draft):
        return draft["name"]

    # "n" selects the Name field; "Renamed" types the new value;
    # "s" saves.
    session = FakeSession(["n", "Renamed", "s"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Edit thing", fields=[_name_field()], draft={"name": "lobby"},
            save=save, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result == "Renamed"


def test_a_blank_text_entry_keeps_the_current_draft_value():
    async def save(draft):
        return draft["name"]

    session = FakeSession(["n", "", "s"])  # blank keeps "lobby"
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Edit thing", fields=[_name_field()], draft={"name": "lobby"},
            save=save, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result == "lobby"


def test_save_raising_error_type_shows_a_message_and_keeps_the_draft_intact():
    calls = {"n": 0}

    async def save(draft):
        calls["n"] += 1
        if calls["n"] == 1:
            raise FieldError("name already in use")
        return draft["name"]

    session = FakeSession(["s", "s"])  # first save fails, second (same draft) succeeds
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Create thing", fields=[_name_field()], draft={"name": "lobby"},
            save=save, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result == "lobby"
    assert "Could not save: name already in use" in _written_text(session)


def test_an_unrelated_exception_type_is_not_caught(monkeypatch):
    async def save(draft):
        raise RuntimeError("not a domain error")

    session = FakeSession(["s"])
    with pytest.raises(RuntimeError):
        asyncio.run(
            edit_resource_draft(
                session, None,
                title="Create thing", fields=[_name_field()], draft={"name": "lobby"},
                save=save, error_type=FieldError,
                save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
            )
        )


def test_an_unrecognized_key_is_rejected_and_the_menu_stays_active():
    async def save(draft):
        return draft["name"]

    session = FakeSession(["z", "s"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Create thing", fields=[_name_field()], draft={"name": "lobby"},
            save=save, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result == "lobby"
    assert "\a" in _written_text(session)


def test_bool_field_toggles_via_prompt_yes_no_or_keep():
    async def save(draft):
        return draft["pinned"]

    # "p" selects Pinned, "y" sets it true (read_line fallback since
    # read_editor_key raises NotImplementedError), "s" saves.
    session = FakeSession(["p", "y", "s"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Edit thing", fields=[_pinned_field()], draft={"pinned": False},
            save=save, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result is True


def test_bool_field_bare_enter_keeps_the_current_value():
    async def save(draft):
        return draft["pinned"]

    session = FakeSession(["p", "", "s"])  # bare Enter keeps current (True)
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Edit thing", fields=[_pinned_field()], draft={"pinned": True},
            save=save, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result is True


def test_choice_field_cycles_one_step_per_hotkey_press_without_typing():
    async def save(draft):
        return draft["name_requirement"]

    # "q" presses cycle none -> verified -> verified_and_displayed, no
    # typed input at all (dogfood feature request, issue #153).
    session = FakeSession(["q", "q", "s"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Edit thing", fields=[_name_requirement_field()], draft={"name_requirement": None},
            save=save, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result == "verified_and_displayed"


def test_choice_field_wraps_back_to_the_first_value():
    async def save(draft):
        return draft["name_requirement"]

    session = FakeSession(["q", "s"])  # one press past the last value wraps to none
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Edit thing",
            fields=[_name_requirement_field()],
            draft={"name_requirement": "verified_and_displayed"},
            save=save, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result is None


def test_multiple_fields_render_together_and_can_be_edited_in_any_order():
    async def save(draft):
        return draft

    # Edits Pinned first, then Name, then saves -- proves fields are
    # addressable independently, not in a fixed sequential order.
    session = FakeSession(["p", "y", "n", "general", "s"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Create thing",
            fields=[_name_field(), _pinned_field()],
            draft={"name": "", "pinned": False},
            save=save, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result == {"name": "general", "pinned": True}


# -- Ctrl-H field help (dogfood feature request, issue #150) ----------------


def _pinned_field_with_help() -> FieldSpec:
    return FieldSpec(
        key="pinned",
        hotkey="p",
        menu_text=menu_key("P", "inned"),
        label="Pinned",
        render=lambda draft: "yes" if draft.get("pinned") else "no",
        prompt=bool_field("pinned", "Pinned?"),
        help="Keeps this item at the top of every listing.",
    )


def test_ctrl_h_shows_help_for_fields_that_have_it():
    async def save(draft):
        return draft["name"]

    session = FakeSession([HELP_KEY, "x", "s"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Edit thing", fields=[_name_field(), _pinned_field_with_help()], draft={"name": "lobby"},
            save=save, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result == "lobby"
    text = _written_text(session)
    assert "Pinned" in text
    assert "Keeps this item at the top of every listing." in text


def test_ctrl_h_omits_fields_with_no_help_authored():
    async def save(draft):
        return draft["name"]

    # _name_field() has no `help` -- only Pinned's should appear.
    session = FakeSession([HELP_KEY, "x", "s"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Edit thing", fields=[_name_field(), _pinned_field_with_help()], draft={"name": "lobby"},
            save=save, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result == "lobby"
    text = _written_text(session)
    # "Name" appears as the field's own current-value line either way,
    # so check specifically that no standalone "Name" help heading was
    # printed by the help block itself.
    assert "Keeps this item at the top of every listing." in text
    assert text.count("Pinned") >= 1


def test_ctrl_h_falls_back_to_a_message_when_nothing_has_help():
    async def save(draft):
        return draft["name"]

    session = FakeSession([HELP_KEY, "x", "s"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Edit thing", fields=[_name_field()], draft={"name": "lobby"},
            save=save, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result == "lobby"
    assert "No help is available for this screen yet." in _written_text(session)


def test_ctrl_h_hint_only_shown_when_some_field_has_help():
    async def save(draft):
        return draft["name"]

    with_help = FakeSession(["s"])
    asyncio.run(
        edit_resource_draft(
            with_help, None,
            title="Edit thing", fields=[_pinned_field_with_help()], draft={"name": "lobby", "pinned": False},
            save=save, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert "Ctrl-H for help" in _written_text(with_help)

    without_help = FakeSession(["s"])
    asyncio.run(
        edit_resource_draft(
            without_help, None,
            title="Edit thing", fields=[_name_field()], draft={"name": "lobby"},
            save=save, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert "Ctrl-H for help" not in _written_text(without_help)


# -- dogfood feature request, issue #160: cursor-key navigation ------------


def test_up_from_unselected_highlights_the_last_field():
    session = NavigableFakeSession(["UP", "s"])
    asyncio.run(
        edit_resource_draft(
            session, None,
            title="Create thing",
            fields=[_name_field(), _pinned_field()],
            draft={"name": "lobby", "pinned": False},
            save=_save_ok, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    text = _written_text(session)
    # "> " only appears once the marker is drawn on the (second, last)
    # Pinned field -- not on Name.
    assert "> Pinned" in text
    assert "> Name" not in text


def test_down_from_unselected_highlights_the_first_field():
    session = NavigableFakeSession(["DOWN", "s"])
    asyncio.run(
        edit_resource_draft(
            session, None,
            title="Create thing",
            fields=[_name_field(), _pinned_field()],
            draft={"name": "lobby", "pinned": False},
            save=_save_ok, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    text = _written_text(session)
    assert "> Name" in text
    assert "> Pinned" not in text


def test_navigation_wraps_at_both_ends():
    # Down past the last field wraps to the first; Up past the first
    # wraps to the last.
    session = NavigableFakeSession(["DOWN", "DOWN", "DOWN", "s"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Create thing",
            fields=[_name_field(), _pinned_field()],
            draft={"name": "lobby", "pinned": False},
            save=_save_ok, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result == "saved"
    # Three Downs from unselected: Name -> Pinned -> Name again.
    assert "> Name" in _written_text(session)


def test_space_activates_the_highlighted_field():
    session = NavigableFakeSession(["DOWN", "DOWN", " ", "y", "s"])  # Name, Pinned, toggle it on, confirm
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Create thing",
            fields=[_name_field(), _pinned_field()],
            draft={"name": "lobby", "pinned": False},
            save=_save_dict, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result["pinned"] is True


def test_enter_activates_the_highlighted_field():
    session = NavigableFakeSession(["DOWN", "DOWN", "ENTER", "y", "s"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Create thing",
            fields=[_name_field(), _pinned_field()],
            draft={"name": "lobby", "pinned": False},
            save=_save_dict, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result["pinned"] is True


def test_enter_with_nothing_selected_is_rejected_silently_not_crashed():
    # No field is highlighted yet -- Enter has no target. Must not
    # raise or consume the wrong scripted input; just bells and waits
    # for the next real key.
    session = NavigableFakeSession(["ENTER", "s"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Create thing", fields=[_name_field()], draft={"name": "lobby"},
            save=_save_ok, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result == "saved"
    assert "\a" in _written_text(session)


def test_selection_persists_after_activating_a_field():
    # After Space/Enter edits the highlighted field, the marker stays
    # on that same field rather than resetting -- so a caller can
    # immediately arrow to the next one.
    session = NavigableFakeSession(["DOWN", "DOWN", " ", "y", "UP", "s"])
    asyncio.run(
        edit_resource_draft(
            session, None,
            title="Create thing",
            fields=[_name_field(), _pinned_field()],
            draft={"name": "lobby", "pinned": False},
            save=_save_ok, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    # From Pinned (selected via two Downs, then toggled with Space),
    # one Up must land back on Name -- proving the cursor was still on
    # Pinned right before that Up, not reset to "nothing selected".
    assert "> Name" in _written_text(session)


def test_hotkey_still_works_and_syncs_the_selection_marker():
    session = NavigableFakeSession(["p", "y", "s"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Create thing",
            fields=[_name_field(), _pinned_field()],
            draft={"name": "lobby", "pinned": False},
            save=_save_dict, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result["pinned"] is True
    assert "> Pinned" in _written_text(session)


def test_right_arrow_steps_a_choice_field_forward():
    session = NavigableFakeSession(["DOWN", "DOWN", "DOWN", "RIGHT", "s"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Create thing",
            fields=[_name_field(), _pinned_field(), _name_requirement_field()],
            draft={"name": "lobby", "pinned": False, "name_requirement": None},
            save=_save_dict, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result["name_requirement"] == "verified"


def test_left_arrow_steps_a_choice_field_backward():
    session = NavigableFakeSession(["DOWN", "DOWN", "DOWN", "LEFT", "s"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Create thing",
            fields=[_name_field(), _pinned_field(), _name_requirement_field()],
            draft={"name": "lobby", "pinned": False, "name_requirement": None},
            save=_save_dict, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    # None -> backward wraps to the last value.
    assert result["name_requirement"] == "verified_and_displayed"


def test_left_right_are_a_noop_on_a_field_with_no_step():
    session = NavigableFakeSession(["DOWN", "DOWN", "RIGHT", "LEFT", "s"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Create thing",
            fields=[_name_field(), _pinned_field()],
            draft={"name": "lobby", "pinned": False},
            save=_save_dict, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result["pinned"] is False
    assert "\a" not in _written_text(session)


def test_left_right_with_nothing_selected_is_a_silent_noop():
    session = NavigableFakeSession(["LEFT", "RIGHT", "s"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Create thing", fields=[_name_requirement_field()],
            draft={"name_requirement": None},
            save=_save_dict, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result["name_requirement"] is None
    assert "\a" not in _written_text(session)


def test_ctrl_h_and_ctrl_c_still_work_through_the_navigable_session():
    save_calls = []

    async def save(draft):
        save_calls.append(draft)
        return "should not happen"

    session = NavigableFakeSession(["CTRL+C"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Create thing", fields=[_name_field()], draft={"name": "lobby"},
            save=save, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result is None
    assert save_calls == []


# -- dogfood feature request: Ctrl-H narrows to the highlighted field ------


def test_ctrl_h_shows_only_the_highlighted_fields_help():
    async def save(draft):
        return draft["name"]

    # Both fields have help authored -- Down selects Pinned (the
    # second field); Ctrl-H must show only Pinned's own help, not
    # Name's too, proving this is narrowed rather than falling back to
    # the combined whole-screen list.
    session = NavigableFakeSession(["DOWN", "DOWN", "CTRL+H", "x", "s"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Edit thing", fields=[_name_field_with_help(), _pinned_field_with_help()],
            draft={"name": "lobby"},
            save=save, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result == "lobby"
    text = _written_text(session)
    assert "Keeps this item at the top of every listing." in text
    assert "A short, unique identifier" not in text


def test_ctrl_h_on_a_highlighted_field_with_no_help_says_so_specifically():
    async def save(draft):
        return draft["name"]

    # Down selects Name (no help authored) -- must say so for *that*
    # field, not silently fall back to the whole-screen list (which
    # would include Pinned's help and be misleading about what Ctrl-H
    # was just asked about).
    session = NavigableFakeSession(["DOWN", "CTRL+H", "x", "s"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Edit thing", fields=[_name_field(), _pinned_field_with_help()], draft={"name": "lobby"},
            save=save, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result == "lobby"
    text = _written_text(session)
    assert "No help is available for 'Name'" in text
    assert "Keeps this item at the top of every listing." not in text


def test_ctrl_h_with_nothing_highlighted_still_shows_the_full_list():
    async def save(draft):
        return draft["name"]

    session = NavigableFakeSession(["CTRL+H", "x", "s"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Edit thing", fields=[_name_field(), _pinned_field_with_help()], draft={"name": "lobby"},
            save=save, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result == "lobby"
    assert "Keeps this item at the top of every listing." in _written_text(session)


# -- menu_grid descriptions (issue #160's rollout to this screen) -----------


def _pinned_field_with_brief() -> FieldSpec:
    return FieldSpec(
        key="pinned",
        hotkey="p",
        menu_text=menu_key("P", "inned"),
        label="Pinned",
        render=lambda draft: "yes" if draft.get("pinned") else "no",
        prompt=bool_field("pinned", "Pinned?"),
        brief="Shown at the top of listings",
    )


def test_description_level_off_hides_brief_text_by_default():
    async def save(draft):
        return draft["name"]

    session = FakeSession(["x", "s"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Edit thing", fields=[_name_field(), _pinned_field_with_brief()], draft={"name": "lobby"},
            save=save, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
        )
    )
    assert result == "lobby"
    assert "Shown at the top of listings" not in _written_text(session)


def test_description_level_brief_shows_field_brief_text():
    async def save(draft):
        return draft["name"]

    session = FakeSession(["x", "s"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Edit thing", fields=[_name_field(), _pinned_field_with_brief()], draft={"name": "lobby"},
            save=save, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
            description_level="brief",
        )
    )
    assert result == "lobby"
    assert "Shown at the top of listings" in _written_text(session)


def test_description_level_detailed_prefers_help_over_brief():
    async def save(draft):
        return draft["name"]

    field = FieldSpec(
        key="pinned",
        hotkey="p",
        menu_text=menu_key("P", "inned"),
        label="Pinned",
        render=lambda draft: "yes" if draft.get("pinned") else "no",
        prompt=bool_field("pinned", "Pinned?"),
        brief="Shown at the top of listings",
        help="Keeps this item at the top of every listing, above everything else.",
    )
    session = FakeSession(["x", "s"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Edit thing", fields=[_name_field(), field], draft={"name": "lobby"},
            save=save, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
            description_level="detailed",
        )
    )
    assert result == "lobby"
    text = _written_text(session)
    assert "Keeps this item at the top of every listing, above everything else." in text
    assert "Shown at the top of listings" not in text


def test_description_level_detailed_falls_back_to_brief_without_help():
    async def save(draft):
        return draft["name"]

    session = FakeSession(["x", "s"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Edit thing", fields=[_name_field(), _pinned_field_with_brief()], draft={"name": "lobby"},
            save=save, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
            description_level="detailed",
        )
    )
    assert result == "lobby"
    assert "Shown at the top of listings" in _written_text(session)


def test_description_level_brief_also_describes_save_and_back():
    async def save(draft):
        return draft["name"]

    session = FakeSession(["s"])
    result = asyncio.run(
        edit_resource_draft(
            session, None,
            title="Edit thing", fields=[_name_field()], draft={"name": "lobby"},
            save=save, error_type=FieldError,
            save_menu_text=menu_key("S", "ave"), back_menu_text=menu_key("B", "ack"),
            description_level="brief",
        )
    )
    assert result == "lobby"
    text = _written_text(session)
    assert "Write this draft to the database" in text
    assert "Discard the draft, nothing saved" in text
