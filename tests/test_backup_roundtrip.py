"""
Backup/restore round-trip against a LOCAL MySQL database (marker: db).

Guards the exact bug where restore fed compressed bytes to mysql and did
nothing: a card deleted after a backup must reappear after restoring it.

Safety: restore OVERWRITES the target database, so this test is opt-in
(RUN_DB_ROUNDTRIP=1) and additionally refuses to run unless DB_HOST is
localhost/127.0.0.1. It only ever touches a sentinel row, and restores from a
backup taken microseconds earlier, so the local data is preserved. The opt-in
gate keeps the normal offline suite (`pytest -m "not live"`) write-free even
when a local .env is present. Run with:

    # PowerShell
    $env:RUN_DB_ROUNDTRIP="1"; pytest -m db
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

AUTO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(AUTO_ROOT / ".env")

BACKUP_DIR = AUTO_ROOT / "backup"
BACKUPS = BACKUP_DIR / "backups"
SENTINEL = "RESTORE_ROUNDTRIP_SENTINEL"

pytestmark = pytest.mark.db


def _tool(env_var, default):
    path = os.environ.get(env_var, default)
    return path if (shutil.which(path) or Path(path).exists()) else None


def _prerequisites_met():
    host = os.environ.get("DB_HOST", "")
    return (
        os.environ.get("RUN_DB_ROUNDTRIP") == "1"     # explicit opt-in (writes to DB)
        and host in ("localhost", "127.0.0.1")        # never run against production
        and os.environ.get("DB_PASSWORD")
        and os.environ.get("DB_NAME")
        and _tool("MYSQLDUMP_PATH", "mysqldump")
        and _tool("MYSQL_PATH", "mysql")
    )


requires_local_db = pytest.mark.skipif(
    not _prerequisites_met(),
    reason="opt-in: set RUN_DB_ROUNDTRIP=1 with a local MySQL DB (DB_HOST=localhost), "
    "DB_* configured, and mysql tools available",
)


def _connect():
    import mysql.connector
    return mysql.connector.connect(
        user=os.environ.get("DB_USER", "kuantorflow"),
        password=os.environ["DB_PASSWORD"],
        host=os.environ["DB_HOST"],
        database=os.environ["DB_NAME"],
    )


def _sentinel_count():
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM flashcards WHERE word = %s", (SENTINEL,))
    n = cur.fetchone()[0]
    conn.close()
    return n


def _delete_sentinel():
    conn = _connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM flashcards WHERE word = %s", (SENTINEL,))
    conn.commit()
    conn.close()


def _run(script, *args):
    r = subprocess.run(
        [sys.executable, str(BACKUP_DIR / script), *args],
        capture_output=True, text=True, cwd=str(AUTO_ROOT),
    )
    assert r.returncode == 0, f"{script} failed:\n{r.stdout}\n{r.stderr}"


@requires_local_db
def test_deleted_card_reappears_after_restore():
    made_backup = None
    try:
        # 1. sentinel exists
        _delete_sentinel()
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO flashcards (word, pos, topic) VALUES (%s, 'noun', 'roundtrip-test')",
            (SENTINEL,),
        )
        conn.commit()
        conn.close()
        assert _sentinel_count() == 1

        # 2. back up (backup now contains the sentinel)
        _run("backup_db.py")
        made_backup = max(BACKUPS.glob("kuantorflow_*.sql.gz"), key=lambda p: p.stat().st_mtime)

        # 3. delete it, as if the user removed a card after the backup
        _delete_sentinel()
        assert _sentinel_count() == 0

        # 4. restore
        _run("restore_db.py", str(made_backup), "--yes")

        # 5. the deleted card is back
        assert _sentinel_count() == 1, "restore did not bring back the deleted card"
    finally:
        _delete_sentinel()
        if made_backup and made_backup.exists():
            made_backup.unlink()
