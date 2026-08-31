"""The word-lookup ceilings against a real LOCAL MySQL (kuantorflow#388).

`claim_word_lookup()` is the part a fake cannot prove, because what it relies
on is MySQL's own behaviour:

* `INSERT ... ON DUPLICATE KEY UPDATE` with `IF(lookups < limit, ...)` advances
  the row only while it is under the ceiling, and `ROW_COUNT()` reports whether
  *this* call was the one that advanced it. That is what stops two workers both
  taking the last slot, and a fake cursor would agree with whatever the code
  assumed.
* The anonymous row is keyed on `user_id = 0`, for #237's reason: MySQL treats
  NULLs in a unique key as distinct, so an upsert against a NULL user_id
  inserts a fresh row every time instead of incrementing the first.

And one thing that is this ticket's own rather than #237's: **the two rows are
independent**. An account is counted on its own row and an anonymous visitor on
row 0, so a day of anonymous traffic hitting its ceiling leaves a signed-in
learner with everything they had. That is the failure #199 names for #164's
shared ceiling, and it is worth proving against the database rather than
against a comment.

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

SCRATCH_DB = "kuantorflow_lookup_cap_test"

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
    cursor.execute("SELECT user_id, lookups FROM word_lookup_usage "
                   "WHERE day = CURDATE() ORDER BY user_id")
    found = cursor.fetchall()
    cursor.close()
    conn.close()
    return found


@pytest.fixture()
def claim(scratch_db):
    import utils
    return utils.claim_word_lookup


ANONYMOUS = None        # what the app passes for a visitor with no account


# --- the per-account ceiling ------------------------------------------------

@requires_local_db
def test_a_learner_gets_their_allowance_and_then_does_not(claim):
    assert [claim(LEARNER, 3, 100)[0] for _ in range(4)] == [
        True, True, True, False]


@requires_local_db
def test_the_refusal_names_the_ceiling_and_the_count(claim):
    for _ in range(3):
        claim(LEARNER, 3, 100)

    assert claim(LEARNER, 3, 100) == (False, "user", 3)


@requires_local_db
def test_a_learner_is_never_counted_against_the_anonymous_row(claim):
    claim(LEARNER, 3, 100)

    assert _rows() == [(LEARNER, 1)], "no row 0, so nothing was double-counted"


# --- the anonymous ceiling --------------------------------------------------

@requires_local_db
def test_anonymous_lookups_land_on_row_zero(claim):
    claim(ANONYMOUS, 50, 2)

    assert _rows() == [(0, 1)]


@requires_local_db
def test_and_stop_at_their_own_ceiling(claim):
    assert [claim(ANONYMOUS, 50, 2)[0] for _ in range(3)] == [True, True, False]
    assert claim(ANONYMOUS, 50, 2)[1] == "anonymous"


# --- the property the design is for -----------------------------------------

@requires_local_db
def test_a_day_of_anonymous_traffic_leaves_a_learner_untouched(claim):
    """The reason the site-wide row counts anonymous lookups only. With #237's
    shape -- one row counting everybody -- this test is the failure #199
    describes: one visitor in a loop spends the day and the people who signed
    up are told to come back tomorrow.
    """
    while claim(ANONYMOUS, 50, 3)[0]:
        pass

    assert claim(LEARNER, 50, 3)[0] is True
    assert _rows() == [(0, 3), (LEARNER, 1)]


@requires_local_db
def test_two_learners_do_not_share_a_ceiling(claim):
    claim(LEARNER, 1, 100)

    assert claim(LEARNER + 1, 1, 100)[0] is True


# --- switches ---------------------------------------------------------------

@requires_local_db
def test_a_ceiling_of_zero_is_no_ceiling(claim):
    """How a deployment turns either half off -- and it must not leave a row
    behind either, or "off" would still be counting."""
    assert [claim(LEARNER, 0, 100)[0] for _ in range(5)] == [True] * 5
    assert _rows() == []


@requires_local_db
def test_the_count_is_the_day_and_not_the_run(claim):
    """The primary key is (day, user_id), so yesterday's row cannot refuse
    today's lookup."""
    claim(LEARNER, 2, 100)
    _execute(["UPDATE word_lookup_usage SET day = day - INTERVAL 1 DAY"],
             database=SCRATCH_DB)

    assert [claim(LEARNER, 2, 100)[0] for _ in range(2)] == [True, True]
