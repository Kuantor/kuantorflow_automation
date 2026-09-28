"""The SM-2 schedule against a real MySQL (kuantorflow#479).

`recall.replay()`'s rules are tested on plain lists in test_recall_schedule.py.
What only a database can show is the part around it: that the live refresh
and the rebuild script write **the same table** from the same log -- the whole
point of the schedule being a cache -- that the upsert really is idempotent,
that a case-insensitive key does not split a word in two, and that the table
leaves with the account.
"""

import os
import subprocess
import sys
from datetime import datetime, timedelta
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
REBUILD = KUANTORFLOW_PATH / "scripts" / "rebuild_schedule.py"

SCRATCH_DB = "kuantorflow_recall_schedule_test"

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


def _execute(statements, database=None, params=None):
    conn = _connect(database)
    cursor = conn.cursor()
    for statement in statements:
        cursor.execute(statement, params)
    conn.commit()
    cursor.close()
    conn.close()


def _query(sql, params=()):
    conn = _connect(SCRATCH_DB)
    cursor = conn.cursor()
    cursor.execute(sql, params)
    found = cursor.fetchall()
    cursor.close()
    conn.close()
    return found


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


@pytest.fixture()
def learner(scratch_db):
    import utils
    user_id, _ = utils.upsert_user("sub-schedule-479", "learner@example.com")
    return user_id


def _log(user_id, word, pos, game, correct, when):
    """A log row at a chosen instant -- `record_answers()` always writes now,
    and a schedule is about days."""
    _execute(["INSERT INTO recall_answers (user_id, card_id, word, pos, game, "
              "correct, answered_at) VALUES (%s, NULL, %s, %s, %s, %s, %s)"],
             SCRATCH_DB, (user_id, word, pos, game, int(correct), when))


def _table(user_id=None):
    where = " WHERE user_id = %s" if user_id else ""
    return _query("SELECT user_id, word, pos, reps, lapses, ease, "
                  "interval_days, due_on FROM recall_schedule" + where
                  + " ORDER BY user_id, word, pos",
                  (user_id,) if user_id else ())


def _history(learner):
    """Three words over three weeks: one climbing, one lapsing, one ticked."""
    for day, correct in ((1, True), (2, True), (8, True)):
        _log(learner, "acquit", "verb", "spell_it", correct,
             datetime(2026, 9, day, 9))
    for day, correct in ((1, True), (2, True), (5, False)):
        _log(learner, "verdict", "noun", "quiz", correct,
             datetime(2026, 9, day, 9))
    for day in (1, 2):
        _log(learner, "bail", "noun", "fill_the_gap", True,
             datetime(2026, 9, day, 9))


# --- the live refresh ---------------------------------------------------------

@requires_local_db
def test_a_refresh_writes_what_the_replay_says(learner):
    import recall
    import utils

    _history(learner)
    written = utils.refresh_schedule(learner, [("acquit", "verb"),
                                               ("verdict", "noun"),
                                               ("bail", "noun")])

    assert written == 3
    rows = {row[1]: row[3:] for row in _table()}
    assert rows["acquit"] == (3, 0, 2500, 15, datetime(2026, 9, 23).date())
    assert rows["verdict"] == (0, 1, 2300, 1, datetime(2026, 9, 6).date())
    # Two ticks: 1 day, then half-way to 6 -- weaker than a checked 6.
    assert rows["bail"][3] == 4
    assert rows["bail"][3] < recall.replay([recall.Answer(datetime(2026, 9, d, 9), True)
                                            for d in (1, 2)]).interval_days


@requires_local_db
def test_a_refresh_touches_only_the_words_it_was_given(learner):
    import utils

    _history(learner)
    utils.refresh_schedule(learner, [("acquit", "verb")])

    assert [row[1] for row in _table()] == ["acquit"]


@requires_local_db
def test_refreshing_twice_changes_nothing(learner):
    import utils

    _history(learner)
    words = [("acquit", "verb"), ("verdict", "noun")]
    utils.refresh_schedule(learner, words)
    first = _table()
    utils.refresh_schedule(learner, words)

    assert _table() == first


@requires_local_db
def test_a_word_with_no_part_of_speech_is_keyed_on_the_empty_string(learner):
    """A primary key holds no NULL, so the log's NULL `pos` is '' here."""
    import utils

    _log(learner, "gist", None, "quiz", True, datetime(2026, 9, 1, 9))
    utils.refresh_schedule(learner, [("gist", None)])

    assert _table()[0][1:3] == ("gist", "")


