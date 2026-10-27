"""A failed statement in a DB test helper no longer holds up `DROP DATABASE`
(found during kuantorflow#210) -- against real MySQL (marker: db).

`test_db_helpers_close.py` checks the rule in every file. This shows what the
rule prevents, with a real helper: a statement fails after an INSERT has locked
a table, the error is kept the way pytest keeps one, and the scratch database
must still drop. The drop runs with `lock_wait_timeout = 5`, so a regression
fails in five seconds instead of hanging the tier as it did twice.
"""

import os

import pytest

import test_topics_table_db as helpers

SCRATCH_DB = "kuantorflow_helpers_close_test"

pytestmark = pytest.mark.db


def _drop(timeout_seconds=5):
    conn = helpers._connect(None)
    try:
        cursor = conn.cursor()
        cursor.execute(f"SET SESSION lock_wait_timeout = {timeout_seconds}")
        cursor.execute(f"DROP DATABASE IF EXISTS {SCRATCH_DB}")
        cursor.close()
    finally:
        conn.close()


@helpers.requires_local_db
def test_a_failed_statement_does_not_hold_up_the_drop():
    _drop()
    helpers._execute([f"CREATE DATABASE {SCRATCH_DB}"], database=None)
    helpers._execute(["CREATE TABLE cards (id INT)"], database=SCRATCH_DB)

    # The INSERT takes a lock on `cards`; the second statement fails. Kept as
    # `failed`, the way pytest keeps a failure's traceback -- which is what
    # used to keep the helper's connection, and its lock, alive.
    with pytest.raises(Exception) as failed:
        helpers._execute(["INSERT INTO cards VALUES (1)",
                          "INSERT INTO no_such_table VALUES (1)"],
                         database=SCRATCH_DB)

    try:
        _drop()                    # raises "Lock wait timeout" if still held
    finally:
        del failed
