"""
apply_schema.py against a real LOCAL MySQL (marker: db) — kuantorflow#180.

The offline tests (test_apply_schema.py) prove the logic against a fake; this
proves the thing the outage was actually about: that running the script on a
database created before #89 adds the missing column, index and foreign key,
and that running it again does nothing.

Safety: this creates and drops its **own** scratch database
(kuantorflow_apply_schema_test) and never touches the configured one. It is
still opt-in (RUN_DB_ROUNDTRIP=1, the same switch as the backup round-trip) and
refuses to run unless DB_HOST is localhost, because it needs CREATE DATABASE
rights and the offline suite must stay write-free. Run with:

    # PowerShell
    $env:RUN_DB_ROUNDTRIP="1"; pytest -m db
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

AUTO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(AUTO_ROOT / ".env")

KUANTORFLOW_PATH = Path(os.environ.get(
    "KUANTORFLOW_PATH", str(AUTO_ROOT.parent.parent / "kuantorflow")))
SCRIPT = KUANTORFLOW_PATH / "apply_schema.py"

SCRATCH_DB = "kuantorflow_apply_schema_test"

pytestmark = pytest.mark.db


def _prerequisites_met():
    return (
        os.environ.get("RUN_DB_ROUNDTRIP") == "1"          # explicit opt-in
        and os.environ.get("DB_HOST") in ("localhost", "127.0.0.1")
        and os.environ.get("DB_PASSWORD")
        and SCRIPT.exists()
    )


requires_local_db = pytest.mark.skipif(
    not _prerequisites_met(),
    reason="opt-in: set RUN_DB_ROUNDTRIP=1 with a local MySQL (DB_HOST=localhost) "
    "and DB_* configured; the test creates its own scratch database",
)

# The flashcards table as it stood before #89 and before the pos column — the
# shape the production database was actually in when the deploy broke it.
PRE_89_FLASHCARDS = """
CREATE TABLE flashcards (
    id INT AUTO_INCREMENT PRIMARY KEY,
    word VARCHAR(255) NOT NULL,
    explanation_en TEXT,
    examples_en TEXT,
    translation_ukr VARCHAR(255),
    examples_ukr TEXT,
    translation_rus VARCHAR(255),
    examples_rus TEXT,
    topic VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_topic (topic),
    INDEX idx_word (word)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
"""


def _connect(database=None):
    import mysql.connector
    return mysql.connector.connect(
        user=os.environ.get("DB_USER", "kuantorflow"),
        password=os.environ["DB_PASSWORD"],
        host=os.environ["DB_HOST"],
        database=database,
    )


def _execute(statements, database=None):
    conn = _connect(database)
    cursor = conn.cursor()
    for statement in statements:
        cursor.execute(statement)
    conn.commit()
    cursor.close()
    conn.close()


def _query(sql, params=(), database=SCRATCH_DB):
    conn = _connect(database)
    cursor = conn.cursor()
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def _apply(*args):
    """Run apply_schema.py against the scratch database."""
    env = dict(os.environ, DB_NAME=SCRATCH_DB)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, env=env, cwd=str(KUANTORFLOW_PATH),
    )


@pytest.fixture()
def scratch_db():
    _execute([f"DROP DATABASE IF EXISTS {SCRATCH_DB}",
              f"CREATE DATABASE {SCRATCH_DB} CHARACTER SET utf8mb4"])
    try:
        yield SCRATCH_DB
    finally:
        _execute([f"DROP DATABASE IF EXISTS {SCRATCH_DB}"])


def _columns(table="flashcards"):
    """Column names in table order (information_schema does not sort them)."""
    return [r[0] for r in _query(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s "
        "ORDER BY ORDINAL_POSITION", (table,))]


@requires_local_db
def test_an_empty_database_gets_the_whole_schema(scratch_db):
    result = _apply()
    assert result.returncode == 0, result.stderr
    tables = sorted(r[0] for r in _query("SHOW TABLES"))
    assert tables == ["anonymous_usage", "flashcards", "users"]
    # The tables schema.sql creates need no migrations on top of them.
    assert "added_by_user_id" in _columns()
    assert "nothing to do" not in result.stdout


@requires_local_db
def test_a_pre_89_database_is_migrated_and_keeps_its_cards(scratch_db):
    _apply()                                   # tables as they should be
    _execute(["DROP TABLE flashcards", PRE_89_FLASHCARDS,
              "INSERT INTO flashcards (word, topic) VALUES ('brittle', 'vocab')"],
             SCRATCH_DB)
    assert "added_by_user_id" not in _columns()

    result = _apply()
    assert result.returncode == 0, result.stderr
    assert "4 change(s) applied" in result.stdout

    columns = _columns()
    assert "pos" in columns and "added_by_user_id" in columns
    # Added in the right place, so a migrated table matches a fresh one.
    assert columns.index("pos") == columns.index("word") + 1
    assert columns.index("added_by_user_id") == columns.index("topic") + 1
    assert _query("SELECT word, pos, added_by_user_id FROM flashcards") == [
        ("brittle", None, None)], "the existing card survived untouched"

    indexes = {r[0] for r in _query(
        "SELECT INDEX_NAME FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'flashcards'")}
    constraints = {r[0] for r in _query(
        "SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'flashcards'")}
    assert "idx_added_by" in indexes
    assert "fk_flashcards_user" in constraints


@requires_local_db
def test_a_second_run_is_a_no_op_and_says_so(scratch_db):
    _apply()
    result = _apply()
    assert result.returncode == 0, result.stderr
    assert "nothing to do" in result.stdout
    assert "applied" not in result.stdout


@requires_local_db
def test_dry_run_reports_the_pending_work_without_doing_it(scratch_db):
    _apply()
    _execute(["DROP TABLE flashcards", PRE_89_FLASHCARDS], SCRATCH_DB)

    result = _apply("--dry-run")
    assert result.returncode == 0, result.stderr
    assert "4 change(s) pending" in result.stdout
    assert "added_by_user_id" not in _columns(), "--dry-run changed the database"


@requires_local_db
def test_a_broken_migration_exits_non_zero(scratch_db):
    """A column of the wrong type: the foreign key cannot be created on it."""
    _apply()
    _execute(["DROP TABLE flashcards", PRE_89_FLASHCARDS,
              "ALTER TABLE flashcards ADD COLUMN added_by_user_id VARCHAR(10) NULL"],
             SCRATCH_DB)

    result = _apply()
    assert result.returncode == 1
    assert "fk_flashcards_user failed" in result.stderr
