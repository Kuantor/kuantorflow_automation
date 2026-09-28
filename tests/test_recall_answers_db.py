"""The answer log against a real MySQL (kuantorflow#338, phase 1).

`recall_answers` is SQL doing the work: one multi-row INSERT that must give a
round one shared instant, and two foreign keys that must behave *differently*
-- deleting an account erases its rows, deleting a card keeps them. The offline
fakes would agree with any statement, which is why this is `db`-marked
(see test_recall_answers.py for the route side, where fakes are enough).
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

SCRATCH_DB = "kuantorflow_recall_answers_test"

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
    user_id, _ = utils.upsert_user("sub-recall-338", "learner@example.com")
    return user_id


@pytest.fixture()
def cards(scratch_db):
    """Two cards as a round sees them: the dicts `get_flashcards_by_topics()`
    returns, with the ids the database gave them."""
    import utils
    made = []
    for word, pos in (("acquit", "verb"), ("verdict", "noun")):
        card_id = utils.save_flashcard({"word": word, "pos": pos,
                                        "topic": "Law"})
        made.append({"id": card_id, "word": word, "pos": pos})
    return made


def _rows():
    return _query("SELECT user_id, card_id, word, pos, game, correct "
                  "FROM recall_answers ORDER BY id")


@requires_local_db
def test_a_round_is_one_row_per_answer_with_the_word_copied(learner, cards):
    import utils

    written = utils.record_answers(learner, "spell_it",
                                   [(cards[0], True), (cards[1], False)])

    assert written == 2
    assert _rows() == [
        (learner, cards[0]["id"], "acquit", "verb", "spell_it", 1),
        (learner, cards[1]["id"], "verdict", "noun", "spell_it", 0),
    ]


@requires_local_db
def test_a_round_shares_one_instant_and_it_is_utc(learner, cards):
    """No table of rounds: a round is its game and its shared `answered_at`,
    which holds because MySQL evaluates `UTC_TIMESTAMP()` once per statement.
    UTC rather than the server's zone, so #479 has one thing to convert."""
    import utils

    utils.record_answers(learner, "quiz", [(cards[0], True), (cards[1], True)])

    stamps = {row[0] for row in _query("SELECT answered_at FROM recall_answers")}
    assert len(stamps) == 1
    (drift,), = _query("SELECT ABS(TIMESTAMPDIFF(SECOND, MAX(answered_at), "
                       "UTC_TIMESTAMP())) FROM recall_answers")
    assert drift <= 5


@requires_local_db
def test_two_rounds_append_and_never_overwrite(learner, cards):
    """The log is the history; a second round over the same word is a second
    row, which is the whole difference from the counter table this replaced."""
    import utils

    utils.record_answers(learner, "scrambled", [(cards[0], False)])
    utils.record_answers(learner, "scrambled", [(cards[0], True)])

    assert [row[5] for row in _rows()] == [0, 1]


@requires_local_db
def test_deleting_a_card_keeps_what_the_learner_knew(learner, cards):
    """`fk_recall_answers_card` is SET NULL: the card was only what was shown,
    and the word and part of speech carry the memory."""
    import utils

    utils.record_answers(learner, "spell_it", [(cards[0], True)])
    _execute([f"DELETE FROM flashcards WHERE id = {int(cards[0]['id'])}"],
             SCRATCH_DB)

    assert _rows() == [(learner, None, "acquit", "verb", "spell_it", 1)]


@requires_local_db
def test_deleting_the_account_erases_its_answers(learner, cards):
    """`fk_recall_answers_user` is CASCADE -- the first in this schema -- and
    the user guide promises it. Another learner's rows are untouched."""
    import utils

    other, _ = utils.upsert_user("sub-recall-other", "other@example.com")
    utils.record_answers(learner, "quiz", [(cards[0], True)])
    utils.record_answers(other, "quiz", [(cards[0], False)])

    assert utils.delete_user(learner)

    assert [row[0] for row in _rows()] == [other]


@requires_local_db
def test_a_card_with_no_part_of_speech_is_still_recorded(learner, scratch_db):
    """`pos` is nullable on flashcards, and a card without one is still a
    word somebody answered."""
    import utils

    card_id = utils.save_flashcard({"word": "gist", "topic": "Law"})
    utils.record_answers(learner, "quiz",
                         [({"id": card_id, "word": "gist", "pos": None}, True)])

    assert _rows() == [(learner, card_id, "gist", None, "quiz", 1)]
