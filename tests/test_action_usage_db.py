"""One table for every ceiling (kuantorflow#447).

`anonymous_usage` (#164), `text_generation_usage` (#237) and
`word_lookup_usage` (#388) were the same table three times, differing only in
the name of the counter column. #447 needs ceilings on three more actions, and
six copies would have made the repetition the design.

`test_word_lookup_cap_db.py` and `test_generation_limits_db.py` already cover
the *ceilings* against a real database, and they pass unchanged against the new
storage — that is the "no behaviour change" half. This file covers what is
genuinely new and could not exist before: **two shared pools on the same row
id**, and the all-or-nothing claim as a primitive rather than as a special case
inside the lookup functions.

The pools matter because `user_id = 0` used to mean two different things in
the two tables it appeared in — anonymous lookups only in #388, everybody's
texts in #237 — and one table would have collided them into a single counter.
The action name is what keeps them apart, so it is what this asserts.
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

SCRATCH_DB = "kuantorflow_action_usage_test"

# No such account: the table has no foreign key to `users` on purpose, so an
# id nobody owns is a valid row and using one says so.
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
    cursor.execute("SELECT user_id, action, used FROM action_usage "
                   "WHERE day = CURDATE() ORDER BY user_id, action")
    found = cursor.fetchall()
    cursor.close()
    conn.close()
    return found


# --- the thing one table made possible, and had to get right ----------------

@requires_local_db
def test_two_shared_pools_share_a_row_id_without_sharing_a_counter(scratch_db):
    """The collision the old design could not have, and the new one must not.

    `user_id = 0` meant anonymous-lookups-only in #388 and everybody's-texts
    in #237. They lived in different tables, so nothing had to reconcile them.
    In one table they are two rows distinguished by nothing but the action, and
    if that were wrong an anonymous word lookup would silently spend the
    reader's site-wide budget.
    """
    import utils

    utils.claim_action(utils.LOOKUP_ANON, utils.ALL_ACCOUNTS, 100)
    utils.claim_action(utils.LOOKUP_ANON, utils.ALL_ACCOUNTS, 100)
    utils.claim_action(utils.GENERATE_ALL, utils.ALL_ACCOUNTS, 100)

    assert _rows() == [(0, "generate:all", 1), (0, "lookup:anon", 2)]


@requires_local_db
def test_an_account_and_the_shared_pool_are_different_rows(scratch_db):
    """#388's whole point, now expressed in the data rather than in a
    docstring: a signed-in learner meets their own ceiling and nothing else."""
    import utils

    utils.claim_action(utils.LOOKUP, LEARNER, 50)
    utils.claim_action(utils.LOOKUP_ANON, utils.ALL_ACCOUNTS, 300)

    assert _rows() == [(0, "lookup:anon", 1), (LEARNER, "lookup", 1)]


# --- the claim itself -------------------------------------------------------

@requires_local_db
def test_a_batch_is_taken_whole_or_not_at_all(scratch_db):
    """#406 approves twenty words before any is looked up. A partial claim is
    the half-built topic the ceiling exists to prevent -- twelve looked up and
    the thirteenth refused, with no way back."""
    import utils

    taken, used = utils.claim_action(utils.LOOKUP, LEARNER, 10, amount=8)
    assert (taken, used) == (True, 8)

    refused, still = utils.claim_action(utils.LOOKUP, LEARNER, 10, amount=5)
    assert refused is False, "a batch that does not fit was allowed through"
    assert still == 8, "a refused batch advanced the row anyway"


@requires_local_db
def test_the_last_slot_goes_to_exactly_one_caller(scratch_db):
    """`ROW_COUNT()` after the conditional update is what says whether *this*
    call was the one that advanced the row. Without it two workers both read
    'under the limit' and both spend."""
    import utils

    for _ in range(3):
        assert utils.claim_action(utils.CHAT, LEARNER, 3)[0] is True
    assert utils.claim_action(utils.CHAT, LEARNER, 3)[0] is False
    assert _rows() == [(LEARNER, "chat", 3)]


@requires_local_db
def test_no_ceiling_means_no_row_and_no_connection(scratch_db):
    """A limit of 0 turns a ceiling off, and it answers without writing
    anything -- which is also how the suite's offline tier survives these."""
    import utils

    assert utils.claim_action(utils.CHAT, LEARNER, 0) == (True, 0)
    assert _rows() == []


@requires_local_db
def test_the_count_is_the_day_and_not_the_run(scratch_db):
    """Yesterday's row is a different row, so a ceiling resets at midnight
    rather than accumulating forever."""
    import utils

    utils.claim_action(utils.CHAT, LEARNER, 5)
    _execute(["UPDATE action_usage SET day = day - INTERVAL 1 DAY"], SCRATCH_DB)

    taken, used = utils.claim_action(utils.CHAT, LEARNER, 5)
    assert (taken, used) == (True, 1), "yesterday's count was carried forward"


@requires_local_db
def test_reading_a_ceiling_does_not_spend_it(scratch_db):
    """#406 states the cost on the approve screen before anything is claimed,
    so the read has to be free."""
    import utils

    utils.claim_action(utils.LOOKUP, LEARNER, 50, amount=4)

    assert utils.action_used_today(utils.LOOKUP, LEARNER) == 4
    assert utils.action_used_today(utils.LOOKUP, LEARNER) == 4
    assert _rows() == [(LEARNER, "lookup", 4)]
