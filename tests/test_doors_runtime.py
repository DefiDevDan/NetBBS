"""Tests for netbbs.doors.runtime — the real subprocess sandbox/relay,
exercised against tiny real Python scripts standing in for doors (not
mocked subprocess calls). FakeSession mirrors tests/test_zmodem.py's own
in-memory duplex-pipe double, the same read_byte/write_raw surface this
module actually uses."""

from __future__ import annotations

import asyncio
import collections
import json
import sys
import textwrap

import pytest

from netbbs.auth.users import create_user
from netbbs.doors import create_door
from netbbs.doors.runtime import DoorRunResult, run_door
from netbbs.net.session import Session, SessionClosedError
from netbbs.storage.database import Database
from netbbs.storage.execution import DatabaseLane


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "node.db")
    yield database
    database.close()


@pytest.fixture
def lane(db):
    database_lane = DatabaseLane(db.path)
    yield database_lane
    database_lane.close()


@pytest.fixture
def player(db):
    return create_user(db, "keeper", password="hunter2", user_level=10)


# -- fake in-memory duplex Session (mirrors test_zmodem.py's own) ----------


class _BytePipe:
    def __init__(self):
        self._buffer: collections.deque[int] = collections.deque()
        self._event = asyncio.Event()
        self._closed = False

    def feed(self, data: bytes) -> None:
        self._buffer.extend(data)
        self._event.set()

    def close(self) -> None:
        self._closed = True
        self._event.set()

    async def read_byte(self) -> int:
        while not self._buffer:
            if self._closed:
                raise SessionClosedError("pipe closed")
            self._event.clear()
            await self._event.wait()
        return self._buffer.popleft()


class FakeSession(Session):
    def __init__(self):
        self._to_door = _BytePipe()
        self.written = bytearray()

    async def write(self, text: str) -> None:
        self.written.extend(text.encode())

    async def write_raw(self, data: bytes) -> None:
        self.written.extend(data)

    async def read_line(self, echo: bool = True) -> str:
        raise NotImplementedError

    async def read_key(self, echo: bool = True) -> str:
        raise NotImplementedError

    async def read_editor_key(self):
        raise NotImplementedError

    async def close(self) -> None:
        self._to_door.close()

    async def read_byte(self) -> int | None:
        return await self._to_door.read_byte()

    def type_in(self, text: str) -> None:
        self._to_door.feed(text.encode())

    def disconnect(self) -> None:
        self._to_door.close()


def _write_script(tmp_path, name: str, body: str):
    path = tmp_path / name
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


async def _run(session, lane, door, player, **kwargs) -> DoorRunResult:
    return await run_door(session, lane, door, player, **kwargs)


def test_door_reads_the_drop_file_and_echoes_input(db, lane, player, tmp_path):
    script = _write_script(
        tmp_path, "echo_door.py",
        """
        import json, os, sys
        info = json.load(open(os.environ["NETBBS_DOOR_INFO"]))
        sys.stdout.write("HELLO " + info["handle"] + "\\n")
        sys.stdout.flush()
        line = sys.stdin.readline()
        sys.stdout.write("ECHO " + line.strip() + "\\n")
        sys.stdout.flush()
        """,
    )
    door = create_door(db, "Echo", sys.executable, args=(str(script),), creator=player)

    session = FakeSession()

    async def scenario():
        task = asyncio.create_task(_run(session, lane, door, player))
        await asyncio.sleep(0.2)
        session.type_in("hi there\n")
        return await task

    result = asyncio.run(scenario())

    assert result.reason == "exited"
    assert result.exit_code == 0
    output = bytes(session.written).decode()
    assert "HELLO keeper" in output
    assert "ECHO hi there" in output


def test_drop_file_carries_terminal_size_and_default_color_depth(db, lane, player, tmp_path):
    script = _write_script(
        tmp_path, "dump_info.py",
        """
        import json, os, sys
        info = json.load(open(os.environ["NETBBS_DOOR_INFO"]))
        sys.stdout.write(json.dumps(info))
        sys.stdout.flush()
        """,
    )
    door = create_door(db, "Dump", sys.executable, args=(str(script),), creator=player)
    session = FakeSession()
    session.terminal_width = 100
    session.terminal_height = 40

    result = asyncio.run(_run(session, lane, door, player))

    assert result.exit_code == 0
    info = json.loads(bytes(session.written).decode())
    assert info["terminal_width"] == 100
    assert info["terminal_height"] == 40
    assert info["color_depth"] == "256"
    assert info["user_id"] == player.id


def test_nonzero_exit_is_reported_as_crashed(db, lane, player, tmp_path):
    script = _write_script(tmp_path, "crash_door.py", "import sys; sys.exit(7)")
    door = create_door(db, "Crasher", sys.executable, args=(str(script),), creator=player)
    session = FakeSession()

    result = asyncio.run(_run(session, lane, door, player))

    assert result.reason == "crashed"
    assert result.exit_code == 7


def test_door_that_never_exits_is_killed_on_wall_time_timeout(db, lane, player, tmp_path):
    script = _write_script(tmp_path, "hang_door.py", "import time; time.sleep(60)")
    door = create_door(db, "Hanger", sys.executable, args=(str(script),), creator=player)
    session = FakeSession()

    result = asyncio.run(_run(session, lane, door, player, wall_time_limit_seconds=0.3))

    assert result.reason == "timed_out"


def test_caller_disconnect_ends_the_session_and_kills_the_door(db, lane, player, tmp_path):
    script = _write_script(tmp_path, "wait_forever.py", "import time; time.sleep(60)")
    door = create_door(db, "Waiter", sys.executable, args=(str(script),), creator=player)
    session = FakeSession()

    async def scenario():
        task = asyncio.create_task(_run(session, lane, door, player))
        await asyncio.sleep(0.2)
        session.disconnect()
        return await task

    result = asyncio.run(scenario())

    assert result.reason == "caller_disconnected"


def test_bad_executable_path_is_reported_as_failed_to_start(db, lane, player):
    door = create_door(db, "Broken", "/no/such/executable-netbbs-test", creator=player)
    session = FakeSession()

    result = asyncio.run(_run(session, lane, door, player))

    assert result.reason == "failed_to_start"
    assert result.exit_code is None


def test_play_door_is_audit_logged(db, lane, player, tmp_path):
    from netbbs.moderation.log import list_actions_for_object

    script = _write_script(tmp_path, "quick_exit.py", "pass")
    door = create_door(db, "Quick", sys.executable, args=(str(script),), creator=player)
    session = FakeSession()

    asyncio.run(_run(session, lane, door, player))

    entries = list_actions_for_object(db, object_type="door", object_id=door.id)
    play_entries = [e for e in entries if e.action == "play_door"]
    assert len(play_entries) == 1
    assert play_entries[0].actor_user_id == player.id
    assert "reason=exited" in play_entries[0].detail
