"""
Editing a card against a real LOCAL MySQL (marker: db) — kuantorflow#176.

Two of #176's acceptance criteria cannot be proved against a fake: that an
edit leaves `created_at` alone, which depends on MySQL's own timestamp
behaviour, and that examples survive a round trip as **lists** rather than as
a JSON string in a text field.

Safety: this creates and drops its own scratch database and never touches the
configured one. Opt-in via RUN_DB_ROUNDTRIP=1, as the other db tests are.

    # PowerShell
    $env:RUN_DB_ROUNDTRIP="1"; pytest -m db
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from dotenv import load_dotenv

AUTO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(AUTO_ROOT / ".env")

KUANTORFLOW_PATH = Path(os.environ.get(
    "KUANTORFLOW_PATH", str(AUTO_ROOT.parent.parent / "kuantorflow")))
SCRATCH_DB = "kuantorflow_edit_test"

pytestmark = pytest.mark.db


def _prerequisites_met():
    return (
        os.environ.get("RUN_DB_ROUNDTRIP") == "1"
        and os.environ.get("DB_HOST") in ("localhost", "127.0.0.1")
        and os.environ.get("DB_PASSWORD")
        and (KUANTORFLOW_PATH / "apply_schema.py").exists()
    )


requires_local_db = pytest.mark.skipif(
    not _prerequisites_met(),
    reason="opt-in: set RUN_DB_ROUNDTRIP=1 with a local MySQL (DB_HOST=localhost); "
    "the test creates its own scratch database")


def _connect(database=None):
    import mysql.connector
    return mysql.connector.connect(
        user=os.environ.get("DB_USER", "kuantorflow"),
        password=os.environ["DB_PASSWORD"],
        host=os.environ["DB_HOST"],
        database=database)


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
    """A throwaway database, with the schema applied by the real deploy step."""
    _execute([f"DROP DATABASE IF EXISTS {SCRATCH_DB}",
              f"CREATE DATABASE {SCRATCH_DB} CHARACTER SET utf8mb4"])
    subprocess.run([sys.executable, str(KUANTORFLOW_PATH / "apply_schema.py")],
                   capture_output=True, text=True,
                   env=dict(os.environ, DB_NAME=SCRATCH_DB), check=True)
    # utils.get_db_connection() reads DB_NAME at call time, so this redirects
    # every helper below without touching how they are written.
    monkeypatch.setenv("DB_NAME", SCRATCH_DB)
    try:
        yield SCRATCH_DB
    finally:
        monkeypatch.undo()
        _execute([f"DROP DATABASE IF EXISTS {SCRATCH_DB}"])


@requires_local_db
def test_an_edit_leaves_created_at_alone(scratch_db):
    """created_at is the card's age, not its last touch. MySQL will happily
    add ON UPDATE CURRENT_TIMESTAMP to the first timestamp column of a table
    if it is declared loosely, which would silently reset every card's age."""
    import utils

    card_id = utils.save_flashcard(
        {"word": "resilient", "pos": "adjective", "topic": "vocab",
         "explanation_en": "before"})
    assert card_id, "the fixture database should be empty"

    conn = _connect(SCRATCH_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT created_at FROM flashcards WHERE id = %s", (card_id,))
    before = cursor.fetchone()[0]
    conn.close()

    time.sleep(1.1)          # a second of resolution, so a reset would show
    outcome, changed = utils.update_flashcard(
        card_id, {"explanation_en": "after"}, admin=True)
    assert (outcome, changed) == ("updated", ["explanation_en"])

    conn = _connect(SCRATCH_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT created_at, explanation_en FROM flashcards WHERE id = %s",
                   (card_id,))
    after, explanation = cursor.fetchone()
    conn.close()

    assert explanation == "after", "the edit did land"
    assert after == before, "created_at must not move when a card is edited"


@requires_local_db
def test_examples_survive_the_round_trip_as_lists(scratch_db):
    """Stored as JSON, read back as a list — not as a string that happens to
    look like one, which is what a card page would then render character by
    character."""
    import utils

    card_id = utils.save_flashcard(
        {"word": "resilient", "pos": "adjective", "topic": "vocab",
         "examples_en": ["first"]})
    utils.update_flashcard(card_id, {"examples_en": ["one", "two"]}, admin=True)

    cards = utils.get_flashcards_by_topic("vocab")
    assert len(cards) == 1
    assert cards[0]["examples_en"] == ["one", "two"]


@requires_local_db
def test_a_rename_onto_an_existing_card_is_refused_for_real(scratch_db):
    """The duplicate rule, against the real NULL-safe comparison rather than
    a fake that always answers the same way."""
    import utils

    keeper = utils.save_flashcard({"word": "walk", "pos": "verb", "topic": "vocab"})
    edited = utils.save_flashcard({"word": "run", "pos": "verb", "topic": "vocab"})

    outcome, detail = utils.update_flashcard(edited, {"word": "walk"}, admin=True)
    assert outcome == "duplicate"
    assert detail[0] == keeper

    # ...and the card is untouched by the refusal
    cards = {c["word"]: c for c in utils.get_flashcards_by_topic("vocab")}
    assert sorted(cards) == ["run", "walk"]


@requires_local_db
def test_a_card_can_be_renamed_to_a_free_word(scratch_db):
    """The card must not count as its own duplicate — without the exclusion
    this is the case that fails."""
    import utils

    card_id = utils.save_flashcard({"word": "run", "pos": "verb", "topic": "vocab"})
    outcome, changed = utils.update_flashcard(
        card_id, {"word": "sprint"}, admin=True)
    assert (outcome, changed) == ("updated", ["word"])

    # And saving it again unchanged is still "nothing to do", not a collision.
    assert utils.update_flashcard(card_id, {"word": "sprint"},
                                  admin=True) == ("unchanged", [])
