"""Consolidating topics against a real LOCAL MySQL (marker: db) —
kuantorflow#407.

`test_retopic.py` proves the *plans* are applicable. This proves the four
things about the **writes** that no fake cursor can answer, because a fake
agrees with any statement it is handed:

* a merge moves `flashcards.topic_id` **and** `flashcards.topic` together
  (#207) -- the string is what ai_agent's `cards_db` reads, so a merge that
  moved only the id would leave Mykola naming topics that no longer exist, and
  every offline assertion about the UPDATE would still pass;
* the emptied source row is gone afterwards, which `fk_flashcards_topic`'s
  ON DELETE RESTRICT (#165) only permits once the last card has left;
* a merge that would put the same word and part of speech in one topic twice is
  **refused**, since a bulk UPDATE does not go through `save_flashcard()` and so
  does not inherit #101;
* a second run is quiet -- and specifically that a **case-only rename** is quiet,
  which is the bug this file was written after. `find_topic()` matches the way
  the unique key collates, so `character and personality` still resolved to the
  row after it became `Character and personality`, and every later run renamed
  it onto itself and wrote a log line for work already done.

And one about the rehearsal: `--dry-run` applies every step and rolls back, so
what it prints is what the database did rather than what the script guessed.
A rollback that did not hold would be a dry run that silently wrote.

Safety: this builds and drops its **own** scratch database and never touches
the configured one. Opt-in with the same switch as the other db tests:

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
SCHEMA_SCRIPT = KUANTORFLOW_PATH / "apply_schema.py"

SCRATCH_DB = "kuantorflow_retopic_test"

pytestmark = pytest.mark.db


def _prerequisites_met():
    return (
        os.environ.get("RUN_DB_ROUNDTRIP") == "1"
        and os.environ.get("DB_HOST") in ("localhost", "127.0.0.1")
        and os.environ.get("DB_PASSWORD")
        and SCHEMA_SCRIPT.exists()
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


def _execute(statements, database=SCRATCH_DB):
    conn = _connect(database)
    cursor = conn.cursor()
    for statement in statements:
        cursor.execute(statement)
    conn.commit()
    cursor.close()
    conn.close()


def _rows(query):
    conn = _connect(SCRATCH_DB)
    cursor = conn.cursor()
    cursor.execute(query)
    found = cursor.fetchall()
    cursor.close()
    conn.close()
    return found


def _topics():
    return {name: tid for tid, name in _rows("SELECT id, name FROM topics")}


def _cards():
    """`{card id: (topic_id, topic string)}` -- both columns, which is the point.

    Keyed by **id**, not by the word: the fixture holds `plum` as a noun in two
    different topics on purpose, because that is the collision case, so any key
    built from the card's content silently drops one of them.
    """
    return {cid: (tid, name) for cid, tid, name
            in _rows("SELECT id, topic_id, topic FROM flashcards")}


def _in_topic(topic_id):
    """`{(word, pos): topic string}` for one topic, which is unique within it —
    #101's whole rule."""
    return {(w, pos): name for w, pos, name in _rows(
        "SELECT word, pos, topic FROM flashcards "
        f"WHERE topic_id = {topic_id}")}


@pytest.fixture()
def deck(monkeypatch, tmp_path):
    """A scratch database holding one of each case the writes have to handle.

    Built by running the app's own `apply_schema.py`, so the columns under test
    are the ones a deploy makes rather than a hand-written copy that could drift.
    """
    _execute([f"DROP DATABASE IF EXISTS {SCRATCH_DB}",
              f"CREATE DATABASE {SCRATCH_DB} CHARACTER SET utf8mb4"],
             database=None)
    env = dict(os.environ, DB_NAME=SCRATCH_DB)
    done = subprocess.run([sys.executable, str(SCHEMA_SCRIPT)],
                          capture_output=True, text=True, env=env,
                          cwd=str(KUANTORFLOW_PATH))
    assert done.returncode == 0, done.stdout + done.stderr

    _execute([
        "INSERT INTO users (id, google_sub, email, display_name) VALUES "
        "(1, 'sub-anton', 'anton@example.com', 'Anton')",
        # alpha merges cleanly into Beta; gamma cannot, because both hold
        # `plum` as a noun; delta is the case-only rename.
        "INSERT INTO topics (name, created_by_user_id, is_public, namespace, "
        "                    section_id) "
        "SELECT n, 1, 1, 0, id FROM topic_sections, "
        "  (SELECT 'alpha' AS n UNION SELECT 'Beta' UNION SELECT 'gamma' "
        "   UNION SELECT 'delta') AS names "
        "WHERE topic_sections.name = 'Other'",
    ])
    ids = _topics()
    _execute([
        "INSERT INTO flashcards (word, pos, topic, topic_id, added_by_user_id) "
        "VALUES "
        f"('apple', 'noun', 'alpha', {ids['alpha']}, 1),"
        f"('pear',  'noun', 'alpha', {ids['alpha']}, 1),"
        f"('plum',  'noun', 'Beta',  {ids['Beta']},  1),"
        f"('plum',  'verb', 'gamma', {ids['gamma']}, 1),"
        f"('quince','noun', 'delta', {ids['delta']}, 1)",
    ])
    # gamma's second card is the collision: same word AND part of speech.
    _execute([
        "INSERT INTO flashcards (word, pos, topic, topic_id, added_by_user_id) "
        f"VALUES ('plum', 'noun', 'gamma', {ids['gamma']}, 1)",
    ])

    sys.path.insert(0, str(KUANTORFLOW_PATH))
    monkeypatch.setenv("DB_NAME", SCRATCH_DB)
    monkeypatch.setenv("KF_LOGS_DIR", str(tmp_path))
    import retopic
    try:
        yield retopic
    finally:
        _execute([f"DROP DATABASE IF EXISTS {SCRATCH_DB}"], database=None)


