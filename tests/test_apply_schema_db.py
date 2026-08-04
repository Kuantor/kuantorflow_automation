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


def _rewind_to_pre_207():
    """Undo #207 on a freshly created scratch database.

    Rewinding a real schema.sql table beats pasting a copy of the old CREATE
    TABLE here: a stale copy would drift from the app's real history and quietly
    stop testing the migration that matters. Dropping the column takes its index
    with it.
    """
    _execute(["ALTER TABLE flashcards DROP FOREIGN KEY fk_flashcards_topic",
              "ALTER TABLE flashcards DROP COLUMN topic_id",
              "DROP TABLE topics"], SCRATCH_DB)


STATUSES = (" would be applied", " already present", " applied")


def _steps_in(stdout):
    """The step names the script reported as applied or pending.

    A name can contain a space ('flashcards.topic_id backfill'), so it is the
    text between the marker and the status rather than the second word.
    """
    names = set()
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line.startswith(("+", "~")):
            continue
        body = line[1:].strip()
        for status in STATUSES:
            if body.endswith(status):
                body = body[:-len(status)]
                break
        names.add(body.strip())
    return names


@requires_local_db
def test_an_empty_database_gets_the_whole_schema(scratch_db):
    result = _apply()
    assert result.returncode == 0, result.stderr
    tables = sorted(r[0] for r in _query("SHOW TABLES"))
    assert tables == ["anonymous_usage", "flashcards", "topics", "users"]
    # The tables schema.sql creates need no migrations on top of them.
    columns = _columns()
    assert "added_by_user_id" in columns
    assert "topic_id" in columns
    assert "nothing to do" not in result.stdout


@requires_local_db
def test_a_pre_89_database_is_migrated_and_keeps_its_cards(scratch_db):
    _apply()                                   # tables as they should be
    fresh_columns = _columns()                 # what a new install looks like
    _execute(["DROP TABLE flashcards", PRE_89_FLASHCARDS,
              "INSERT INTO flashcards (word, topic) VALUES ('brittle', 'vocab')"],
             SCRATCH_DB)
    assert "added_by_user_id" not in _columns()

    result = _apply()
    assert result.returncode == 0, result.stderr
    # Named steps rather than a count: a total goes stale on the next migration
    # and says nothing about which work was done.
    assert {"flashcards.pos", "flashcards.added_by_user_id",
            "flashcards.topic_id", "flashcards.topic_id backfill"} <= \
        _steps_in(result.stdout)
    assert "change(s) applied" in result.stdout

    # Every column landed where schema.sql puts it, so a database that was
    # migrated is indistinguishable from one that was created.
    assert _columns() == fresh_columns
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
    assert "idx_topic_id" in indexes
    assert "fk_flashcards_topic" in constraints


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
    assert "change(s) pending" in result.stdout
    assert {"flashcards.pos", "flashcards.added_by_user_id",
            "flashcards.topic_id"} <= _steps_in(result.stdout)
    assert "added_by_user_id" not in _columns(), "--dry-run changed the database"


@requires_local_db
def test_dry_run_reports_the_backfill_it_cannot_yet_probe(scratch_db):
    """The probe names topic_id, which --dry-run has not created (#207).

    A real database rejects that query. The script has to read the rejection as
    "nothing has been backfilled" and carry on reporting, because otherwise
    looking before you leap would crash on exactly the deploy that needs it.
    """
    _apply()
    _rewind_to_pre_207()
    _execute(["INSERT INTO flashcards (word, topic) VALUES ('brittle', 'vocab')"],
             SCRATCH_DB)

    result = _apply("--dry-run")
    assert result.returncode == 0, result.stderr
    assert "flashcards.topic_id backfill" in _steps_in(result.stdout)
    assert "topic_id" not in _columns(), "--dry-run changed the database"


# --- #207: the backfill, against a real database ------------------------


@requires_local_db
def test_the_backfill_creates_one_topic_per_name_and_links_every_card(scratch_db):
    _apply()
    _rewind_to_pre_207()
    _execute([
        "INSERT INTO flashcards (word, topic) VALUES ('brittle', 'vocab')",
        "INSERT INTO flashcards (word, topic) VALUES ('resilient', 'vocab')",
        "INSERT INTO flashcards (word, topic) VALUES ('nosy', 'emotions')",
        # 'no topic' is a real state, and must not become a topic named ''
        "INSERT INTO flashcards (word, topic) VALUES ('orphan', '')",
        "INSERT INTO flashcards (word, topic) VALUES ('stray', NULL)",
    ], SCRATCH_DB)

    assert _apply().returncode == 0

    assert sorted(r[0] for r in _query("SELECT name FROM topics")) == \
        ["emotions", "vocab"]
    assert _query("SELECT COUNT(*) FROM flashcards WHERE topic IS NOT NULL "
                  "AND topic <> '' AND topic_id IS NULL") == [(0,)]
    assert _query("SELECT COUNT(*) FROM topics WHERE name = ''") == [(0,)]
    assert sorted(_query(
        "SELECT word, topic_id FROM flashcards WHERE topic_id IS NULL")) == \
        [("orphan", None), ("stray", None)]


