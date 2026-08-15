"""Tests for netbbs.rendering.reflow.truncate."""

from __future__ import annotations

import pytest

from netbbs.rendering.reflow import truncate


def test_short_text_unchanged():
    assert truncate("hello", width=80) == "hello"


def test_text_exactly_at_width_unchanged():
    assert truncate("hello", width=5) == "hello"


def test_long_text_truncated_with_ellipsis():
    result = truncate("hello world", width=8)
    assert len(result) == 8
    assert result.endswith("...")
    assert result == "hello..."


def test_width_too_small_for_ellipsis_truncates_ellipsis_itself():
    result = truncate("hello world", width=2)
    assert result == ".."
    assert len(result) == 2


def test_custom_ellipsis():
    result = truncate("hello world", width=8, ellipsis=">>")
    assert result == "hello >>"
    assert len(result) == 8


def test_rejects_non_positive_width():
    with pytest.raises(ValueError):
        truncate("hello", width=0)
    with pytest.raises(ValueError):
        truncate("hello", width=-1)


def test_empty_string():
    assert truncate("", width=10) == ""


def test_cjk_text_truncates_at_a_display_column_boundary_not_a_character_count():
    """Dogfood report: international users found non-ASCII handling
    poor. `truncate` delegates to `netbbs.rendering.width.
    truncate_to_width` -- each CJK character is 2 display columns, not
    1, so budget math must account for that, not just `len()`."""
    text = "你好世界"  # 4 characters, 8 display columns
    result = truncate(text, width=7)  # budget 4 after "..." fits 2 chars
    assert result == "你好..."
