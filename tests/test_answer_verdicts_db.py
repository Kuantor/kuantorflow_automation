"""`answer_verdicts` and the answer-check ceiling on a real MySQL (kuantorflow#612).

Verdicts stored and read back by (language, word, part of speech, answer),
a re-judged answer keeping its first verdict, languages and parts of speech
kept apart; and `claim_answer_check()` spending its three pools like every
paid action.
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

SCRATCH_DB = "kuantorflow_answer_verdicts_test"

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


def test_verdicts_are_stored_and_read_back(scratch_db):
    import utils

    utils.save_answer_verdicts("ukr", [("heritage", "noun", "спадок", "yellow", "narrower"),
                                       ("despondent", "adjective", "пригнічений", "green", "")])

    assert utils.answer_verdicts("ukr", [("heritage", "noun", "спадок"),
                                         ("despondent", "adjective", "пригнічений"),
                                         ("heritage", "noun", "традиція")]) == {
        ("heritage", "noun", "спадок"): ("yellow", "narrower"),
        ("despondent", "adjective", "пригнічений"): ("green", "")}


def test_the_first_verdict_is_kept(scratch_db):
    import utils

    utils.save_answer_verdicts("ukr", [("heritage", "noun", "спадок", "yellow", "first")])
    assert utils.save_answer_verdicts("ukr", [("heritage", "noun", "спадок", "green", "second")]) == 0

    assert utils.answer_verdicts("ukr", [("heritage", "noun", "спадок")])[
        ("heritage", "noun", "спадок")] == ("yellow", "first")


def test_language_and_part_of_speech_are_kept_apart(scratch_db):
    import utils

    utils.save_answer_verdicts("ukr", [("record", "noun", "запис", "green", "")])

    assert utils.answer_verdicts("rus", [("record", "noun", "запис")]) == {}
    assert utils.answer_verdicts("ukr", [("record", "verb", "запис")]) == {}


def test_the_ceiling_spends_its_pools(scratch_db):
    import utils

    learner, _, _ = utils.upsert_user("sub-612", "learner@example.com")
    answers = [utils.claim_answer_check(learner, 2, 5, 100) for _ in range(3)]

    assert [a[0] for a in answers] == [True, True, False]
    assert answers[2][1] == "user"
    assert utils.claim_answer_check(None, 2, 1, 100)[0] is True
    assert utils.claim_answer_check(None, 2, 1, 100)[1] == "anonymous"
