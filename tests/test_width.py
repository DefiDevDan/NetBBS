"""
Tests for `netbbs.rendering.width` -- display-column-aware text
measurement (design doc, dogfood feature request: international
users reported poor handling of anything beyond 7-bit ASCII).
"""

from __future__ import annotations

import pytest

from netbbs.rendering.width import char_width, display_width, truncate_to_width

# "Hello" romanized greeting in Chinese -- 4 CJK characters, each 2
# columns wide on a real terminal.
_CJK = "你好世界"  # 你好世界


def test_char_width_of_ascii_is_one():
    assert char_width("a") == 1
    assert char_width(" ") == 1


def test_char_width_of_empty_string_is_zero():
    assert char_width("") == 0


def test_char_width_of_cjk_character_is_two():
    for ch in _CJK:
        assert char_width(ch) == 2


def test_char_width_of_combining_mark_is_zero():
    # "e" + COMBINING ACUTE ACCENT (U+0301) -- two code points forming
    # one visual "é", the accent contributing no width of its own.
    e, accent = "é"
    assert char_width(e) == 1
    assert char_width(accent) == 0


def test_char_width_of_control_character_is_zero():
    assert char_width("\x01") == 0


def test_display_width_of_pure_ascii_matches_len():
    text = "hello world"
    assert display_width(text) == len(text)


def test_display_width_of_cjk_text_is_double_len():
    assert display_width(_CJK) == len(_CJK) * 2


def test_display_width_of_mixed_ascii_and_cjk():
    text = "hi " + _CJK  # 3 ASCII columns + 8 CJK columns
    assert display_width(text) == 3 + 8


def test_display_width_ignores_combining_marks():
    base = "café"  # "cafe" + combining acute, reads as "café"
    assert display_width(base) == 4  # not 5


def test_truncate_to_width_pure_ascii_matches_old_len_based_behavior():
    assert truncate_to_width("hello world", 8) == "hello..."
    assert truncate_to_width("short", 20) == "short"


def test_truncate_to_width_rejects_a_width_below_one():
    with pytest.raises(ValueError):
        truncate_to_width("hello", 0)


def test_truncate_to_width_cuts_at_a_display_column_boundary_not_a_character_count():
    # _CJK is 4 characters, 8 display columns total. width=7 forces
    # real truncation; budget is 7 - 3 (for "...") = 4 columns, which
    # at 2 columns/character fits exactly 2 characters -- not the 4 a
    # naive len()-based `text[:4]` slice would have kept (that would
    # still be "truncating" nothing at all, since len(_CJK) is already
    # only 4).
    result = truncate_to_width(_CJK, 7)
    assert result == _CJK[:2] + "..."
    assert display_width(result) <= 7


def test_truncate_to_width_never_returns_something_wider_than_the_budget():
    for width in range(1, 12):
        result = truncate_to_width(_CJK, width)
        assert display_width(result) <= width


def test_truncate_to_width_with_a_width_too_narrow_for_the_ellipsis_itself():
    result = truncate_to_width("hello world", 2)
    assert result == ".."
    assert display_width(result) == 2


def test_truncate_to_width_no_truncation_needed_returns_the_original_text():
    text = _CJK  # width 8
    assert truncate_to_width(text, 8) == text
    assert truncate_to_width(text, 100) == text
