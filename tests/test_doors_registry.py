"""Tests for netbbs.doors.registry — the SysOp-facing door catalogue.
Mirrors tests/test_file_areas.py's fixture shape."""

from __future__ import annotations

import pytest

from netbbs.auth.users import create_user
from netbbs.communities import create_community
from netbbs.doors import (
    DoorError,
    create_door,
    delete_door,
    get_door_by_name,
    list_doors,
    update_door,
)
from netbbs.moderation.log import list_actions_for_object
from netbbs.storage.database import Database


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "node.db")
    yield database
    database.close()


@pytest.fixture
def sysop(db):
    return create_user(db, "keeper", password="hunter2", user_level=255)


def test_create_door_round_trips_every_field(db, sysop):
    door = create_door(
        db, "Star Trek Trivia", "/opt/doors/sttrivia.sh",
        description="1980s-style trivia game", args=("--fast",),
        min_play_level=10, pinned=True, creator=sysop,
    )
    fetched = get_door_by_name(db, "Star Trek Trivia")
    assert fetched == door
    assert fetched.executable_path == "/opt/doors/sttrivia.sh"
    assert fetched.args == ("--fast",)
    assert fetched.min_play_level == 10
    assert fetched.pinned is True
    assert fetched.community_id is None


def test_create_door_with_no_args_round_trips_empty_tuple(db, sysop):
    door = create_door(db, "Guess The Number", "/opt/doors/guess.py", creator=sysop)
    assert door.args == ()
    assert door.min_play_level == 0
    assert door.pinned is False


def test_create_door_records_moderation_log_entry(db, sysop):
    door = create_door(db, "Lotto", "/opt/doors/lotto.py", creator=sysop)
    entries = list_actions_for_object(db, object_type="door", object_id=door.id)
    assert len(entries) == 1
    assert entries[0].action == "create_door"
    assert entries[0].actor_user_id == sysop.id


def test_duplicate_door_name_is_rejected(db, sysop):
    create_door(db, "Lotto", "/opt/doors/lotto.py", creator=sysop)
    with pytest.raises(DoorError, match="already in use"):
        create_door(db, "Lotto", "/opt/doors/other.py", creator=sysop)


def test_get_door_by_name_raises_for_unknown_door(db):
    with pytest.raises(DoorError, match="no such door"):
        get_door_by_name(db, "Nonexistent")


def test_list_doors_orders_pinned_first_then_alphabetical(db, sysop):
    create_door(db, "Zork", "/opt/doors/zork", creator=sysop)
    create_door(db, "Adventure", "/opt/doors/adv", pinned=True, creator=sysop)
    create_door(db, "Battleship", "/opt/doors/bs", creator=sysop)
    names = [door.name for door in list_doors(db)]
    assert names == ["Adventure", "Battleship", "Zork"]


def test_list_doors_scoped_to_community_excludes_others(db, sysop):
    community = create_community(db, "Gaming", creator=sysop)
    create_door(db, "Community Door", "/opt/doors/a", community_id=community.id, creator=sysop)
    create_door(db, "Global Door", "/opt/doors/b", creator=sysop)
    scoped = list_doors(db, community_id=community.id)
    assert [door.name for door in scoped] == ["Community Door"]
    assert len(list_doors(db)) == 2


def test_update_door_replaces_full_state(db, sysop):
    door = create_door(db, "Lotto", "/opt/doors/lotto.py", min_play_level=0, creator=sysop)
    updated = update_door(
        db, door, name="Lotto", description="Now with jackpots", executable_path="/opt/doors/lotto2.py",
        args=("--jackpot",), min_play_level=20, pinned=True, community_id=None, changed_by=sysop,
    )
    assert updated.description == "Now with jackpots"
    assert updated.executable_path == "/opt/doors/lotto2.py"
    assert updated.args == ("--jackpot",)
    assert updated.min_play_level == 20
    assert updated.pinned is True


def test_delete_door_removes_it_and_records_log_entry(db, sysop):
    door = create_door(db, "Lotto", "/opt/doors/lotto.py", creator=sysop)
    delete_door(db, door, deleted_by=sysop)
    with pytest.raises(DoorError, match="no such door"):
        get_door_by_name(db, "Lotto")
    entries = list_actions_for_object(db, object_type="door", object_id=door.id)
    assert any(entry.action == "delete_door" for entry in entries)
