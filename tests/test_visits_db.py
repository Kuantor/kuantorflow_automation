"""`utils.record_visit()` against a real MySQL (kuantorflow#598).

A check-in continues the visitor's open visit or starts one, and every rule
that decides which is SQL: the 30-minute gap, a closed visit, the seconds cap
read off `TIMESTAMPDIFF`, `IFNULL` for an account signed in part-way, and the
cascade when the account goes. Time is moved by setting `last_seen_at` back
rather than by waiting.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv


@pytest.fixture(autouse=True)
def _the_real_utils(real_utils):
    """A real scratch database, so the offline stubs would answer first
    (kuantorflow#436)."""


AUTO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(AUTO_ROOT / ".env")

KUANTORFLOW_PATH = Path(os.environ.get(
    "KUANTORFLOW_PATH", str(AUTO_ROOT.parent.parent / "kuantorflow")))
SCRIPT = KUANTORFLOW_PATH / "scripts" / "apply_schema.py"

SCRATCH_DB = "kuantorflow_visits_test"

pytestmark = [pytest.mark.db, pytest.mark.skipif(
    not (os.environ.get("RUN_DB_ROUNDTRIP") == "1"
         and os.environ.get("DB_HOST") in ("localhost", "127.0.0.1")
         and os.environ.get("DB_PASSWORD")
         and SCRIPT.exists()),
    reason="opt-in: set RUN_DB_ROUNDTRIP=1 with a local MySQL (DB_HOST=localhost) "
    "and DB_* configured; the test creates its own scratch database")]


def _execute(statements):
    import mysql.connector
    conn = mysql.connector.connect(
        user=os.environ.get("DB_USER", "kuantorflow"),
        password=os.environ["DB_PASSWORD"], host=os.environ["DB_HOST"])
    try:
        cursor = conn.cursor()
        for statement in statements:
            cursor.execute(statement)
        conn.commit()
        cursor.close()
    finally:
        conn.close()


@pytest.fixture()
def scratch_db(monkeypatch):
    _execute([f"DROP DATABASE IF EXISTS {SCRATCH_DB}",
              f"CREATE DATABASE {SCRATCH_DB} CHARACTER SET utf8mb4"])
    subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True,
                   env=dict(os.environ, DB_NAME=SCRATCH_DB),
                   cwd=str(KUANTORFLOW_PATH), check=True)
    monkeypatch.setenv("DB_NAME", SCRATCH_DB)
    try:
        yield SCRATCH_DB
    finally:
        _execute([f"DROP DATABASE IF EXISTS {SCRATCH_DB}"])


def _sql(sql, params=()):
    import utils
    conn = utils.get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        rows = cursor.fetchall() if cursor.with_rows else None
        conn.commit()
        cursor.close()
    finally:
        conn.close()
    return rows


def _visits(visitor="a" * 16):
    return _sql("SELECT id, user_id, active_seconds, pages, "
                "TIMESTAMPDIFF(SECOND, started_at, last_seen_at) "
                "FROM visits WHERE visitor = %s ORDER BY id", (visitor,))


def _back(seconds, visitor="a" * 16):
    """As if the last check-in was `seconds` ago."""
    _sql("UPDATE visits SET started_at = started_at - INTERVAL %s SECOND, "
         "last_seen_at = last_seen_at - INTERVAL %s SECOND WHERE visitor = %s",
         (seconds, seconds, visitor))


V = "a" * 16


def test_the_first_check_in_starts_a_visit(scratch_db):
    import utils

    utils.record_visit(visitor=V, user_id=None, active=5, page=True)

    ((_, user_id, active, pages, span),) = _visits()
    assert (user_id, active, pages) == (None, 5, 1)
    assert span == 5, "the visit starts when the page was opened, not at the check-in"


def test_a_minute_later_continues_it(scratch_db):
    import utils

    utils.record_visit(visitor=V, user_id=None, active=5, page=True)
    _back(60)
    utils.record_visit(visitor=V, user_id=None, active=60, page=False)
    _back(60)
    utils.record_visit(visitor=V, user_id=None, active=58, page=True)

    ((_, _, active, pages, _),) = _visits()
    assert (active, pages) == (123, 2)


def test_the_seconds_never_exceed_the_time_that_passed(scratch_db):
    import utils

    utils.record_visit(visitor=V, user_id=None, active=5, page=True)
    _back(10)
    utils.record_visit(visitor=V, user_id=None, active=70, page=False)

    assert _visits()[0][2] == 5 + 10 + utils.VISIT_SLACK_SECONDS


def test_thirty_minutes_of_silence_starts_a_new_visit(scratch_db):
    import utils

    utils.record_visit(visitor=V, user_id=None, active=5, page=True)
    _back(utils.VISIT_GAP_MINUTES * 60 + 60)
    utils.record_visit(visitor=V, user_id=None, active=5, page=True)

    assert len(_visits()) == 2


def test_a_closed_visit_is_not_continued(scratch_db):
    import utils

    utils.record_visit(visitor=V, user_id=None, active=5, page=True)
    _sql("UPDATE visits SET closed_at = UTC_TIMESTAMP()")
    utils.record_visit(visitor=V, user_id=None, active=5, page=True)

    assert len(_visits()) == 2


def test_another_visitor_is_another_visit(scratch_db):
    import utils

    utils.record_visit(visitor=V, user_id=None, active=5, page=True)
    utils.record_visit(visitor="b" * 16, user_id=None, active=5, page=True)

    assert len(_visits()) == 1 and len(_visits("b" * 16)) == 1


def test_signing_in_part_way_attaches_the_visit(scratch_db):
    import utils

    learner, _, _ = utils.upsert_user("sub-598", "learner@example.com")
    utils.record_visit(visitor=V, user_id=None, active=5, page=True)
    _back(30)
    utils.record_visit(visitor=V, user_id=learner, active=30, page=False)
    _back(30)
    utils.record_visit(visitor=V, user_id=None, active=30, page=False)

    assert _visits()[0][1] == learner, "signing out must not take the visit away"


def test_deleting_the_account_deletes_its_visits(scratch_db):
    import utils

    learner, _, _ = utils.upsert_user("sub-598b", "gone@example.com")
    utils.record_visit(visitor=V, user_id=learner, active=5, page=True)
    utils.record_visit(visitor="b" * 16, user_id=None, active=5, page=True)
    _sql("DELETE FROM users WHERE id = %s", (learner,))

    assert _visits() == [] and len(_visits("b" * 16)) == 1
