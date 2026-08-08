"""
Seeding against a real LOCAL MySQL (marker: db) — kuantorflow#203.

`test_seed_topics.py` proves the script's logic against stubs. This proves the
part only a database can: that `place_topic()` really does put the curriculum in
the section #215 built for it, that it *moves* rather than duplicates a topic
somebody had already started, and that a whole run leaves eighteen numbered
topics full of linked cards.

`lookup_word()` is still stubbed. The network is not the thing under test, 360
live lookups are not something a suite should do, and a run that depended on
Google being reachable would fail for reasons that are nobody's bug.

Safety: this creates and drops its **own** scratch database and never touches the
configured one, on the same opt-in switch as the other db-marked tests.

    # PowerShell
    $env:RUN_DB_ROUNDTRIP="1"; pytest -m db
"""

import io
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

SCRATCH_DB = "kuantorflow_seed_test"
CURRICULUM_SECTION = "B2–C1 Conversational Topics"

pytestmark = pytest.mark.db


def _prerequisites_met():
    return (
        os.environ.get("RUN_DB_ROUNDTRIP") == "1"
        and os.environ.get("DB_HOST") in ("localhost", "127.0.0.1")
        and os.environ.get("DB_PASSWORD")
        and SCRIPT.exists()
        and (KUANTORFLOW_PATH / "seed_topics.py").exists()
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


def _placement(topic):
    """`(section, position)` for a topic, or None when it does not exist."""
    rows = _query("SELECT s.name, t.position FROM topics t "
                  "LEFT JOIN topic_sections s ON t.section_id = s.id "
                  "WHERE t.name = %s", (topic,))
    return rows[0] if rows else None


@pytest.fixture()
def seed_db(monkeypatch):
    """A migrated scratch database with utils and the script pointed at it."""
    _execute([f"DROP DATABASE IF EXISTS {SCRATCH_DB}",
              f"CREATE DATABASE {SCRATCH_DB} CHARACTER SET utf8mb4 "
              f"COLLATE utf8mb4_unicode_ci"], database=None)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True,
        env=dict(os.environ, DB_NAME=SCRATCH_DB), cwd=str(KUANTORFLOW_PATH))
    assert result.returncode == 0, result.stderr
    monkeypatch.setenv("DB_NAME", SCRATCH_DB)
    try:
        yield SCRATCH_DB
    finally:
        _execute([f"DROP DATABASE IF EXISTS {SCRATCH_DB}"], database=None)


@pytest.fixture()
def stub_lookup(monkeypatch):
    """One noun card per word, no network. Returns the words it was asked for."""
    import seed_topics

    asked = []

    def fake(word, topic=None, translator=None, explanatory_dictionary=None):
        asked.append(word)
        return [{"word": word, "pos": "noun", "topic": topic,
                 "explanation_en": f"a definition of {word}",
                 "translation_ukr": "переклад", "translation_rus": "перевод"}]

    monkeypatch.setattr(seed_topics, "lookup_word", fake)
    return asked


# --- place_topic() ------------------------------------------------------


@requires_local_db
def test_place_topic_puts_a_new_topic_in_the_section_at_the_position(seed_db):
    import utils

    assert utils.place_topic("Work and careers", CURRICULUM_SECTION, 1)[0] == \
        "created"
    assert _placement("Work and careers") == (CURRICULUM_SECTION, 1)


@requires_local_db
def test_place_topic_moves_a_topic_that_already_exists_elsewhere(seed_db):
    """The UNIQUE key means "the same name" is "the same topic", so a topic
    somebody had already started in 'Other' *is* the curriculum topic — and its
    cards come with it rather than being stranded beside a duplicate."""
    import utils

    card = utils.save_flashcard({"word": "resign", "topic": "Work and careers"})
    assert _placement("Work and careers") == ("Other", 0)

    assert utils.place_topic("Work and careers", CURRICULUM_SECTION, 1)[0] == \
        "moved"

    assert _placement("Work and careers") == (CURRICULUM_SECTION, 1)
    assert _query("SELECT COUNT(*) FROM topics") == [(1,)], "not duplicated"
    assert _query("SELECT topic_id IS NOT NULL FROM flashcards WHERE id = %s",
                  (card,)) == [(1,)], "the card came with it"


