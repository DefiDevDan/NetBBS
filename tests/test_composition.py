from __future__ import annotations

import asyncio

from netbbs.net.composition import ReviewAction, edit_line_body, review_composition


class FakeSession:
    def __init__(self, *, lines=(), keys=(), width=80):
        self._lines = iter(lines)
        self._keys = iter(keys)
        self.written: list[str] = []
        self.terminal_width = width

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


def test_line_editor_cancel_is_distinct_from_an_empty_body():
    session = FakeSession(lines=("/cancel",))
    assert asyncio.run(edit_line_body(session, initial_text=None, max_bytes=1_000, max_lines=20)) is None


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
    assert "To: bob" in text
    assert "Subject: Hello" in text
    assert "first\nsecond" in text
    assert "\b" in text  # unsupported key was visibly rejected


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
