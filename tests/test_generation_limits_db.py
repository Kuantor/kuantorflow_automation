"""The generated-text ceilings against a real LOCAL MySQL (kuantorflow#237).

`claim_text_generation()` is the one part of #237 a fake cannot prove, because
what it relies on is MySQL's own behaviour:

* `INSERT ... ON DUPLICATE KEY UPDATE` with `IF(texts < limit, ...)` advances
  the row only while it is under the ceiling, and `ROW_COUNT()` reports whether
  *this* call was the one that advanced it. That is what stops two workers both
  taking the last slot, and a fake cursor would simply agree with whatever the
  code assumed.
* The everybody row is keyed on `user_id = 0` rather than the NULL #237's
  comment described. **Only a real database shows why**: MySQL treats NULLs in
  a unique key as distinct, so an upsert against a NULL user_id inserts a
  second row every time instead of incrementing the first, and a PRIMARY KEY
  cannot hold NULL at all. This file pins that down — a well-meaning change
  back to NULL passes every offline test and silently stops counting.

Safety and opt-in are test_apply_schema_db.py's: its own scratch database,
RUN_DB_ROUNDTRIP=1, and localhost only.

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

SCRATCH_DB = "kuantorflow_generation_test"

# No such account. The table deliberately has **no foreign key to users** —
# these are day-scoped counters, not attribution — so an id nobody owns is a
# valid row, and using one here says so.
LEARNER = 987654321

pytestmark = pytest.mark.db


def _prerequisites_met():
    return (
        os.environ.get("RUN_DB_ROUNDTRIP") == "1"
        and os.environ.get("DB_HOST") in ("localhost", "127.0.0.1")
        and os.environ.get("DB_PASSWORD")
        and SCRIPT.exists()
    )


requires_local_db = pytest.mark.skipif(
    not _prerequisites_met(),
    reason="opt-in: set RUN_DB_ROUNDTRIP=1 with a local MySQL (DB_HOST=localhost) "
    "and DB_* configured; the test creates its own scratch database",
)


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


@pytest.fixture()
def scratch_db(monkeypatch):
    """A scratch database with the schema applied, and utils pointed at it."""
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


def _rows():
    conn = _connect(SCRATCH_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, texts FROM text_generation_usage "
                   "WHERE day = CURDATE() ORDER BY user_id")
    found = cursor.fetchall()
    cursor.close()
    conn.close()
    return found


@pytest.fixture()
def claim(scratch_db):
    import utils
    return utils.claim_text_generation


# --- the per-account ceiling ------------------------------------------------

@requires_local_db
def test_a_learner_gets_their_allowance_and_then_does_not(claim):
    assert [claim(LEARNER, 3, 100)[0] for _ in range(4)] == [True, True, True, False]


@requires_local_db
def test_the_refusal_names_the_ceiling_that_refused(claim):
    for _ in range(3):
        claim(LEARNER, 3, 100)
    allowed, scope, used = claim(LEARNER, 3, 100)
    assert (allowed, scope, used) == (False, "user", 3)


@requires_local_db
def test_a_refused_claim_does_not_advance_the_row(claim):
    """The ceiling is a ceiling, not a counter of attempts — otherwise
    tomorrow's allowance would depend on how often somebody pressed a button
    today."""
    for _ in range(10):
        claim(LEARNER, 2, 100)
    assert dict(_rows())[LEARNER] == 2


# --- the site-wide ceiling --------------------------------------------------

@requires_local_db
def test_everybody_is_counted_on_one_row(claim):
    """user_id 0, and it has to be a real value: a NULL here would insert a new
    row per generation and count nothing (see this file's docstring)."""
    claim(11, 50, 100)
    claim(22, 50, 100)
    claim(33, 50, 100)
    assert dict(_rows())[0] == 3


@requires_local_db
def test_the_site_wide_ceiling_refuses_everyone(claim):
    claim(11, 50, 2)
    claim(22, 50, 2)
    allowed, scope, _ = claim(33, 50, 2)
    assert (allowed, scope) == (False, "daily")


@requires_local_db
def test_an_anonymous_visitor_counts_towards_the_daily_ceiling_only(claim):
    """They have no account row — the session counter is their own nudge — but
    their texts cost the same money as anybody's."""
    claim(None, 10, 100)
    claim(None, 10, 100)
    assert _rows() == [(0, 2)]


@requires_local_db
def test_the_account_claim_is_taken_first_even_when_the_site_is_exhausted(claim):
    """Deliberate, and documented as the lesser of two evils: the learner may
    spend one of their ten on a day the site is exhausted anyway. The reverse
    order burns a site-wide slot for somebody already over their own limit."""
    claim(11, 50, 1)                       # takes the one site-wide slot
    allowed, scope, _ = claim(LEARNER, 50, 1)
    assert (allowed, scope) == (False, "daily")
    assert dict(_rows())[LEARNER] == 1     # their row advanced regardless


# --- no ceiling -------------------------------------------------------------

@requires_local_db
def test_a_limit_of_zero_means_no_ceiling_and_writes_nothing(claim):
    assert claim(LEARNER, 0, 0) == (True, None, 0)
    assert _rows() == []
