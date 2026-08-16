"""Visual-composition regression tests for ordinary terminal screens."""

from __future__ import annotations

import re

import pytest

from netbbs.rendering import MenuEntry, action_bar, badge, empty_state, menu_grid, menu_key, screen_title, visible_width

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


def test_screen_title_cuts_cjk_text_at_a_display_column_boundary():
    """Dogfood report: international users found non-ASCII handling
    poor. A naive character slice (the old `location[:width]`) can
    leave a CJK line *wider* than the terminal, since each character
    is 2 display columns, not 1 -- 8 CJK characters (16 columns) all
    fit inside a character-count budget of 10, overflowing a real
    10-column terminal by 6 columns."""
    text = "你好世界你好世界"  # 8 characters, 16 display columns
    result = screen_title(text, breadcrumb=(), width=10)
    title_line = visible(result).split("\r\n")[0]
    assert visible_width(title_line) <= 10
    assert title_line == text[:5]  # 5 CJK chars = exactly 10 columns


def test_menu_grid_uses_two_columns_at_classic_width():
    result = visible(menu_grid([
        ("Explore", [menu_key("C", "ommunities"), menu_key("F", "ind")]),
        ("You", [menu_key("E", "-mail"), menu_key("P", "rofile")]),
    ], width=80))
    lines = result.split("\r\n")
    assert "EXPLORE" in lines[0] and "YOU" in lines[0]
    assert "[C]ommunities" in lines[1] and "[E]-mail" in lines[1]


def test_menu_grid_collapses_to_one_column_at_minimum_width():
    # Dogfood follow-up (issue #160): a genuine single-column collapse
    # (multiple sections squeezed down to one) gets a standing notice
    # explaining why -- see test_menu_grid_notes_when_collapsed_to_one_
    # column below for the notice itself.
    result = visible(menu_grid([
        ("Explore", [menu_key("C", "ommunities")]),
        ("You", [menu_key("E", "-mail")]),
    ], width=40))
    lines = result.split("\r\n")
    assert lines[:5] == ["EXPLORE", "  [C]ommunities", "", "YOU", "  [E]-mail"]


def test_menu_grid_collapse_notice_respects_width():
    # The notice text is long informational prose, not a fixed-format
    # label -- it must wrap to the terminal width like anything else
    # rendered here, not overflow a narrow terminal unwrapped.
    result = visible(menu_grid([
        ("Explore", [menu_key("C", "ommunities")]),
        ("You", [menu_key("E", "-mail")]),
    ], width=40))
    assert all(visible_width(line) <= 40 for line in result.split("\r\n"))


def test_menu_grid_notes_when_collapsed_to_one_column():
    result = visible(menu_grid([
        ("Explore", [menu_key("C", "ommunities")]),
        ("You", [menu_key("E", "-mail")]),
    ], width=40))
    assert "widen your terminal" in result.lower()


def test_menu_grid_two_sections_at_wide_width_is_not_flagged_as_collapsed():
    # Dogfood follow-up: going from 3 columns to 2 (or simply having
    # only 2 sections) is routine width adaptation almost every real
    # terminal hits -- the classic 80-column default never reaches the
    # 3-column breakpoint at all -- not a degraded state worth a notice.
    result = visible(menu_grid([
        ("Explore", [menu_key("C", "ommunities")]),
        ("You", [menu_key("E", "-mail")]),
    ], width=80))
    assert "widen your terminal" not in result.lower()


def test_menu_grid_uses_three_columns_at_wide_width():
    result = visible(menu_grid([
        ("Explore", [menu_key("C", "ommunities")]),
        ("You", [menu_key("E", "-mail")]),
        ("System", [menu_key("L", "ogoff")]),
    ], width=120))
    lines = result.split("\r\n")
    assert "EXPLORE" in lines[0] and "YOU" in lines[0] and "SYSTEM" in lines[0]
    assert "widen your terminal" not in result.lower()


def test_menu_grid_three_sections_at_classic_width_uses_two_columns_not_three():
    result = visible(menu_grid([
        ("Explore", [menu_key("C", "ommunities")]),
        ("You", [menu_key("E", "-mail")]),
        ("System", [menu_key("L", "ogoff")]),
    ], width=80))
    lines = result.split("\r\n")
    assert "EXPLORE" in lines[0] and "YOU" in lines[0]
    # System is pushed to its own group below, not squeezed onto the
    # first row as a third column.
    assert "SYSTEM" not in lines[0]


def test_menu_grid_empty_title_omits_the_heading_line():
    # An empty title means "one flat group, no heading to show" -- a
    # legitimate shape for a single-purpose menu with nothing to group,
    # not a blank line where a heading would otherwise go.
    result = visible(menu_grid([
        ("", [menu_key("C", "reate"), menu_key("B", "ack")]),
    ], width=80))
    assert result.split("\r\n") == ["  [C]reate", "  [B]ack"]


