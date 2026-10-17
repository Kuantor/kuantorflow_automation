"""`weekly_numbers.db_numbers()` against a real MySQL (kuantorflow#607).

Visits grouped per UTC day with their anonymous share, distinct visitors,
seconds and pages, and the accounts created since a date -- SQL the offline
stub cannot check.
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

SCRATCH_DB = "kuantorflow_weekly_numbers_test"

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


def test_visits_per_day_and_the_accounts(scratch_db):
    from datetime import date

    import utils
    import weekly_numbers

    learner, _, _ = utils.upsert_user("sub-607", "learner@example.com")
    conn = utils.get_db_connection()
    cursor = conn.cursor()
    rows = [("a" * 16, None, "2026-10-12 08:00:00", 60, 2),
            ("a" * 16, None, "2026-10-12 15:00:00", 30, 1),
            ("b" * 16, learner, "2026-10-12 23:59:59", 90, 3),
            ("c" * 16, None, "2026-10-13 00:00:00", 10, 1),
            ("d" * 16, None, "2026-10-09 23:00:00", 999, 9)]
    for visitor, user_id, started, seconds, pages in rows:
        cursor.execute("INSERT INTO visits (visitor, user_id, started_at, last_seen_at, "
                       "active_seconds, pages) VALUES (%s, %s, %s, %s, %s, %s)",
                       (visitor, user_id, started, started, seconds, pages))
    conn.commit()
    cursor.close()
    conn.close()

    numbers = weekly_numbers.db_numbers("2026-10-10")

    assert numbers["visits"] == [(date(2026, 10, 12), 3, 2, 2, 180, 6),
                                 (date(2026, 10, 13), 1, 1, 1, 10, 1)]
    assert numbers["accounts"] == 1 and numbers["new"] == 1
