"""Tests for netbbs.net.draft_storage -- shared draft file persistence
(issue #149) and stale-draft pruning (issue #158)."""

from __future__ import annotations

import os
import time

from netbbs.net.draft_storage import drafts_directory, prune_stale_drafts
from netbbs.storage.database import Database

import pytest


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "node.db")
    yield database
    database.close()


def _age_file(path, seconds_old: float) -> None:
    """Backdate a file's mtime -- same direct-manipulation approach
    tests/test_files_gc.py already uses to simulate old content,
    rather than monkeypatching a clock."""
    backdated = time.time() - seconds_old
    os.utime(path, (backdated, backdated))


def test_drafts_directory_is_created_and_colocated_with_the_database(db):
    directory = drafts_directory(db)
    assert directory.exists()
    assert directory.parent == db.path.parent
    assert directory.name == f"{db.path.name}_drafts"


def test_prune_reports_nothing_when_the_directory_is_empty(db):
    report = prune_stale_drafts(db, dry_run=True)
    assert report.stale_files == 0
    assert report.stale_bytes == 0
    assert report.skipped_recent == 0
    assert report.errors == []


def test_dry_run_reports_but_does_not_delete(db):
    stale = drafts_directory(db) / "new_1_2.draft"
    stale.write_text("abandoned draft", encoding="utf-8")
    _age_file(stale, seconds_old=40 * 24 * 3600)

    report = prune_stale_drafts(db, dry_run=True, min_age_seconds=30 * 24 * 3600)

    assert report.dry_run is True
    assert report.stale_files == 1
    assert report.stale_bytes == len(b"abandoned draft")
    assert stale.exists()  # nothing actually deleted


def test_real_run_deletes_the_stale_draft(db):
    stale = drafts_directory(db) / "edit_1_2_abc123.draft"
    stale.write_text("abandoned edit", encoding="utf-8")
    _age_file(stale, seconds_old=40 * 24 * 3600)

    report = prune_stale_drafts(db, dry_run=False, min_age_seconds=30 * 24 * 3600)

    assert report.dry_run is False
    assert report.stale_files == 1
    assert not stale.exists()


def test_a_draft_still_within_the_retention_window_is_never_pruned(db):
    """Acceptance criterion: a draft just inside the window is left
    alone even while the prune action runs -- not just "usually"."""
    fresh = drafts_directory(db) / "bio_3.draft"
    fresh.write_text("still working on this", encoding="utf-8")
    _age_file(fresh, seconds_old=(30 * 24 * 3600) - 60)  # just under 30 days

    report = prune_stale_drafts(db, dry_run=False, min_age_seconds=30 * 24 * 3600)

    assert report.stale_files == 0
    assert report.skipped_recent == 1
    assert fresh.exists()


def test_a_draft_just_past_the_window_is_pruned(db):
    """The other half of the same boundary."""
    stale = drafts_directory(db) / "bio_3.draft"
    stale.write_text("forgot about this one", encoding="utf-8")
    _age_file(stale, seconds_old=(30 * 24 * 3600) + 60)  # just over 30 days

    report = prune_stale_drafts(db, dry_run=False, min_age_seconds=30 * 24 * 3600)

    assert report.stale_files == 1
    assert report.skipped_recent == 0
    assert not stale.exists()


def test_prune_does_not_distinguish_new_edit_or_bio_drafts(db):
    """Issue #158's own scope: every *.draft file is safe to prune the
    same way once stale, regardless of which caller wrote it."""
    directory = drafts_directory(db)
    new_draft = directory / "new_1_2.draft"
    edit_draft = directory / "edit_1_2_abc.draft"
    bio_draft = directory / "bio_2.draft"
    for path, content in ((new_draft, "a"), (edit_draft, "bb"), (bio_draft, "ccc")):
        path.write_text(content, encoding="utf-8")
        _age_file(path, seconds_old=40 * 24 * 3600)

    report = prune_stale_drafts(db, dry_run=False, min_age_seconds=30 * 24 * 3600)

    assert report.stale_files == 3
    assert report.stale_bytes == len("a") + len("bb") + len("ccc")
    assert not new_draft.exists()
    assert not edit_draft.exists()
    assert not bio_draft.exists()


def test_non_draft_files_in_the_directory_are_ignored(db):
    directory = drafts_directory(db)
    stray = directory / "not-a-draft.txt"
    stray.write_text("unrelated", encoding="utf-8")
    _age_file(stray, seconds_old=40 * 24 * 3600)

    report = prune_stale_drafts(db, dry_run=False, min_age_seconds=30 * 24 * 3600)

    assert report.stale_files == 0
    assert stray.exists()