def test_menu_grid_rejects_unknown_description_level():
    with pytest.raises(ValueError, match="description_level"):
        menu_grid([("Explore", [menu_key("C", "ommunities")])], width=80, description_level="verbose")


def test_menu_grid_plain_string_options_are_unaffected_by_description_level():
    # A bare str option (no MenuEntry, no description text) must render
    # identically regardless of description_level -- there is nothing
    # to show either way, and every existing caller passes plain
    # strings.
    off = menu_grid([("Explore", [menu_key("C", "ommunities")])], width=80, description_level="off")
    brief = menu_grid([("Explore", [menu_key("C", "ommunities")])], width=80, description_level="brief")
    assert off == brief


def test_menu_grid_shows_brief_description_under_its_entry():
    result = visible(menu_grid([
        ("Explore", [MenuEntry(label=menu_key("C", "ommunities"), brief="Browse shared spaces")]),
    ], width=80, description_level="brief"))
    lines = result.split("\r\n")
    assert lines[1] == "  [C]ommunities"
    assert lines[2].strip() == "Browse shared spaces"


def test_menu_grid_description_off_by_default_even_with_menu_entry():
    result = visible(menu_grid([
        ("Explore", [MenuEntry(label=menu_key("C", "ommunities"), brief="Browse shared spaces")]),
    ], width=80))
    assert "Browse shared spaces" not in result


def test_menu_grid_detailed_level_prefers_detailed_text_over_brief():
    result = visible(menu_grid([
        ("Explore", [MenuEntry(
            label=menu_key("C", "ommunities"), brief="Browse shared spaces",
            detailed="Browse spaces shared by other callers, organized by topic.",
        )]),
    ], width=80, description_level="detailed"))
    assert "Browse spaces shared by other callers, organized by topic." in result
    assert "Browse shared spaces" not in result


def test_menu_grid_detailed_level_falls_back_to_brief_when_no_detailed_text():
    result = visible(menu_grid([
        ("Explore", [MenuEntry(label=menu_key("C", "ommunities"), brief="Browse shared spaces")]),
    ], width=80, description_level="detailed"))
    assert "Browse shared spaces" in result


def test_menu_grid_entry_with_no_description_text_shows_no_extra_line():
    result = visible(menu_grid([
        ("Explore", [MenuEntry(label=menu_key("C", "ommunities")), menu_key("F", "ind")]),
    ], width=80, description_level="brief"))
    lines = result.split("\r\n")
    assert lines == ["EXPLORE", "  [C]ommunities", "  [F]ind"]


def test_menu_grid_description_text_is_truncated_to_the_available_column_width():
    # Same class of bug as the collapse-notice width fix: description
    # text is caller-authored prose with no length guarantee, and must
    # not overflow a narrow column just because it wasn't wrapped.
    long_description = "A description far too long to fit on any narrow terminal without truncation"
    result = visible(menu_grid([
        ("Explore", [MenuEntry(label=menu_key("C", "ommunities"), brief=long_description)]),
    ], width=40, description_level="brief"))
    assert all(visible_width(line) <= 40 for line in result.split("\r\n"))


def test_menu_grid_descriptions_forced_off_below_height_floor():
    result = visible(menu_grid([
        ("Explore", [MenuEntry(label=menu_key("C", "ommunities"), brief="Browse shared spaces")]),
    ], width=80, height=10, description_level="brief"))
    assert "Browse shared spaces" not in result
    assert "descriptions hidden" in result.lower()


def test_menu_grid_descriptions_shown_above_height_floor():
    result = visible(menu_grid([
        ("Explore", [MenuEntry(label=menu_key("C", "ommunities"), brief="Browse shared spaces")]),
    ], width=80, height=24, description_level="brief"))
    assert "Browse shared spaces" in result
    assert "descriptions hidden" not in result.lower()


def test_menu_grid_no_height_given_never_suppresses_descriptions():
    # height is optional -- a caller that doesn't pass it (or doesn't
    # know it) must not have descriptions silently disabled.
    result = visible(menu_grid([
        ("Explore", [MenuEntry(label=menu_key("C", "ommunities"), brief="Browse shared spaces")]),
    ], width=80, description_level="brief"))
    assert "Browse shared spaces" in result


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


def test_empty_state_cuts_cjk_title_at_a_display_column_boundary():
    text = "你好世界你好世界"  # 8 characters, 16 display columns
    result = visible(empty_state(text, width=10))
    assert visible_width(result) <= 10
    assert result == text[:5]  # 5 CJK chars = exactly 10 columns


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
