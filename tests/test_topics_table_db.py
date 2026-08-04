"""
The topics table against a real LOCAL MySQL (marker: db) — kuantorflow#207.

The offline tests prove the SQL each function builds; these prove what the
database then does with it, which is where the interesting decisions live:

* an empty topic row exists but is not listed,
* a name resolves case-insensitively to one row,
* the creator of a topic is whoever made it and does not change afterwards,
* and none of it filters a view by anything but *card* ownership.

Safety: this creates and drops its **own** scratch database and never touches
the configured one, on the same opt-in switch as the other db-marked tests.

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

SCRATCH_DB = "kuantorflow_topics_test"

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


def _execute(statements, database=SCRATCH_DB):
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
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


@pytest.fixture()
def topics_db(monkeypatch):
    """A migrated scratch database, with utils pointed at it.

    utils.get_db_connection() reads DB_NAME at call time, so redirecting the
    environment variable is enough — and it keeps every function under test on
    its own real connection rather than a fake.
    """
    _execute([f"DROP DATABASE IF EXISTS {SCRATCH_DB}",
              f"CREATE DATABASE {SCRATCH_DB} CHARACTER SET utf8mb4 "
              f"COLLATE utf8mb4_unicode_ci"], database=None)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True,
        env=dict(os.environ, DB_NAME=SCRATCH_DB), cwd=str(KUANTORFLOW_PATH))
    assert result.returncode == 0, result.stderr
    monkeypatch.setenv("DB_NAME", SCRATCH_DB)
    _execute(["INSERT INTO users (id, google_sub, email) "
              "VALUES (7, 'sub-7', 'seven@example.com')",
              "INSERT INTO users (id, google_sub, email) "
              "VALUES (8, 'sub-8', 'eight@example.com')"])
    try:
        yield SCRATCH_DB
    finally:
        _execute([f"DROP DATABASE IF EXISTS {SCRATCH_DB}"], database=None)


# --- creating a topic by saving into it ---------------------------------


@requires_local_db
def test_saving_into_a_new_topic_creates_it_and_records_its_creator(topics_db):
    import utils

    assert utils.save_flashcard(
        {"word": "sustainable", "pos": "adjective", "topic": "Environment"},
        added_by_user_id=7)
    assert _query("SELECT name, created_by_user_id FROM topics") == \
        [("Environment", 7)]


@requires_local_db
def test_a_second_save_reuses_the_row_and_leaves_its_creator_alone(topics_db):
    """A topic is created once, by one person. Later arrivals are not its
    author, however the name reaches them."""
    import utils

    utils.save_flashcard({"word": "sustainable", "topic": "Environment"},
                         added_by_user_id=7)
    utils.save_flashcard({"word": "offset", "topic": "environment"},
                         added_by_user_id=8)

    assert _query("SELECT COUNT(*) FROM topics") == [(1,)]
    assert _query("SELECT created_by_user_id FROM topics") == [(7,)]


@requires_local_db
def test_the_card_stores_the_rows_spelling_not_the_one_submitted(topics_db):
    """`flashcards.topic` is still read by ai_agent, so it must not drift from
    the row `topic_id` points at."""
    import utils

    utils.save_flashcard({"word": "sustainable", "topic": "Environment"},
                         added_by_user_id=7)
    utils.save_flashcard({"word": "offset", "topic": "eNvIrOnMeNt"},
                         added_by_user_id=7)

    assert sorted(_query("SELECT topic FROM flashcards")) == \
        [("Environment",), ("Environment",)]
    assert _query("SELECT COUNT(*) FROM flashcards f JOIN topics t "
                  "ON f.topic_id = t.id "
                  "WHERE f.topic <> t.name COLLATE utf8mb4_bin") == [(0,)]


@requires_local_db
def test_a_card_with_no_topic_is_stored_with_no_topic(topics_db):
    import utils

    card = utils.save_flashcard({"word": "stray", "topic": "   "},
                                added_by_user_id=7)
    assert _query("SELECT topic_id FROM flashcards WHERE id = %s", (card,)) == \
        [(None,)]
    assert _query("SELECT COUNT(*) FROM topics") == [(0,)]


# --- reading -----------------------------------------------------------


@requires_local_db
def test_get_topics_counts_cards_not_topics(topics_db):
    import utils

    utils.save_flashcard({"word": "a", "topic": "vocab"}, added_by_user_id=7)
    utils.save_flashcard({"word": "b", "topic": "vocab"}, added_by_user_id=7)
    utils.save_flashcard({"word": "c", "topic": "emotions"}, added_by_user_id=8)

    assert utils.get_topics() == [("emotions", 1), ("vocab", 2)]


@requires_local_db
def test_an_empty_topic_exists_but_is_not_listed(topics_db):
    """Deleting the last card in a topic leaves the row behind (#207).

    The row is kept because it is where the name, creator and age live — but
    `get_topics()` lists topics that *have cards*, exactly as the GROUP BY it
    replaced did, which is why this change is invisible on the page.
    """
    import utils

    card = utils.save_flashcard({"word": "only", "topic": "doomed"},
                                added_by_user_id=7)
    utils.delete_flashcard(card, owner_id=7)

    assert _query("SELECT name FROM topics") == [("doomed",)], "the row survives"
    assert utils.get_topics() == [], "and is not offered as a topic to browse"
    assert utils.get_flashcards_by_topic("doomed") == []


@requires_local_db
def test_refiling_a_card_resurrects_the_same_topic(topics_db):
    """Which is the point of keeping the row: the topic's history is not lost
    because it went briefly empty."""
    import utils

    card = utils.save_flashcard({"word": "only", "topic": "doomed"},
                                added_by_user_id=7)
    topic_id = _query("SELECT id FROM topics")[0][0]
    utils.delete_flashcard(card, owner_id=7)
    utils.save_flashcard({"word": "again", "topic": "doomed"},
                         added_by_user_id=8)

    assert _query("SELECT id, created_by_user_id FROM topics") == \
        [(topic_id, 7)], "same row, same creator"


@requires_local_db
def test_a_topic_name_is_matched_case_insensitively_on_the_way_in_and_out(
        topics_db):
    import utils

    utils.save_flashcard({"word": "a", "topic": "Media and the news"},
                         added_by_user_id=7)
    assert [c["word"] for c in
            utils.get_flashcards_by_topic("media AND THE news")] == ["a"]


# --- what attribution must not do --------------------------------------


@requires_local_db
def test_the_owner_filter_is_about_cards_not_about_who_made_the_topic(topics_db):
    """#127 filters on card ownership. A topic someone else started, holding
    your cards, is still yours to see; one holding only theirs is not."""
    import utils

    utils.save_flashcard({"word": "theirs", "topic": "shared"},
                         added_by_user_id=8)
    utils.save_flashcard({"word": "mine", "topic": "shared"},
                         added_by_user_id=7)
    utils.save_flashcard({"word": "alsotheirs", "topic": "theirs only"},
                         added_by_user_id=8)

    assert _query("SELECT created_by_user_id FROM topics WHERE name = 'shared'") \
        == [(8,)], "user 8 created it"
    assert utils.get_topics(owner_id=7) == [("shared", 1)], \
        "user 7 sees it because a card of theirs is in it"
    assert [c["word"] for c in
            utils.get_flashcards_by_topic("shared", owner_id=7)] == ["mine"]


@requires_local_db
def test_deleting_a_creators_account_keeps_the_topic_and_its_cards(topics_db):
    """The #165 flow, with a topic in it: resolve the cards, then the row."""
    import utils

    utils.save_flashcard({"word": "theirs", "topic": "shared"},
                         added_by_user_id=7)
    utils.save_flashcard({"word": "someone elses", "topic": "shared"},
                         added_by_user_id=8)

    utils.resolve_user_cards(7, keep_cards=True)
    assert utils.delete_user(7) is True, \
        "a RESTRICT key here would have made this fail"

    assert _query("SELECT name, created_by_user_id FROM topics") == \
        [("shared", None)]
    assert utils.get_topics() == [("shared", 2)], "both cards are still filed"
