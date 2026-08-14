"""Visual-composition regression tests for ordinary terminal screens."""

from __future__ import annotations

import re

import pytest

from netbbs.rendering import action_bar, badge, empty_state, menu_grid, menu_key, screen_title, visible_width

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def visible(text: str) -> str:
    return _ANSI_RE.sub("", text)


def test_screen_title_shows_location_subtitle_and_ascii_divider():
    result = visible(screen_title("Home", subtitle="alice / mail caught up", width=80))
    assert result.split("\r\n") == [
        "NetBBS / Home",
        "alice / mail caught up",
        "-------------",
    ]


def test_screen_title_truncates_every_visible_line_to_terminal_width():
    result = screen_title("A title far too long", subtitle="also much too long", width=12)
    assert all(visible_width(line) <= 12 for line in result.split("\r\n"))


def test_menu_grid_uses_two_columns_at_classic_width():
    result = visible(menu_grid([
        ("Explore", [menu_key("C", "ommunities"), menu_key("F", "ind")]),
        ("You", [menu_key("E", "-mail"), menu_key("P", "rofile")]),
    ], width=80))
    lines = result.split("\r\n")
    assert "EXPLORE" in lines[0] and "YOU" in lines[0]
    assert "[C]ommunities" in lines[1] and "[E]-mail" in lines[1]


def test_menu_grid_collapses_to_one_column_at_minimum_width():
    result = visible(menu_grid([
        ("Explore", [menu_key("C", "ommunities")]),
        ("You", [menu_key("E", "-mail")]),
    ], width=40))
    assert result.split("\r\n") == [
        "EXPLORE", "  [C]ommunities", "", "YOU", "  [E]-mail",
    ]


def test_action_bar_wraps_only_between_complete_actions():
    result = visible(action_bar([
        menu_key("O", "lder"), menu_key("N", "ewer"), menu_key("B", "ack"),
    ], width=18))
    assert result.split("\r\n") == ["[O]lder  [N]ewer", "[B]ack"]


def test_empty_state_and_badge_use_compact_ascii_safe_copy():
    assert visible(empty_state("No posts yet", detail="Start the conversation.")) == (
        "No posts yet\r\nStart the conversation."
    )
    assert visible(badge("edited")) == "[edited]"


def test_badge_rejects_unknown_tone():
    with pytest.raises(ValueError, match="unknown badge tone"):
        badge("mystery", tone="unknown")


@pytest.mark.parametrize("width", [0, -1])
def test_layout_rejects_non_positive_width(width):
    with pytest.raises(ValueError):
        screen_title("Home", width=width)
    with pytest.raises(ValueError):
        menu_grid([("Explore", ["item"])], width=width)
    with pytest.raises(ValueError):
        action_bar(["item"], width=width)
    with pytest.raises(ValueError):
        empty_state("Nothing", width=width)
