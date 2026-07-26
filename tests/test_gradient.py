"""Tests for netbbs.rendering.gradient."""

from __future__ import annotations

import re

import pytest

from netbbs.rendering.gradient import GRADIENTS, gradient_text

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _visible(text: str) -> str:
    return _ANSI_ESCAPE_RE.sub("", text)


def test_visible_text_is_unchanged():
    assert _visible(gradient_text("hello", "red")) == "hello"
    assert _visible(gradient_text("hello", "red", truecolor=False)) == "hello"


def test_empty_string_returns_empty_string():
    assert gradient_text("", "red") == ""


def test_single_character_uses_first_stop():
    result = gradient_text("a", [(255, 0, 0), (0, 0, 255)])
    assert result == "\x1b[38;2;255;0;0ma\x1b[0m"


def test_first_and_last_character_match_gradient_endpoints():
    result = gradient_text("hello", [(255, 0, 0), (0, 0, 255)])
    assert result.startswith("\x1b[38;2;255;0;0m")
    assert "\x1b[38;2;0;0;255m" in result
    assert result.endswith("\x1b[0m")


def test_unknown_preset_name_raises():
    with pytest.raises(ValueError):
        gradient_text("hello", "not-a-real-gradient")


def test_single_stop_list_raises():
    with pytest.raises(ValueError):
        gradient_text("hello", [(255, 0, 0)])


def test_out_of_range_stop_raises():
    with pytest.raises(ValueError):
        gradient_text("hello", [(255, 0, 0), (0, 0, 300)])


def test_run_collapsing_reduces_escape_count_for_a_flat_gradient():
    # Two identical stops -- every interpolated position rounds to the
    # same color, so the whole string must be a single colored() span,
    # not one per character.
    result = gradient_text("a" * 20, [(10, 20, 30), (10, 20, 30)])
    assert result.count("\x1b[38;2;") == 1


def test_truecolor_false_emits_256_color_sequences():
    result = gradient_text("hello", "red", truecolor=False)
    assert "\x1b[38;5;" in result
    assert "\x1b[38;2;" not in result


def test_sanitize_strips_untrusted_control_characters():
    result = gradient_text("a\x07b", "red")
    assert _visible(result) == "ab"


def test_multi_stop_gradient_interpolates_through_middle_stop():
    stops = [(255, 0, 0), (255, 255, 255), (0, 0, 255)]
    result = gradient_text("abcde", stops)
    assert result.startswith("\x1b[38;2;255;0;0m")
    assert result.endswith("\x1b[38;2;0;0;255me\x1b[0m")


def test_bold_is_applied_to_every_span():
    result = gradient_text("ab", [(255, 0, 0), (0, 0, 255)], bold=True)
    assert result.count("\x1b[1m") == 2


def test_all_presets_are_valid_gradients():
    for name in GRADIENTS:
        result = gradient_text("test", name)
        assert _visible(result) == "test"