@requires_local_db
def test_place_topic_is_unchanged_the_second_time(seed_db):
    import utils

    utils.place_topic("Work and careers", CURRICULUM_SECTION, 1)
    assert utils.place_topic("Work and careers", CURRICULUM_SECTION, 1)[0] == \
        "unchanged"


@requires_local_db
def test_place_topic_matches_a_name_case_insensitively(seed_db):
    """Same rule as `_get_or_create_topic()` and as the column collation."""
    import utils

    _, topic_id = utils.place_topic("Work and careers", CURRICULUM_SECTION, 1)
    outcome, again = utils.place_topic("WORK AND CAREERS",
                                       CURRICULUM_SECTION, 1)
    assert (outcome, again) == ("unchanged", topic_id)
    assert _query("SELECT COUNT(*) FROM topics") == [(1,)]


@requires_local_db
def test_place_topic_refuses_when_the_section_does_not_exist(seed_db):
    """The section rows are a migration step, so their absence means
    apply_schema.py has not run. A seed that quietly filed eighteen topics under
    nothing would be worse than a stopped script."""
    import utils

    _execute([f"DELETE FROM topic_sections WHERE name = '{CURRICULUM_SECTION}'"])

    with pytest.raises(LookupError) as excinfo:
        utils.place_topic("Work and careers", CURRICULUM_SECTION, 1)
    assert "apply_schema" in str(excinfo.value)
    assert _query("SELECT COUNT(*) FROM topics") == [(0,)], "nothing was created"


@requires_local_db
def test_place_topic_records_the_creator(seed_db):
    import utils

    _execute(["INSERT INTO users (id, google_sub, email) "
              "VALUES (7, 'sub-7', 'seven@example.com')"])
    utils.place_topic("Work and careers", CURRICULUM_SECTION, 1,
                      created_by_user_id=7)
    assert _query("SELECT created_by_user_id FROM topics") == [(7,)]


@requires_local_db
def test_a_saved_card_does_not_drag_a_placed_topic_back_to_other(seed_db):
    """The property the two-pass order rests on. `save_flashcard()` finds the
    topic by name and leaves its section alone (#218), which is what lets the
    curriculum be declared before its cards exist."""
    import utils

    utils.place_topic("Work and careers", CURRICULUM_SECTION, 1)
    utils.save_flashcard({"word": "resign", "topic": "Work and careers"})

    assert _placement("Work and careers") == (CURRICULUM_SECTION, 1)


# --- a whole run --------------------------------------------------------


@requires_local_db
def test_a_full_run_places_eighteen_numbered_topics_and_fills_them(
        seed_db, stub_lookup):
    import seed_topics
    import seed_words

    assert seed_topics.main(["--pause", "0"]) == 0

    rows = _query("SELECT t.position, t.name, COUNT(f.id) FROM topics t "
                  "JOIN topic_sections s ON t.section_id = s.id "
                  "LEFT JOIN flashcards f ON f.topic_id = t.id "
                  "WHERE s.name = %s "
                  "GROUP BY t.id, t.position, t.name ORDER BY t.position",
                  (CURRICULUM_SECTION,))
    assert [r[0] for r in rows] == list(range(1, 19)), "numbered 1..18"
    assert [r[1] for r in rows] == list(seed_words.SEED_WORDS), \
        "in the order the word list declares"
    assert all(count == 20 for _, _, count in rows), "twenty cards each"
    assert _query("SELECT COUNT(*) FROM flashcards WHERE topic_id IS NULL") == \
        [(0,)]
    assert len(stub_lookup) == 360


@requires_local_db
def test_the_seeded_deck_is_what_the_browse_page_will_show(seed_db, stub_lookup):
    """#218 renders `get_topics_by_section()`, so this is the end of the chain:
    the curriculum section stops being an empty heading."""
    import seed_topics
    import utils

    seed_topics.main(["--pause", "0"])

    grouped = dict(utils.get_topics_by_section())
    assert len(grouped[CURRICULUM_SECTION]) == 18
    assert grouped["Other"] == []
    assert grouped[CURRICULUM_SECTION][0] == ("Work and careers", 20), \
        "position, not alphabet"


