"""
Cleanup-on-delete tests for `netbbs.sort_preferences` overrides:
deleting a Community or a board/channel/file-area category must remove
any per-user sort-preference override scoped to it, the same
application-level "explicit delete, no schema ON DELETE" convention
`netbbs.activity`'s user_follows/user_read_cursors cleanup already
established for `delete_board`/`delete_channel`/`delete_file_area`/
`delete_community` (see `tests/test_activity.py`'s own cleanup tests).
"""

from __future__ import annotations

import pytest

from netbbs.auth.users import create_user
from netbbs.boards.categories import create_category as create_board_category
from netbbs.boards.categories import delete_category as delete_board_category
from netbbs.chat.categories import create_category as create_channel_category
from netbbs.chat.categories import delete_category as delete_channel_category
from netbbs.communities import create_community, delete_community
from netbbs.files.categories import create_category as create_file_area_category
from netbbs.files.categories import delete_category as delete_file_area_category
from netbbs.sort_preferences import get_effective_sort_mode, set_sort_preference
from netbbs.storage.database import Database


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "node.db")
    yield database
    database.close()


@pytest.fixture
def alice(db):
    return create_user(db, "alice", password="hunter2", user_level=10)


def test_deleting_a_community_removes_its_sort_preference_override(db, alice):
    community = create_community(db, "Retro Computing", creator=alice)
    set_sort_preference(db, alice, "channel", "volume", community_id=community.id)

    delete_community(db, community, deleted_by=alice)

    assert db.connection.execute(
        "SELECT 1 FROM user_sort_preferences WHERE community_id = ?", (community.id,)
    ).fetchone() is None
    # Falls all the way back to the hardcoded default -- the community
    # it was scoped to no longer exists to look up by id anyway.
    assert get_effective_sort_mode(db, alice, "channel") == "activity"


def test_deleting_a_board_category_removes_its_sort_preference_override(db, alice):
    category = create_board_category(db, "Amiga", created_by=alice)
    set_sort_preference(db, alice, "board", "volume", category_id=category.id)

    delete_board_category(db, category, deleted_by=alice)

    assert db.connection.execute(
        "SELECT 1 FROM user_sort_preferences WHERE resource_kind = 'board' AND category_id = ?",
        (category.id,),
    ).fetchone() is None


def test_deleting_a_channel_category_removes_its_sort_preference_override(db, alice):
    category = create_channel_category(db, "Amiga", created_by=alice)
    set_sort_preference(db, alice, "channel", "recent", category_id=category.id)

    delete_channel_category(db, category, deleted_by=alice)

    assert db.connection.execute(
        "SELECT 1 FROM user_sort_preferences WHERE resource_kind = 'channel' AND category_id = ?",
        (category.id,),
    ).fetchone() is None


def test_deleting_a_file_area_category_removes_its_sort_preference_override(db, alice):
    category = create_file_area_category(db, "Amiga", created_by=alice)
    set_sort_preference(db, alice, "file_area", "alphabetical", category_id=category.id)

    delete_file_area_category(db, category, deleted_by=alice)

    assert db.connection.execute(
        "SELECT 1 FROM user_sort_preferences WHERE resource_kind = 'file_area' AND category_id = ?",
        (category.id,),
    ).fetchone() is None


def test_deleting_a_board_category_does_not_touch_a_channel_categorys_override_with_the_same_id(db, alice):
    """resource_kind disambiguates category_id (board_categories/
    channel_categories/file_area_categories are separate id sequences,
    per the migration's own docstring) -- a coincidental id collision
    between a board category and a channel category must not cross-
    delete the other kind's override."""
    board_category = create_board_category(db, "Amiga", created_by=alice)
    channel_category = create_channel_category(db, "Amiga", created_by=alice)
    set_sort_preference(db, alice, "board", "volume", category_id=board_category.id)
    set_sort_preference(db, alice, "channel", "recent", category_id=channel_category.id)

    delete_board_category(db, board_category, deleted_by=alice)

    # The channel-scoped row survives regardless of whether the two
    # category ids happened to collide numerically.
    assert get_effective_sort_mode(db, alice, "channel", category_id=channel_category.id) == "recent"
