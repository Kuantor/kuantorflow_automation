"""Claiming unowned cards against a real LOCAL MySQL (marker: db) —
kuantorflow#396.

The offline file proves the shape of the statement. **This proves what the
statement matched**, which is the only thing an author column is: a fake cursor
agrees with any WHERE it is handed, and here the WHERE decides whether another
learner keeps their cards.

Four facts only a database can settle:

* another author's cards survive a run — and unlike a topic, an author is a
  permission (#162) and a visibility (#127) as well as a label, so taking one
  would hand somebody's work over three ways at once;
* the join to `topics` is a real section filter, not a label on the output;
* a second run finds nothing, because the first left no NULLs;
* **a topic whose cards are all claimed can finally be hidden** — which is the
  reason this ticket exists at all. `set_topic_visibility()` answers `shared`
  while any card in the topic belongs to somebody else, and an unowned card
  counts as somebody else's.

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

SCRATCH_DB = "kuantorflow_claim_cards_test"

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

ANTON, OLENA = 1, 2


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


def _authors():
    """`{word: added_by_user_id}` as the database now holds it."""
    conn = _connect(SCRATCH_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT word, added_by_user_id FROM flashcards ORDER BY word")
    rows = dict(cursor.fetchall())
    cursor.close()
    conn.close()
    return rows


def _topic_id(name):
    conn = _connect(SCRATCH_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM topics WHERE name = %s", (name,))
    found = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return found


@pytest.fixture()
def deck(monkeypatch):
    """A scratch database whose cards cover the three states a section holds.

    Built by running the app's own `apply_schema.py`, so the columns under test
    are the ones the deploy makes rather than a hand-written copy of them.
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
        "(1, 'sub-anton', 'anton@example.com', 'Anton'),"
        "(2, 'sub-olena', 'olena@example.com', 'Olena')",
        "INSERT INTO topics (id, name, created_by_user_id, is_public, namespace,"
        "                    section_id) "
        "SELECT 10, 'general', 1, 1, 0, id FROM topic_sections WHERE name='Other'",
        "INSERT INTO topics (id, name, created_by_user_id, is_public, namespace,"
        "                    section_id) "
        "SELECT 11, 'Travel', 2, 1, 0, id FROM topic_sections WHERE name='Other'",
        # Outside the section, and unowned: the join has to miss it.
        "INSERT INTO topics (id, name, created_by_user_id, is_public, namespace,"
        "                    section_id) "
        "SELECT 12, 'Work and careers', 1, 1, 0, id FROM topic_sections "
        "WHERE name <> 'Other' LIMIT 1",
        # Nobody's, Anton's, Olena's, and one in the other section.
        "INSERT INTO flashcards (word, topic, topic_id, added_by_user_id) VALUES "
        "('orphan', 'general', 10, NULL),"
        "('mine', 'general', 10, 1),"
        "('hers', 'Travel', 11, 2),"
        "('elsewhere', 'Work and careers', 12, NULL)",
    ])

    sys.path.insert(0, str(KUANTORFLOW_PATH))
    import utils
    monkeypatch.setenv("DB_NAME", SCRATCH_DB)
    try:
        yield utils
    finally:
        _execute([f"DROP DATABASE IF EXISTS {SCRATCH_DB}"], database=None)


# --- what the UPDATE actually matched ---------------------------------------

@requires_local_db
def test_it_claims_the_authorless_card_and_only_that(deck):
    claimed, others, missing = deck.claim_unowned_cards("Other", ANTON)

    assert (claimed, missing) == ([("general", 1)], False)
    assert others == [(OLENA, "olena@example.com", 1)]
    assert _authors() == {"orphan": ANTON, "mine": ANTON, "hers": OLENA,
                          "elsewhere": None}


@requires_local_db
def test_another_authors_card_survives_it(deck):
    """An author is a permission and a visibility, not only a label: taking
    Olena's card would put it in Anton's deck, let him delete it, and hide it
    from her behind #127."""
    deck.claim_unowned_cards("Other", ANTON)

    assert _authors()["hers"] == OLENA


@requires_local_db
def test_a_card_in_another_section_is_not_touched(deck):
    """`--section` is a join, not a label on the output."""
    deck.claim_unowned_cards("Other", ANTON)

    assert _authors()["elsewhere"] is None


@requires_local_db
def test_a_second_run_finds_nothing(deck):
    deck.claim_unowned_cards("Other", ANTON)

    claimed, others, _ = deck.claim_unowned_cards("Other", ANTON)

    assert claimed == []
    assert others == [(OLENA, "olena@example.com", 1)], (
        "the report is still worth printing on a run that writes nothing")


@requires_local_db
def test_a_dry_run_leaves_the_rows_alone(deck):
    before = _authors()

    claimed, _, _ = deck.claim_unowned_cards("Other", ANTON, dry_run=True)

    assert claimed == [("general", 1)], "it still reports what it would do"
    assert _authors() == before


# --- and the reason for doing it at all -------------------------------------

@requires_local_db
def test_a_topic_can_be_hidden_once_its_cards_have_an_author(deck):
    """The whole point, and what #394 could not finish on its own.
    `set_topic_visibility()` answers `shared` while any card in the topic
    belongs to somebody else, and an unowned card counts -- so a topic with a
    creator and orphaned cards is still stuck public.
    """
    general = _topic_id("general")

    assert deck.set_topic_visibility(general, False, viewer_id=ANTON) == "shared"

    deck.claim_unowned_cards("Other", ANTON)

    assert deck.set_topic_visibility(general, False, viewer_id=ANTON) == "changed"