@requires_local_db
def test_a_second_run_adds_nothing(seed_db, stub_lookup):
    """#101's duplicate rule is the whole of the idempotency, and it is what
    makes an interrupted run finishable by running it again."""
    import seed_topics

    seed_topics.main(["--topic", "Work and careers", "--pause", "0"])
    before = _query("SELECT COUNT(*) FROM flashcards")[0][0]

    seed_topics.main(["--topic", "Work and careers", "--pause", "0"])

    assert _query("SELECT COUNT(*) FROM flashcards")[0][0] == before
    assert _query("SELECT COUNT(*) FROM topics") == [(1,)]


@requires_local_db
def test_an_interrupted_run_is_finished_by_the_next_one(seed_db, stub_lookup):
    """Half a topic, then the whole of it: the second run adds only the rest."""
    import seed_topics
    import seed_words

    half = dict(list(seed_words.SEED_WORDS.items())[:1])
    half["Work and careers"] = half["Work and careers"][:8]
    counts = seed_topics.run(half, None, None, "google", "oxford", pause=0,
                             out=io.StringIO())
    assert counts.added == 8

    assert seed_topics.main(["--topic", "Work and careers", "--pause", "0"]) == 0
    assert _query("SELECT COUNT(*) FROM flashcards") == [(20,)]


@requires_local_db
def test_an_unowned_run_leaves_the_cards_and_the_topics_nobodys(
        seed_db, stub_lookup):
    """The default, and the honest answer: the deck was not added by a learner.
    The consequence is #127 — an 'only my cards' learner sees none of it."""
    import seed_topics
    import utils

    seed_topics.main(["--topic", "Work and careers", "--pause", "0"])

    assert _query("SELECT DISTINCT added_by_user_id FROM flashcards") == [(None,)]
    assert _query("SELECT created_by_user_id FROM topics") == [(None,)]
    assert utils.get_topics_by_section(owner_id=1) == \
        [(CURRICULUM_SECTION, []), ("Other", [])]


@requires_local_db
def test_owner_attributes_the_cards_and_the_topic_together(seed_db, stub_lookup):
    """One flag settles both, or the odd state is a run that created owned topics
    full of unowned cards."""
    import seed_topics

    _execute(["INSERT INTO users (id, google_sub, email) "
              "VALUES (7, 'sub-7', 'seven@example.com')"])

    assert seed_topics.main(["--topic", "Work and careers", "--pause", "0",
                             "--owner", "SEVEN@Example.com"]) == 0

    assert _query("SELECT DISTINCT added_by_user_id FROM flashcards") == [(7,)]
    assert _query("SELECT created_by_user_id FROM topics") == [(7,)]


@requires_local_db
def test_an_unknown_owner_email_is_refused_before_anything_is_written(
        seed_db, stub_lookup):
    """Refused rather than falling back to nobody: someone who passed --owner
    wants the deck attributed, and silently not doing it would be found out only
    by a learner opening an empty site."""
    import seed_topics

    assert seed_topics.main(["--topic", "Work and careers", "--pause", "0",
                             "--owner", "nobody@example.com"]) == 1

    assert _query("SELECT COUNT(*) FROM topics") == [(0,)]
    assert _query("SELECT COUNT(*) FROM flashcards") == [(0,)]
    assert stub_lookup == [], "and nothing was looked up"


@requires_local_db
def test_a_dry_run_changes_nothing(seed_db, stub_lookup):
    import seed_topics

    assert seed_topics.main(["--dry-run"]) == 0

    assert _query("SELECT COUNT(*) FROM topics") == [(0,)]
    assert _query("SELECT COUNT(*) FROM flashcards") == [(0,)]
    assert stub_lookup == []


@requires_local_db
def test_a_dry_run_reports_a_topic_it_would_move(seed_db, stub_lookup, capsys):
    """`current_placement()` reads the real table, so this is the query that
    turns "18 would be created" into "one of yours would be moved"."""
    import seed_topics
    import utils

    utils.save_flashcard({"word": "resign", "topic": "Work and careers"})

    seed_topics.main(["--dry-run", "--topic", "Work and careers"])

    assert "would MOVE from 'Other' position 0" in capsys.readouterr().out
    assert _placement("Work and careers") == ("Other", 0), "and did not move it"
