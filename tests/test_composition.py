from __future__ import annotations

import asyncio

from netbbs.net.char_input import CANCEL_KEY
from netbbs.net.composition import ReviewAction, edit_line_body, review_composition


class FakeSession:
    def __init__(self, *, lines=(), keys=(), width=80, height=24):
        self._lines = iter(lines)
        self._keys = iter(keys)
        self.written: list[str] = []
        self.terminal_width = width
        self.node_display_name = "NetBBS"
        self.terminal_height = height

    async def write(self, text: str) -> None:
        self.written.append(text)

    async def write_line(self, text: str = "") -> None:
        self.written.append(text + "\n")

    async def read_line(self, **kwargs) -> str:
        try:
            return next(self._lines)
        except StopIteration as exc:
            raise AssertionError("ran out of scripted lines") from exc

    async def read_key(self, **kwargs) -> str:
        try:
            return next(self._keys)
        except StopIteration as exc:
            raise AssertionError("ran out of scripted keys") from exc


def _text(session: FakeSession) -> str:
    return "".join(session.written)


def test_line_editor_can_replace_insert_delete_and_list_submitted_lines():
    session = FakeSession(
        lines=("first", "second", "/list", "/edit 1", "FIRST", "/insert 2", "middle", "/delete 3", "/done")
    )
    body = asyncio.run(edit_line_body(session, initial_text=None, max_bytes=1_000, max_lines=20))

    assert body == "FIRST\nmiddle"
    assert "  1: first" in _text(session)
    assert "Deleted line 3: second" in _text(session)


def test_line_editor_prefills_existing_text_and_can_add_literal_slash_line():
    session = FakeSession(lines=("//signature", "/done"))
    body = asyncio.run(edit_line_body(session, initial_text="hello\nworld", max_bytes=1_000, max_lines=20))
    assert body == "hello\nworld\n/signature"


def test_line_editor_help_is_reachable_via_help_and_question_mark_aliases():
    session = FakeSession(lines=("/help", "/?", "/cancel"))
    body = asyncio.run(edit_line_body(session, initial_text=None, max_bytes=1_000, max_lines=20))
    assert body is None
    assert _text(session).count("Line editor commands:") == 2


def test_line_editor_cancel_is_distinct_from_an_empty_body():
    session = FakeSession(lines=("/cancel",))
    assert asyncio.run(edit_line_body(session, initial_text=None, max_bytes=1_000, max_lines=20)) is None


def test_line_editor_exit_saves_a_draft_and_returns_none(tmp_path):
    """Dogfood feature request, issue #149: /exit is distinct from
    /cancel -- both return None, but /exit leaves the draft on disk."""
    draft_path = tmp_path / "d.draft"
    session = FakeSession(lines=("first line", "/exit"))
    body = asyncio.run(
        edit_line_body(session, initial_text=None, max_bytes=1_000, max_lines=20, draft_path=draft_path)
    )
    assert body is None
    assert draft_path.read_text(encoding="utf-8") == "first line"


def test_line_editor_quit_is_a_synonym_for_exit(tmp_path):
    draft_path = tmp_path / "d.draft"
    session = FakeSession(lines=("first line", "/quit"))
    body = asyncio.run(
        edit_line_body(session, initial_text=None, max_bytes=1_000, max_lines=20, draft_path=draft_path)
    )
    assert body is None
    assert draft_path.read_text(encoding="utf-8") == "first line"


def test_line_editor_exit_is_not_recognized_without_a_draft_path():
    """mail_flow.py and other callers that never pass draft_path keep
    their exact old behavior -- /exit stays an ordinary unknown
    command there, same as before this parameter existed."""
    session = FakeSession(lines=("/exit", "/cancel"))
    body = asyncio.run(edit_line_body(session, initial_text=None, max_bytes=1_000, max_lines=20))
    assert body is None
    assert "Unknown editor command" in _text(session)