@requires_local_db
def test_the_backfill_dates_each_topic_from_its_earliest_card(scratch_db):
    """A topic began when its first card was filed, not on migration day."""
    _apply()
    _rewind_to_pre_207()
    _execute([
        "INSERT INTO flashcards (word, topic, created_at) "
        "VALUES ('early', 'vocab', '2026-01-01 09:00:00')",
        "INSERT INTO flashcards (word, topic, created_at) "
        "VALUES ('late', 'vocab', '2026-06-01 09:00:00')",
    ], SCRATCH_DB)

    assert _apply().returncode == 0

    assert [str(r[0]) for r in _query(
        "SELECT created_at FROM topics WHERE name = 'vocab'")] == \
        ["2026-01-01 09:00:00"]


@requires_local_db
def test_the_backfill_credits_the_earliest_cards_owner(scratch_db):
    """Whoever saved the first card did create the topic, under the rules this
    replaces. A later arrival does not become its creator."""
    _apply()
    _rewind_to_pre_207()
    _execute([
        "INSERT INTO users (id, google_sub, email) "
        "VALUES (11, 'sub-first', 'first@example.com')",
        "INSERT INTO users (id, google_sub, email) "
        "VALUES (22, 'sub-later', 'later@example.com')",
        "INSERT INTO flashcards (word, topic, added_by_user_id, created_at) "
        "VALUES ('early', 'owned', 11, '2026-01-01 09:00:00')",
        "INSERT INTO flashcards (word, topic, added_by_user_id, created_at) "
        "VALUES ('late', 'owned', 22, '2026-06-01 09:00:00')",
        # A topic whose first card was anonymous stays creatorless: the honest
        # answer, arrived at rather than assumed.
        "INSERT INTO flashcards (word, topic, created_at) "
        "VALUES ('nobodys', 'unowned', '2026-02-01 09:00:00')",
        "INSERT INTO flashcards (word, topic, added_by_user_id, created_at) "
        "VALUES ('somebodys', 'unowned', 11, '2026-03-01 09:00:00')",
    ], SCRATCH_DB)

    assert _apply().returncode == 0

    assert _query("SELECT created_by_user_id FROM topics WHERE name = 'owned'") \
        == [(11,)]
    assert _query("SELECT created_by_user_id FROM topics WHERE name = 'unowned'") \
        == [(None,)]


@requires_local_db
def test_case_variant_topics_become_one_row_and_one_spelling(scratch_db):
    """'Work' and 'work' were already one topic to every query the app ran, so
    the UNIQUE key cannot be violated — but only one spelling survives, and the
    string column is rewritten to match the row it points at."""
    _apply()
    _rewind_to_pre_207()
    _execute([
        "INSERT INTO flashcards (word, topic) VALUES ('a', 'emotions')",
        "INSERT INTO flashcards (word, topic) VALUES ('b', 'EMOTIONS')",
        "INSERT INTO flashcards (word, topic) VALUES ('c', 'Emotions')",
    ], SCRATCH_DB)

    assert _apply().returncode == 0

    assert _query("SELECT COUNT(*) FROM topics") == [(1,)]
    assert _query("SELECT COUNT(DISTINCT topic_id) FROM flashcards") == [(1,)]
    # Every card spells it exactly as the row does — the invariant that keeps
    # ai_agent, which still reads the string, agreeing with the app.
    assert _query("SELECT COUNT(*) FROM flashcards f JOIN topics t "
                  "ON f.topic_id = t.id "
                  "WHERE f.topic <> t.name COLLATE utf8mb4_bin") == [(0,)]


@requires_local_db
def test_an_interrupted_backfill_is_finished_by_the_next_run(scratch_db):
    """The probe describes remaining work, so a partial run reads as unfinished.

    This is what makes the migration safe to interrupt: the fix for a run that
    died halfway is to run it again.
    """
    _apply()
    _rewind_to_pre_207()
    _execute(["INSERT INTO flashcards (word, topic) VALUES ('brittle', 'vocab')"],
             SCRATCH_DB)
    assert _apply().returncode == 0

    # A card arriving as if the run had stopped before reaching it.
    _execute(["INSERT INTO flashcards (word, topic, topic_id) "
              "VALUES ('afterwards', 'vocab', NULL)"], SCRATCH_DB)

    result = _apply()
    assert result.returncode == 0, result.stderr
    assert "flashcards.topic_id backfill" in _steps_in(result.stdout), \
        "the outstanding row makes the step pending again"
    assert _query("SELECT COUNT(*) FROM flashcards WHERE topic_id IS NULL") == [(0,)]
    assert _query("SELECT COUNT(*) FROM topics") == [(1,)], \
        "and the topic it already had was not duplicated"


@requires_local_db
def test_deleting_a_topics_creator_leaves_the_topic_standing(scratch_db):
    """ON DELETE SET NULL, unlike flashcards' RESTRICT (#207).

    A topic may hold other people's cards, so deleting its creator's account
    cannot delete it — and RESTRICT would make the deletion itself fail.
    """
    _apply()
    _execute([
        "INSERT INTO users (id, google_sub, email) "
        "VALUES (11, 'sub-leaver', 'leaver@example.com')",
        "INSERT INTO topics (id, name, created_by_user_id) "
        "VALUES (5, 'shared', 11)",
    ], SCRATCH_DB)

    _execute(["DELETE FROM users WHERE id = 11"], SCRATCH_DB)

    assert _query("SELECT name, created_by_user_id FROM topics WHERE id = 5") \
        == [("shared", None)]


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
