"""Tests for netbbs.operational_history."""

from __future__ import annotations

import pytest

from netbbs.operational_history import list_operational_run_history, record_operational_run
from netbbs.storage.database import Database


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "node.db")
    yield database
    database.close()


def test_record_operational_run_returns_populated_entry(db):
    run = record_operational_run(db, "backup", "succeeded", detail="/backups/2026-08-16")
    assert run.kind == "backup"
    assert run.outcome == "succeeded"
    assert run.detail == "/backups/2026-08-16"
    assert run.created_at


def test_record_operational_run_allows_no_detail(db):
    run = record_operational_run(db, "update_check", "up to date (v2.1.0)")
    assert run.detail is None


def test_list_operational_run_history_is_most_recent_first(db):
    record_operational_run(db, "backup", "first")
    record_operational_run(db, "backup", "second")
    history = list_operational_run_history(db, "backup")
    assert [r.outcome for r in history] == ["second", "first"]


def test_list_operational_run_history_scoped_to_kind(db):
    record_operational_run(db, "backup", "succeeded")
    record_operational_run(db, "update_check", "up to date")
    backups = list_operational_run_history(db, "backup")
    checks = list_operational_run_history(db, "update_check")
    assert [r.outcome for r in backups] == ["succeeded"]
    assert [r.outcome for r in checks] == ["up to date"]


def test_list_operational_run_history_empty_when_nothing_recorded(db):
    assert list_operational_run_history(db, "backup") == []


def test_record_operational_run_prunes_old_rows_of_the_same_kind(db):
    # Dogfood follow-up: this is reporting context for a SysOp, not a
    # permanent audit trail -- unbounded growth would be pure waste.
    from netbbs.operational_history import _MAX_ROWS_PER_KIND

    for i in range(_MAX_ROWS_PER_KIND + 5):
        record_operational_run(db, "backup", f"run-{i}")
    history = list_operational_run_history(db, "backup", limit=_MAX_ROWS_PER_KIND + 5)
    assert len(history) == _MAX_ROWS_PER_KIND
    # The oldest surviving entry is the most recent one still inside
    # the retention window, not one of the earliest ever recorded.
    assert history[-1].outcome == "run-5"


def test_record_operational_run_prunes_only_the_same_kind(db):
    for i in range(3):
        record_operational_run(db, "backup", f"backup-{i}")
    record_operational_run(db, "update_check", "up to date")
    assert len(list_operational_run_history(db, "backup")) == 3
    assert len(list_operational_run_history(db, "update_check")) == 1
