"""
Topic sections against a real LOCAL MySQL (marker: db) — kuantorflow#215.

test_apply_schema_db.py proves the *migration*: that the table appears, that
every existing topic is filed under 'Other' and that the foreign key holds.
This file proves what the **app** does once that has happened — which is one
promise and its consequences:

    every topic has a section, so nothing needs a "no section" branch.

The migration only settles that for topics that already existed. Keeping it
true is `_get_or_create_topic()`'s job, on every path that invents a topic: a
lookup, a notes import, a card move, Mykola. If any of them left `section_id`
NULL the invariant would be broken by the next word anyone looked up.

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

SCRATCH_DB = "kuantorflow_sections_test"

# As #215 spells it, en dash and all. See test_apply_schema_db.py.
CURRICULUM_SECTION = "B2–C1 Conversational Topics"

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


def _apply():
    return subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True,
        env=dict(os.environ, DB_NAME=SCRATCH_DB), cwd=str(KUANTORFLOW_PATH))


def _section_of(topic):
    """The section a topic sits in, by name. None when it has none."""
    rows = _query("SELECT s.name FROM topics t "
                  "LEFT JOIN topic_sections s ON t.section_id = s.id "
                  "WHERE t.name = %s", (topic,))
    return rows[0][0] if rows else None


@pytest.fixture()
def sections_db(monkeypatch):
    """A migrated scratch database, with utils pointed at it.

    utils.get_db_connection() reads DB_NAME at call time, so redirecting the
    environment variable is enough — every function under test then runs on its
    own real connection rather than a fake.
    """
    _execute([f"DROP DATABASE IF EXISTS {SCRATCH_DB}",
              f"CREATE DATABASE {SCRATCH_DB} CHARACTER SET utf8mb4 "
              f"COLLATE utf8mb4_unicode_ci"], database=None)
    result = _apply()
    assert result.returncode == 0, result.stderr
    monkeypatch.setenv("DB_NAME", SCRATCH_DB)
    _execute(["INSERT INTO users (id, google_sub, email) "
              "VALUES (7, 'sub-7', 'seven@example.com')"])
    try:
        yield SCRATCH_DB
    finally:
        _execute([f"DROP DATABASE IF EXISTS {SCRATCH_DB}"], database=None)


# --- the invariant: a topic always has a section ------------------------


@requires_local_db
def test_a_topic_invented_by_a_lookup_lands_in_other(sections_db):
    import utils

    utils.save_flashcard({"word": "sustainable", "topic": "Environment"},
                         added_by_user_id=7)

    assert _section_of("Environment") == "Other"
    assert _query("SELECT COUNT(*) FROM topics WHERE section_id IS NULL") == [(0,)]


@requires_local_db
def test_a_topic_invented_by_a_card_move_lands_in_other(sections_db):
    """#177 promises an unknown destination is created. It must be created
    *into a section*, like every other new topic."""
    import utils

    card = utils.save_flashcard({"word": "sustainable", "topic": "Environment"},
                                added_by_user_id=7)
    assert utils.move_flashcard(card, "Climate", owner_id=7)[0] == "moved"

    assert _section_of("Climate") == "Other"
    assert _query("SELECT COUNT(*) FROM topics WHERE section_id IS NULL") == [(0,)]


@requires_local_db
def test_a_new_topic_starts_at_position_zero(sections_db):
    """Which is what puts it in alphabetical place among the rest of 'Other',
    rather than at the front or the end."""
    import utils

    utils.save_flashcard({"word": "sustainable", "topic": "Environment"},
                         added_by_user_id=7)

    assert _query("SELECT position FROM topics WHERE name = 'Environment'") \
        == [(0,)]


@requires_local_db
def test_saving_into_an_existing_topic_does_not_move_it(sections_db):
    """A topic's section is set when it is created and never rewritten by a
    later save — otherwise #203's curriculum topics would be dragged back into
    'Other' by the first learner to add a card to one.
    """
    import utils

    utils.save_flashcard({"word": "sustainable", "topic": "Environment"},
                         added_by_user_id=7)
    _execute(["UPDATE topics SET section_id = "
              f"(SELECT id FROM topic_sections WHERE name = '{CURRICULUM_SECTION}'), "
              "position = 4 WHERE name = 'Environment'"])

    utils.save_flashcard({"word": "offset", "topic": "environment"},
                         added_by_user_id=7)

    assert _section_of("Environment") == CURRICULUM_SECTION
    assert _query("SELECT position FROM topics WHERE name = 'Environment'") \
        == [(4,)], "and its place in that section is untouched"


# --- ordering -----------------------------------------------------------


@requires_local_db
def test_topics_order_by_section_then_position_then_name(sections_db):
    """The full ordering rule. `Other` sinks below the curriculum section
    because its position is 100, and its members sort by name because they all
    share position 0.
    """
    import utils

    for word, topic in (("a", "zebra"), ("b", "apple"), ("c", "first"),
                        ("d", "second")):
        utils.save_flashcard({"word": word, "topic": topic}, added_by_user_id=7)
    # Two of them promoted into the curriculum, deliberately out of alphabetical
    # order, so position is doing the work rather than the name.
    _execute([
        "UPDATE topics SET section_id = "
        f"(SELECT id FROM topic_sections WHERE name = '{CURRICULUM_SECTION}'), "
        "position = 1 WHERE name = 'second'",
        "UPDATE topics SET section_id = "
        f"(SELECT id FROM topic_sections WHERE name = '{CURRICULUM_SECTION}'), "
        "position = 2 WHERE name = 'first'",
    ])

    assert [r[0] for r in _query(
        "SELECT t.name FROM topics t JOIN topic_sections s "
        "ON t.section_id = s.id "
        "ORDER BY s.position, t.position, t.name")] == \
        ["second", "first", "apple", "zebra"]


@requires_local_db
def test_get_topics_is_unchanged_by_sections(sections_db):
    """#215 adds no UI, and this is the assertion that says so: the browse list
    is still `(name, count)` for topics that have cards, in name order."""
    import utils

    utils.save_flashcard({"word": "a", "topic": "vocab"}, added_by_user_id=7)
    utils.save_flashcard({"word": "b", "topic": "vocab"}, added_by_user_id=7)
    utils.save_flashcard({"word": "c", "topic": "emotions"}, added_by_user_id=7)

    assert utils.get_topics() == [("emotions", 1), ("vocab", 2)]


# --- get_topics_by_section(), the browse page's read (#218) -------------


@requires_local_db
def test_the_grouped_read_returns_every_section_with_its_topics(sections_db):
    import utils

    utils.save_flashcard({"word": "a", "topic": "vocab"}, added_by_user_id=7)
    utils.save_flashcard({"word": "b", "topic": "vocab"}, added_by_user_id=7)
    utils.save_flashcard({"word": "c", "topic": "emotions"}, added_by_user_id=7)

    assert utils.get_topics_by_section() == [
        (CURRICULUM_SECTION, []),
        ("Other", [("emotions", 1), ("vocab", 2)]),
    ]


@requires_local_db
def test_an_empty_section_comes_back_with_an_empty_list(sections_db):
    """Not omitted, and not None — the page renders a heading from it."""
    import utils

    assert utils.get_topics_by_section() == [
        (CURRICULUM_SECTION, []), ("Other", [])]


@requires_local_db
def test_a_topic_with_no_cards_is_left_out_but_its_section_is_not(sections_db):
    """The asymmetry #218 rests on: an empty *section* is structure, an empty
    *topic* is a leftover (#207 keeps the row for its name and creator)."""
    import utils

    card = utils.save_flashcard({"word": "only", "topic": "doomed"},
                                added_by_user_id=7)
    utils.delete_flashcard(card, owner_id=7)

    assert _query("SELECT COUNT(*) FROM topics WHERE name = 'doomed'") == [(1,)]
    assert utils.get_topics_by_section() == [
        (CURRICULUM_SECTION, []), ("Other", [])]


@requires_local_db
def test_a_section_survives_the_owner_filter_hiding_all_its_topics(sections_db):
    """The bug an owner filter in the WHERE clause would cause: it would drop
    the rows the outer join exists to keep, and every section with no cards
    *of yours* would disappear rather than appear empty."""
    import utils

    _execute(["INSERT INTO users (id, google_sub, email) "
              "VALUES (8, 'sub-8', 'eight@example.com')"])
    utils.save_flashcard({"word": "theirs", "topic": "shared"},
                         added_by_user_id=8)

    assert utils.get_topics_by_section(owner_id=8) == [
        (CURRICULUM_SECTION, []), ("Other", [("shared", 1)])]
    assert utils.get_topics_by_section(owner_id=7) == [
        (CURRICULUM_SECTION, []), ("Other", [])], \
        "user 7 owns nothing, but both sections are still there"


@requires_local_db
def test_the_grouped_read_counts_only_your_cards(sections_db):
    """#127, one level in: the count on a tile is of the cards you can see."""
    import utils

    _execute(["INSERT INTO users (id, google_sub, email) "
              "VALUES (8, 'sub-8', 'eight@example.com')"])
    utils.save_flashcard({"word": "mine", "topic": "shared"},
                         added_by_user_id=7)
    utils.save_flashcard({"word": "theirs", "topic": "shared"},
                         added_by_user_id=8)

    assert utils.get_topics_by_section()[1][1] == [("shared", 2)]
    assert utils.get_topics_by_section(owner_id=7)[1][1] == [("shared", 1)]


@requires_local_db
def test_the_grouped_read_orders_by_section_then_position_then_name(sections_db):
    import utils

    for word, topic in (("a", "zebra"), ("b", "apple"), ("c", "second")):
        utils.save_flashcard({"word": word, "topic": topic}, added_by_user_id=7)
    _execute([
        "UPDATE topics SET section_id = "
        f"(SELECT id FROM topic_sections WHERE name = '{CURRICULUM_SECTION}'), "
        "position = 1 WHERE name = 'second'",
    ])

    assert utils.get_topics_by_section() == [
        (CURRICULUM_SECTION, [("second", 1)]),
        ("Other", [("apple", 1), ("zebra", 1)]),
    ]


@requires_local_db
def test_a_topic_with_no_section_is_absent_rather_than_ungrouped(sections_db):
    """#215 documents section_id as never NULL, so there is no "no section"
    bucket. Worth pinning the consequence: such a topic is missing from this
    page while still listed flat and still reachable by URL.
    """
    import utils

    utils.save_flashcard({"word": "a", "topic": "orphan"}, added_by_user_id=7)
    _execute(["UPDATE topics SET section_id = NULL WHERE name = 'orphan'"])

    assert utils.get_topics_by_section() == [
        (CURRICULUM_SECTION, []), ("Other", [])]
    assert utils.get_topics() == [("orphan", 1)], "still in the flat list"
    assert [c["word"] for c in utils.get_flashcards_by_topic("orphan")] == ["a"]


# --- a database the migration has not finished with ---------------------


@requires_local_db
def test_a_topic_created_before_the_sections_exist_is_adopted_later(sections_db):
    """The one case where section_id is legitimately NULL.

    A worker saving a card between the column arriving and the section rows
    being inserted must not crash — the card matters more than the grouping —
    and the next `apply_schema.py` picks the topic up.
    """
    import utils

    _execute(["DELETE FROM topic_sections"])   # no topics yet, so nothing blocks it

    assert utils.save_flashcard({"word": "sustainable", "topic": "Environment"},
                                added_by_user_id=7), "the card is still saved"
    assert _section_of("Environment") is None

    assert _apply().returncode == 0
    assert _section_of("Environment") == "Other"


@requires_local_db
def test_a_card_with_no_topic_creates_no_section_membership(sections_db):
    """"No topic" is still a real state (#207), and it must not become a topic
    named '' filed under 'Other'."""
    import utils

    card = utils.save_flashcard({"word": "stray", "topic": "   "},
                                added_by_user_id=7)

    assert _query("SELECT topic_id FROM flashcards WHERE id = %s", (card,)) \
        == [(None,)]
    assert _query("SELECT COUNT(*) FROM topics") == [(0,)]
