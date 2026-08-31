"""Claiming unowned topics against a real LOCAL MySQL (marker: db) —
kuantorflow#394.

The offline file proves the shape of the statement. **This proves the clause
that makes it safe.** `claim_unowned_topics()` is one conditional UPDATE whose
whole safety is `created_by_user_id IS NULL` in the WHERE — a fake cursor
agrees with any WHERE clause it is handed, so what it *matched* is exactly the
thing an offline test cannot check.

Three facts only a database can settle:

* another learner's topic survives a run, which is the rule the ticket turns on
  — for a private topic the creator id is the only thing deciding who can see
  it;
* a second run finds nothing, because the first left no NULLs behind rather
  than because the code remembered;
* a claimed topic can then be made private, which is the point of the whole
  thing: `set_topic_visibility()` answers `nobodys` for a creatorless topic,
  and that is the state these rows are stuck in until this runs.

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

SCRATCH_DB = "kuantorflow_claim_topics_test"

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


def _creators():
    """`{topic name: created_by_user_id}` as the database now holds it."""
    conn = _connect(SCRATCH_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT name, created_by_user_id FROM topics ORDER BY name")
    rows = dict(cursor.fetchall())
    cursor.close()
    conn.close()
    return rows


@pytest.fixture()
def deck(monkeypatch):
    """A scratch database holding the three states a section can be in.

    Built by running the app's own `apply_schema.py`, so the columns under test
    are the ones the deploy makes rather than a hand-written copy that could
    drift from them.
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
        # Unowned, Anton's already, and Olena's -- one row for each thing the
        # run has to do: claim it, leave it because there is nothing to do, and
        # leave it because it is not his.
        "INSERT INTO topics (name, created_by_user_id, is_public, namespace, "
        "                    section_id) "
        "SELECT 'general', NULL, 1, 0, id FROM topic_sections WHERE name='Other'",
        "INSERT INTO topics (name, created_by_user_id, is_public, namespace, "
        "                    section_id) "
        "SELECT 'math', 1, 1, 0, id FROM topic_sections WHERE name='Other'",
        "INSERT INTO topics (name, created_by_user_id, is_public, namespace, "
        "                    section_id) "
        "SELECT 'Travel', 2, 1, 0, id FROM topic_sections WHERE name='Other'",
        # And one outside the section, which a WHERE on section_id has to miss.
        "INSERT INTO topics (name, created_by_user_id, is_public, namespace, "
        "                    section_id) "
        "SELECT 'Work and careers', NULL, 1, 0, id FROM topic_sections "
        "WHERE name <> 'Other' LIMIT 1",
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
def test_it_claims_the_unowned_row_and_only_that(deck):
    claimed, left, missing = deck.claim_unowned_topics("Other", ANTON)

    assert (claimed, missing) == (["general"], False)
    assert left == [("Travel", OLENA)]
    assert _creators() == {"general": ANTON, "math": ANTON, "Travel": OLENA,
                           "Work and careers": None}


@requires_local_db
def test_another_learners_topic_survives_it(deck):
    """The rule the ticket turns on, asked of the database rather than of a
    list comprehension. Rewriting Olena's creator would move her topic into
    Anton's namespace and out of her own deck."""
    deck.claim_unowned_topics("Other", ANTON)

    assert _creators()["Travel"] == OLENA


@requires_local_db
def test_a_topic_in_another_section_is_not_touched(deck):
    """`--section` is a real filter, not a label on the output."""
    deck.claim_unowned_topics("Other", ANTON)

    assert _creators()["Work and careers"] is None


@requires_local_db
def test_a_second_run_finds_nothing(deck):
    """Idempotent because the first run left no NULLs, not because anything
    remembered it ran."""
    deck.claim_unowned_topics("Other", ANTON)

    claimed, left, _ = deck.claim_unowned_topics("Other", ANTON)

    assert claimed == []
    assert left == [("Travel", OLENA)]


@requires_local_db
def test_a_dry_run_leaves_the_rows_alone(deck):
    before = _creators()

    claimed, _, _ = deck.claim_unowned_topics("Other", ANTON, dry_run=True)

    assert claimed == ["general"], "it still reports what it would do"
    assert _creators() == before


# --- and the reason for doing it at all -------------------------------------

@requires_local_db
def test_a_claimed_topic_can_then_be_hidden(deck):
    """The whole point. `set_topic_visibility()` answers `nobodys` for a
    creatorless topic -- #382's rule, since a private topic nobody owns is one
    nobody can see and nobody can un-hide -- so those rows are stuck public
    until this runs.

    It is refused **twice over**, which is worth pinning: an ordinary learner
    is told `denied`, because the ownership check comes first and a topic with
    no creator is nobody's, while the admin gets as far as `nobodys`. Neither
    can hide it, by different routes, and the claim dissolves both.

    The card belongs to the claimant, because a topic holding somebody else's
    cards is refused for a different reason (`shared`), and this test is about
    the creator rather than the cards.
    """
    _execute(["INSERT INTO flashcards (word, topic, topic_id, added_by_user_id) "
              "SELECT 'resilient', 'general', id, 1 FROM topics "
              "WHERE name = 'general'"])
    conn = _connect(SCRATCH_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM topics WHERE name = 'general'")
    topic_id = cursor.fetchone()[0]
    cursor.close()
    conn.close()

    assert deck.set_topic_visibility(topic_id, False, viewer_id=ANTON) \
        == "denied"
    assert deck.set_topic_visibility(topic_id, False, admin=True) == "nobodys"

    deck.claim_unowned_topics("Other", ANTON)

    assert deck.set_topic_visibility(topic_id, False, viewer_id=ANTON) \
        == "changed"
