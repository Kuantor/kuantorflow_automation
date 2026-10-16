"""The daily report's queries against a real MySQL (kuantorflow#593).

`gather_db()` counts a Kyiv day's rows in SQL. The day's edges are UTC
instants, and **`TIMESTAMP` columns come back in the session's time zone**:
locally that is Kyiv, so without `SET time_zone = '+00:00'` a card made a
minute before the day began would be read as three hours later and counted.
Only a real server converts, so this puts rows just inside and just outside
both edges and checks which are counted.
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

SCRATCH_DB = "kuantorflow_daily_report_test"

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
    cursor = conn.cursor()
    for statement in statements:
        cursor.execute(statement)
    conn.commit()
    cursor.close()
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


def _run(sql, params=()):
    import utils
    conn = utils.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SET time_zone = '+00:00'")
    cursor.execute(sql, params)
    conn.commit()
    cursor.close()
    conn.close()


def _curdate():
    import utils
    conn = utils.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT CURDATE()")
    (day,) = cursor.fetchone()
    cursor.close()
    conn.close()
    return day


@pytest.fixture()
def kyiv_sessions(monkeypatch):
    """Every connection the app opens starts in Kyiv's zone, as a server whose
    clock is not UTC would hand it out -- the case `SET time_zone` is for. A
    local MySQL running in UTC would otherwise hide the bug this test is for."""
    import utils
    real = utils.get_db_connection

    def in_kyiv():
        conn = real()
        cursor = conn.cursor()
        cursor.execute("SET time_zone = '+03:00'")
        cursor.close()
        return conn
    monkeypatch.setattr(utils, "get_db_connection", in_kyiv)


def test_the_days_rows_are_counted_and_the_edges_hold(scratch_db, kyiv_sessions):
    from datetime import timedelta

    import daily_report
    import recall
    import utils

    learner, _, _ = utils.upsert_user("sub-593", "learner@example.com")
    other, _, _ = utils.upsert_user("sub-593b", "other@example.com")
    day = recall.today()
    start, end = daily_report.day_window(day)
    minute = timedelta(minutes=1)
    # One account at each edge, so a shifted window cannot trade a card lost
    # at one end for one gained at the other and keep the total.
    for word, owner, when in (("before", learner, start - minute), ("first", learner, start),
                              ("last", other, end - minute), ("after", other, end)):
        _run("INSERT INTO flashcards (word, added_by_user_id, created_at) "
             "VALUES (%s, %s, %s)", (word, owner, when))
    for when in (start - minute, start + minute, start + minute):
        _run("INSERT INTO recall_answers (user_id, word, game, correct, answered_at) "
             "VALUES (%s, 'w', 'quiz', 1, %s)", (other, when))
    utils.claim_action(utils.CHAT, learner, 40, amount=3)
    utils.claim_action(utils.LOOKUP_ANON, utils.ALL_ACCOUNTS, 150, amount=2)

    db = daily_report.gather_db(_curdate(), start, end, emails=["Other@Example.com"])

    assert db["cards"] == {learner: 1, other: 1}
    assert db["answers"] == {other: 2}
    assert db["new"] >= {learner, other}
    assert db["usage"][(learner, utils.CHAT)] == 3
    assert db["usage"][(utils.ALL_ACCOUNTS, utils.LOOKUP_ANON)] == 2
    assert db["accounts"][learner]["email"] == "learner@example.com"
    assert db["emails"]["other@example.com"] == other


def test_an_empty_day_reads_nothing(scratch_db):
    from datetime import date

    import daily_report

    start, end = daily_report.day_window(date(2020, 1, 1))
    db = daily_report.gather_db(date(2020, 1, 1), start, end)

    assert db == {"accounts": {}, "new": set(), "cards": {}, "answers": {},
                  "usage": {}, "emails": {}}
