"""`upsert_user()`'s "is this account new?" against a real MySQL (kuantorflow#592).

The new-account notice rests on one number MySQL reports: the rowcount of an
`INSERT ... ON DUPLICATE KEY UPDATE` is 1 for an insert, 2 for an update and 0
for a row left as it was -- **unless** the connection asks for "found rows",
when an unchanged row counts 1 too and a returning learner would look new.
The offline fake answers whatever it is told, so only a real server can say
which of those the app's connection gets.
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

SCRATCH_DB = "kuantorflow_new_account_test"

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


def test_the_first_sign_in_is_new_and_the_next_ones_are_not(scratch_db):
    import utils

    first_id, _, created = utils.upsert_user("sub-592", "new@example.com", "New One")
    assert created is True

    for _ in range(3):      # back to back: at least two land in the same second,
        user_id, _, created = utils.upsert_user(  # an unchanged row (rowcount 0)
            "sub-592", "new@example.com", "New One")
        assert (user_id, created) == (first_id, False)


def test_an_email_change_is_not_a_new_account(scratch_db):
    import utils

    first_id, _, _ = utils.upsert_user("sub-592b", "old@example.com")
    user_id, _, created = utils.upsert_user("sub-592b", "renamed@example.com")

    assert (user_id, created) == (first_id, False)


def test_a_second_person_is_new(scratch_db):
    import utils

    utils.upsert_user("sub-a", "a@example.com")
    _, _, created = utils.upsert_user("sub-b", "b@example.com")

    assert created is True
    assert utils.count_users() == 2