def _quiet(_line):
    """Swallow the script's console output; the assertions read the database."""


# --- the merge --------------------------------------------------------------

@requires_local_db
def test_a_merge_moves_both_columns(deck):
    """The half that is easy to leave out, and invisible if you do (#207).

    Every page renders from `topic_id`, so a merge that moved only the id looks
    perfect in the browser -- and ai_agent's `cards_db` reads `flashcards.topic`,
    so Mykola would go on naming a topic that no longer exists.
    """
    before = _topics()

    deck.run([deck.Merge("alpha", "Beta")], out=_quiet)

    landed = _in_topic(before["Beta"])
    assert landed[("apple", "noun")] == "Beta"
    assert landed[("pear", "noun")] == "Beta"


@requires_local_db
def test_the_emptied_source_row_is_deleted(deck):
    """Only possible after the cards have left: `fk_flashcards_topic` is
    ON DELETE RESTRICT (#165), so the order is the whole of the safety."""
    deck.run([deck.Merge("alpha", "Beta")], out=_quiet)

    assert "alpha" not in _topics()
    assert "Beta" in _topics()


@requires_local_db
def test_a_rename_rewrites_the_string_on_every_card(deck):
    beta = _topics()["Beta"]

    deck.run([deck.Rename("Beta", "Beta and friends")], out=_quiet)

    assert set(_in_topic(beta).values()) == {"Beta and friends"}
    assert "Beta and friends" in _topics()
    # gamma holds `plum` as a noun too, and its string must not have moved.
    assert set(_in_topic(_topics()["gamma"]).values()) == {"gamma"}


# --- what it refuses --------------------------------------------------------

@requires_local_db
def test_a_collision_is_refused_and_nothing_moves(deck):
    """#101 keeps one card per word and part of speech, and a bulk UPDATE does
    not go through `save_flashcard()` to get it. `gamma` and `Beta` both hold
    `plum` as a noun; `plum` the verb is a different card and not a collision.
    """
    before = _topics()

    deck.run([deck.Merge("gamma", "Beta")], out=_quiet)

    assert "gamma" in _topics(), "the source survives a refused merge"
    assert all(tid == before["gamma"]
               for word, pos, tid in _rows(
                   "SELECT word, pos, topic_id FROM flashcards "
                   f"WHERE topic_id = {before['gamma']}"))


@requires_local_db
def test_allow_duplicates_moves_them_anyway(deck):
    """The flag exists because "refuse" is the right default and not the right
    answer every time -- and it has to actually do the thing it names."""
    before = _topics()

    deck.run([deck.Merge("gamma", "Beta")], allow_duplicates=True, out=_quiet)

    assert "gamma" not in _topics()
    assert len(_rows("SELECT id FROM flashcards WHERE word = 'plum' "
                     f"AND topic_id = {before['Beta']}")) == 3


@requires_local_db
def test_it_will_not_guess_between_two_topics_of_the_same_name(deck):
    """Since #382 a name is unique only within a namespace, so a public `Beta`
    and somebody's private `Beta` can both exist. A bulk move that picked one
    by luck is exactly what this must not do."""
    _execute([
        "INSERT INTO topics (name, created_by_user_id, is_public, namespace, "
        "                    section_id) "
        "SELECT 'Beta', 1, 0, 1, id FROM topic_sections WHERE name = 'Other'",
    ])

    with pytest.raises(SystemExit):
        deck.run([deck.Merge("alpha", "Beta")], out=_quiet)


# --- running it twice -------------------------------------------------------

@requires_local_db
def test_a_case_only_rename_runs_once(deck):
    """The bug this file was written after.

    `find_topic()` matches case-insensitively because the unique key collates
    that way -- so after `delta` becomes `Delta`, the old name still finds the
    same row, and the self-match guard let the rename through on every later
    run. It reported a change and wrote a log line for work already done.
    """
    first = deck.run([deck.Rename("delta", "Delta")], out=_quiet)
    second = deck.run([deck.Rename("delta", "Delta")], out=_quiet)

    assert first == 1
    assert second == 0, "a finished rename must report nothing to do"


@requires_local_db
def test_a_finished_plan_is_quiet(deck):
    plan = [deck.Merge("alpha", "Beta"), deck.Rename("delta", "Delta")]

    assert deck.run(plan, out=_quiet) == 2
    assert deck.run(plan, out=_quiet) == 0


# --- the rehearsal ----------------------------------------------------------

@requires_local_db
def test_a_dry_run_leaves_the_database_exactly_as_it_found_it(deck):
    """The rehearsal applies every step and rolls back, which is the only way
    it can report truthfully on a plan whose steps depend on each other. A
    rollback that did not hold would be a dry run that silently wrote."""
    topics_before, cards_before = _topics(), _cards()

    deck.run([deck.Merge("alpha", "Beta"), deck.Rename("delta", "Delta")],
             dry_run=True, out=_quiet)

    assert _topics() == topics_before
    assert _cards() == cards_before


@requires_local_db
def test_the_rehearsal_sees_what_earlier_steps_did(deck):
    """Why it is a rehearsal rather than a prediction.

    A dry run that checked each step against the untouched database would call
    the second one impossible: `Beta and friends` does not exist until the first
    step creates it. This is the local plan's shape in miniature -- a rename
    that makes the topic the next step merges into.
    """
    counted = deck.run([deck.Rename("Beta", "Beta and friends"),
                        deck.Merge("alpha", "Beta and friends")],
                       dry_run=True, out=_quiet)

    assert counted == 2, "both steps were applicable during the rehearsal"
    assert "Beta" in _topics(), "and none of it was kept"