@requires_local_db
def test_two_spellings_of_one_word_are_one_schedule(learner):
    """The key's collation is case-insensitive, so `Tip` and `tip` are one row
    to MySQL. Grouped apart, the second upsert would overwrite the first and
    the word would look answered once instead of twice."""
    import utils

    _log(learner, "Tip", "noun", "quiz", True, datetime(2026, 9, 1, 9))
    _log(learner, "tip", "noun", "quiz", True, datetime(2026, 9, 2, 9))
    utils.refresh_schedule(learner, [("tip", "noun")])

    rows = _table()
    assert len(rows) == 1
    assert (rows[0][3], rows[0][6]) == (2, 6)


@requires_local_db
def test_a_round_through_record_answers_is_scheduled(learner):
    """The two calls `_record_recall()` makes, in its order, against the real
    tables: the log row the first one writes is what the second one replays."""
    import utils

    card = {"id": None, "word": "acquit", "pos": "verb"}
    utils.record_answers(learner, "spell_it", [(card, True)])
    utils.refresh_schedule(learner, [("acquit", "verb")])

    (row,) = _table()
    assert row[3:7] == (1, 0, 2500, 1)


# --- the rebuild ---------------------------------------------------------------

@requires_local_db
def test_the_rebuild_writes_exactly_what_the_live_refresh_writes(learner):
    """The reason the schedule can be called a cache: two paths, one table."""
    import utils

    _history(learner)
    utils.refresh_schedule(learner, [("acquit", "verb"), ("verdict", "noun"),
                                     ("bail", "noun")])
    live = _table()
    _execute(["DELETE FROM recall_schedule"], SCRATCH_DB)

    report = utils.rebuild_schedules()

    assert _table() == live
    assert report == {learner: (3, 0, 0, 0)}


@requires_local_db
def test_a_second_rebuild_has_nothing_to_do(learner):
    import utils

    _history(learner)
    utils.rebuild_schedules()

    assert utils.rebuild_schedules() == {learner: (0, 0, 3, 0)}


@requires_local_db
def test_a_dry_run_reports_and_writes_nothing(learner):
    import utils

    _history(learner)

    assert utils.rebuild_schedules(dry_run=True) == {learner: (3, 0, 0, 0)}
    assert _table() == []


@requires_local_db
def test_the_rebuild_corrects_a_wrong_row_and_removes_an_orphan(learner):
    """What a rule change looks like from the table's side: rows that no longer
    match the log are rewritten, and a row with no history is removed."""
    import utils

    _history(learner)
    utils.rebuild_schedules()
    _execute(["UPDATE recall_schedule SET interval_days = 99 "
              "WHERE word = 'acquit'",
              "INSERT INTO recall_schedule (user_id, word, pos, due_on) "
              f"VALUES ({int(learner)}, 'ghost', 'noun', '2026-09-30')"],
             SCRATCH_DB)

    assert utils.rebuild_schedules() == {learner: (0, 1, 2, 1)}
    assert [row[1] for row in _table()] == ["acquit", "bail", "verdict"]
    assert _table()[0][6] == 15


@requires_local_db
def test_one_learners_rebuild_leaves_the_others_alone(learner):
    import utils

    other, _ = utils.upsert_user("sub-schedule-other", "other@example.com")
    _history(learner)
    _log(other, "acquit", "verb", "quiz", True, datetime(2026, 9, 1, 9))

    assert utils.rebuild_schedules(learner) == {learner: (3, 0, 0, 0)}
    assert _table(other) == []


@requires_local_db
def test_deleting_the_account_deletes_its_schedule(learner):
    import utils

    _history(learner)
    utils.rebuild_schedules()
    assert utils.delete_user(learner)

    assert _table() == []


# --- the console script --------------------------------------------------------

@requires_local_db
def test_the_script_dry_runs_applies_and_then_has_nothing_to_do(learner):
    """The deploy's three commands, as a PythonAnywhere console would run them:
    from the repo root, against the scratch database."""
    _history(learner)

    def run(*args):
        result = subprocess.run([sys.executable, str(REBUILD), *args],
                                capture_output=True, text=True,
                                env=dict(os.environ, DB_NAME=SCRATCH_DB),
                                cwd=str(KUANTORFLOW_PATH))
        assert result.returncode == 0, result.stderr
        return result.stdout

    dry = run("--dry-run")
    assert f"~ user {learner}: 3 new" in dry and "nothing written" in dry
    assert _table() == []

    applied = run()
    assert f"+ user {learner}: 3 new" in applied
    assert len(_table()) == 3

    assert "nothing to do" in run()


@requires_local_db
def test_the_script_refuses_an_unknown_learner(learner):
    result = subprocess.run([sys.executable, str(REBUILD), "--user",
                             "nobody@example.com"], capture_output=True,
                            text=True, env=dict(os.environ, DB_NAME=SCRATCH_DB),
                            cwd=str(KUANTORFLOW_PATH))

    assert result.returncode == 1
    assert "no account" in result.stderr