def test_line_editor_cancel_deletes_an_existing_draft(tmp_path):
    draft_path = tmp_path / "d.draft"
    draft_path.write_text("stale", encoding="utf-8")
    session = FakeSession(lines=("n", "/cancel"))  # "n" declines resuming the stale draft
    body = asyncio.run(
        edit_line_body(session, initial_text=None, max_bytes=1_000, max_lines=20, draft_path=draft_path)
    )
    assert body is None
    assert not draft_path.exists()


def test_line_editor_offers_recovery_and_done_deletes_the_resumed_draft(tmp_path):
    draft_path = tmp_path / "d.draft"
    draft_path.write_text("recovered text", encoding="utf-8")
    session = FakeSession(lines=("y", "/done"))  # "y" accepts resuming
    body = asyncio.run(
        edit_line_body(session, initial_text=None, max_bytes=1_000, max_lines=20, draft_path=draft_path)
    )
    assert body == "recovered text"
    assert not draft_path.exists()
    assert "A draft from a previous session was found" in _text(session)


def test_line_editor_declining_recovery_deletes_the_stale_draft(tmp_path):
    draft_path = tmp_path / "d.draft"
    draft_path.write_text("stale", encoding="utf-8")
    session = FakeSession(lines=("n", "fresh line", "/done"))  # "n" declines, starts empty instead
    body = asyncio.run(
        edit_line_body(session, initial_text=None, max_bytes=1_000, max_lines=20, draft_path=draft_path)
    )
    assert body == "fresh line"


def test_line_editor_help_mentions_exit_only_when_draft_path_is_given(tmp_path):
    with_draft = FakeSession(lines=("/help", "/cancel"))
    asyncio.run(
        edit_line_body(
            with_draft, initial_text=None, max_bytes=1_000, max_lines=20, draft_path=tmp_path / "d.draft"
        )
    )
    assert "/exit" in _text(with_draft)

    without_draft = FakeSession(lines=("/help", "/cancel"))
    asyncio.run(edit_line_body(without_draft, initial_text=None, max_bytes=1_000, max_lines=20))
    assert "/exit" not in _text(without_draft)


def test_line_editor_rejects_byte_overflow_without_losing_the_draft():
    session = FakeSession(lines=("okay", "€€", "/done"))
    body = asyncio.run(edit_line_body(session, initial_text=None, max_bytes=6, max_lines=20))
    assert body == "okay"
    assert "would be" in _text(session)


def test_review_renders_all_fields_and_returns_explicit_actions():
    session = FakeSession(keys=("x", "t"), width=40)
    action = asyncio.run(
        review_composition(
            session,
            recipient="bob",
            subject="Hello",
            body="first\nsecond",
            commit_key="s",
            commit_label="end",
        )
    )
    text = _text(session)
    assert action is ReviewAction.EDIT_RECIPIENT
    assert "NetBBS / Compose / Review composition" in text
    assert "Check the draft before continuing" in text
    assert "To: " in text and "bob" in text
    assert "Subject: " in text and "Hello" in text
    assert "first\nsecond" in text
    assert "\b" in text  # unsupported key was visibly rejected


def test_review_ctrl_c_is_an_alias_for_cancel():
    """Dogfood feature request, issue #157: an incremental Ctrl-C
    alias for this screen's own [C]ancel action."""
    session = FakeSession(keys=(CANCEL_KEY,))
    action = asyncio.run(
        review_composition(
            session, recipient=None, subject="Subject", body="Body", commit_key="p", commit_label="ost",
        )
    )
    assert action is ReviewAction.CANCEL


def test_post_review_has_no_recipient_action_and_can_commit():
    session = FakeSession(keys=("p",))
    action = asyncio.run(
        review_composition(
            session,
            recipient=None,
            subject="Subject",
            body="Body",
            commit_key="p",
            commit_label="ost",
        )
    )
    assert action is ReviewAction.COMMIT
    assert "To:" not in _text(session)
