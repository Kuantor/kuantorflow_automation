"""Offline checks for the backup helper logic (no DB or mysqldump needed)."""

import sys
from datetime import datetime
from pathlib import Path

BACKUP_DIR = Path(__file__).resolve().parent.parent / "backup"
sys.path.insert(0, str(BACKUP_DIR))

import backup_db  # noqa: E402


def test_backup_filename_is_timestamped_and_sortable():
    name = backup_db.backup_filename(datetime(2026, 7, 13, 2, 0, 0))
    assert name == "kuantorflow_2026-07-13_020000.sql.gz"
    # Chronological order == lexicographic order (used by the retention logic)
    earlier = backup_db.backup_filename(datetime(2026, 7, 12, 23, 59, 59))
    later = backup_db.backup_filename(datetime(2026, 7, 13, 0, 0, 0))
    assert earlier < later


def test_select_old_backups_keeps_newest(tmp_path):
    names = [
        "kuantorflow_2026-07-10_020000.sql.gz",
        "kuantorflow_2026-07-11_020000.sql.gz",
        "kuantorflow_2026-07-12_020000.sql.gz",
        "kuantorflow_2026-07-13_020000.sql.gz",
    ]
    files = []
    for n in names:
        p = tmp_path / n
        p.write_bytes(b"x")
        files.append(p)

    to_delete = backup_db.select_old_backups(files, keep=2)
    deleted_names = sorted(f.name for f in to_delete)
    # The two oldest are deleted; the two newest are kept.
    assert deleted_names == [
        "kuantorflow_2026-07-10_020000.sql.gz",
        "kuantorflow_2026-07-11_020000.sql.gz",
    ]


def test_select_old_backups_ignores_unrelated_files(tmp_path):
    (tmp_path / "kuantorflow_2026-07-13_020000.sql.gz").write_bytes(b"x")
    (tmp_path / "notes.txt").write_bytes(b"x")
    (tmp_path / ".gitkeep").write_bytes(b"x")
    to_delete = backup_db.select_old_backups(tmp_path.iterdir(), keep=0)
    # Only the real backup is a deletion candidate; keep=0 selects it, others ignored.
    assert [f.name for f in to_delete] == ["kuantorflow_2026-07-13_020000.sql.gz"]


def test_select_old_backups_nothing_to_delete_when_under_limit(tmp_path):
    (tmp_path / "kuantorflow_2026-07-13_020000.sql.gz").write_bytes(b"x")
    assert backup_db.select_old_backups(tmp_path.iterdir(), keep=7) == []
