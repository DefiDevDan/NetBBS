"""
Tests for `netbbs.net.resource_editor` -- the shared draft-based
create/edit screen driver (design doc, dogfood feature request) behind
`netbbs.net.admin_flow`'s board/channel/file-area/Community screens.
"""

from __future__ import annotations

import asyncio

import pytest

from netbbs.net.resource_editor import FieldSpec, bool_field, choice_field, edit_resource_draft, text_field
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


def _pinned_field() -> FieldSpec:
    return FieldSpec(
        key="pinned",
        hotkey="p",
        menu_text=menu_key("P", "inned"),
        label="Pinned",
        render=lambda draft: "yes" if draft.get("pinned") else "no",
        prompt=bool_field("pinned", "Pinned?"),
    )


def _name_requirement_field() -> FieldSpec:
    return FieldSpec(
        key="name_requirement",
        hotkey="q",
        menu_text=menu_key("Q", "uirement", prefix="Name req"),
        label="Name requirement",
        render=lambda draft: draft.get("name_requirement") or "none",
        prompt=choice_field("name_requirement", [None, "verified", "verified_and_displayed"]),
    )


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
