"""Tests for netbbs.rendering.reflow."""

from __future__ import annotations

import re

import pytest

from netbbs.rendering.ansi import colored
from netbbs.rendering.reflow import colored_truncate, reflow

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _visible(text: str) -> str:
    return _ANSI_ESCAPE_RE.sub("", text)


def test_short_text_unchanged():
    assert reflow("hello world", width=80) == "hello world"


def test_long_line_wraps_at_width():
    text = "word " * 30  # well over 80 chars
    result = reflow(text.strip(), width=20)
    for line in result.split("\n"):
        assert len(line) <= 20


def test_preserves_paragraph_breaks():
    text = "First paragraph here.\n\nSecond paragraph here."
    result = reflow(text, width=80)
    assert "\n\n" in result
    assert "First paragraph here." in result
    assert "Second paragraph here." in result


def test_wraps_each_paragraph_independently():
    long_para = "word " * 30
    text = f"{long_para.strip()}\n\nshort"
    result = reflow(text, width=20)
    paragraphs = result.split("\n\n")
    assert len(paragraphs) == 2
    assert paragraphs[1] == "short"
    for line in paragraphs[0].split("\n"):
        assert len(line) <= 20


def test_empty_string():
    assert reflow("", width=80) == ""


def test_rejects_non_positive_width():
    with pytest.raises(ValueError):
        reflow("hello", width=0)
    with pytest.raises(ValueError):
        reflow("hello", width=-5)


def test_single_long_word_not_broken_mid_word_by_default():
    # textwrap's default behavior can still break extremely long single
    # words if they exceed the width entirely; this test just confirms
    # normal multi-word text doesn't get mangled at a reasonable width.
    text = "supercalifragilisticexpialidocious is a long word"
    result = reflow(text, width=80)
    assert "supercalifragilisticexpialidocious" in result


def test_narrow_width_like_40_columns():
    # Design doc requirement: must degrade gracefully above 40x24 minimum.
    text = "This is a reasonably long sentence that should wrap cleanly."
    result = reflow(text, width=40)
    for line in result.split("\n"):
        assert len(line) <= 40


def test_reflow_wraps_cjk_text_at_display_column_boundaries_not_character_count():
    # Dogfood report: international users found non-ASCII handling poor.
    # No spaces at all -- one long "word" under whitespace-splitting --
    # must still wrap at real column boundaries (2 columns/character),
    # not overflow into one unbroken line the way a len()-based wrap
    # would (12 characters, 24 display columns, all "fitting" under an
    # 8-character-count budget).
    text = "你好世界" * 3
    result = reflow(text, width=8)
    lines = result.split("\n")
    assert len(lines) > 1
    from netbbs.rendering.width import display_width

    for line in lines:
        assert display_width(line) <= 8
    assert "".join(lines) == text


# -- colored_truncate ---------------------------------------------------


def test_colored_truncate_untruncated_colors_every_segment():
    result = colored_truncate([("abc", 51), ("def", None), ("ghi", 220)], width=80)
    assert result == colored("abc", fg_color=51) + "def" + colored("ghi", fg_color=220)
    assert _visible(result) == "abcdefghi"


def test_colored_truncate_skips_empty_segments():
    # An empty segment (e.g. no description on this item) must not emit
    # a stray color-on/color-off pair with nothing between them.
    result = colored_truncate([("abc", 51), ("", 220)], width=80)
    assert result == colored("abc", fg_color=51)


def test_colored_truncate_cuts_across_a_segment_boundary():
    # width=5, ellipsis="..." -> a 2-character budget: all of the first
    # segment ("a") plus one character of the second ("b") survive,
    # each still individually colored, followed by the ellipsis.
    result = colored_truncate([("a", 51), ("bcdef", 220)], width=5)
    assert _visible(result) == "ab..."
    assert result == colored("a", fg_color=51) + colored("b", fg_color=220) + "..."


def test_colored_truncate_never_splits_an_escape_sequence():
    # Regression check for the exact failure mode the module docstring
    # warns about: every SGR "on" code in the output must be paired with
    # a RESET, i.e. no truncation ever lands mid-escape-sequence.
    result = colored_truncate([("hello world", 51), ("more text here", 220)], width=10)
    on_codes = result.count("\x1b[38;5;")
    reset_codes = result.count("\x1b[0m")
    assert on_codes == reset_codes
    assert on_codes > 0


def test_colored_truncate_exactly_at_width_is_unchanged():
    result = colored_truncate([("abcde", 51)], width=5)
    assert result == colored("abcde", fg_color=51)


def test_colored_truncate_cuts_cjk_segments_at_a_display_column_boundary():
    """Dogfood report: international users found non-ASCII handling
    poor. Each CJK character in a segment is 2 display columns, not 1
    -- a picker row's own colored name field (netbbs.net.picker) must
    truncate at a real column boundary, not a character count."""
    # "你好" (2 chars, 4 columns) + "世界" (2 chars, 4 columns) = 8
    # columns total. width=7 forces truncation; budget 4 after "..."
    # fits exactly "你好" from the first segment, none of the second.
    result = colored_truncate([("你好", 51), ("世界", 220)], width=7)
    assert _visible(result) == "你好..."


def test_colored_truncate_width_at_or_below_ellipsis_length():
    assert colored_truncate([("hello", 51)], width=3) == "..."
    assert colored_truncate([("hello", 51)], width=2) == ".."


def test_colored_truncate_rejects_non_positive_width():
    with pytest.raises(ValueError):
        colored_truncate([("hello", 51)], width=0)
