"""Private topics against a real LOCAL MySQL (marker: db) — kuantorflow#382.

The offline tests prove the plumbing: that every read is told who is asking,
that a private topic is refused when named, who may change it. **This proves
what the database actually returns**, which is the only thing the feature is.
A fake that answers a WHERE clause by agreeing with it proves nothing at all,
and three of the things here cannot be faked even in principle:

* the unique key. `(name, namespace)` is what lets a private *Work* exist
  beside the public one and stops a second of either — enforced by MySQL, not
  by the app, because an application check has a gap between the question and
  the write;
* `namespace` as a plain column. It wants to be
  `IF(is_public, 0, created_by_user_id)` and MySQL refuses it both as a
  generated column (1215) and as a CHECK (3823), because `fk_topics_user`'s
  ON DELETE SET NULL needs that column for its referential action. So the app
  writes it, and these tests are where "the app writes it correctly" stops
  being a claim;
* what a departing account leaves behind. `resolve_user_cards()` makes its
  private topics public before the foreign key nulls their creator, and merges
  the one case that cannot: a private *Work* released into a namespace a public
  *Work* already occupies.

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

SCRATCH_DB = "kuantorflow_private_topics_test"

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


def _execute(statements, params=None, database=SCRATCH_DB):
    conn = _connect(database)
    cursor = conn.cursor()
    for i, statement in enumerate(statements):
        cursor.execute(statement, (params or {}).get(i, ()))
    conn.commit()
    cursor.close()
    conn.close()


@pytest.fixture()
def deck(monkeypatch):
    """A scratch database with two learners and four topics, and `utils`
    pointed at it.

    Built by running the app's own `apply_schema.py`, so the table under test
    is the table the deploy makes -- not a hand-written copy that could drift
    from it, which is the thing this file is least able to afford.
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
        # Public 'Work', Anton's private 'Work', Anton's private 'Diary',
        # Olena's public 'Travel'. The two Works are the point.
        "INSERT INTO topics (id, name, created_by_user_id, is_public, namespace,"
        "                    section_id) "
        "SELECT 10, 'Work', 1, 1, 0, id FROM topic_sections WHERE name='Other'",
        "INSERT INTO topics (id, name, created_by_user_id, is_public, namespace,"
        "                    section_id) "
        "SELECT 11, 'Work', 1, 0, 1, id FROM topic_sections WHERE name='Other'",
        "INSERT INTO topics (id, name, created_by_user_id, is_public, namespace,"
        "                    section_id) "
        "SELECT 12, 'Diary', 1, 0, 1, id FROM topic_sections WHERE name='Other'",
        "INSERT INTO topics (id, name, created_by_user_id, is_public, namespace,"
        "                    section_id) "
        "SELECT 13, 'Travel', 2, 1, 0, id FROM topic_sections WHERE name='Other'",
        "INSERT INTO flashcards (word, topic, topic_id, added_by_user_id) VALUES "
        "('shared', 'Work', 10, 1),"
        "('secret', 'Work', 11, 1),"
        "('journal', 'Diary', 12, 1),"
        "('abroad', 'Travel', 13, 2)",
    ])

    sys.path.insert(0, str(KUANTORFLOW_PATH))
    import utils
    # `get_db_connection()` reads DB_NAME from the environment at call time,
    # so the env var is the whole redirection -- and monkeypatch puts it back
    # afterwards, which is what keeps the configured database untouched.
    monkeypatch.setenv("DB_NAME", SCRATCH_DB)
    try:
        yield utils
    finally:
        _execute([f"DROP DATABASE IF EXISTS {SCRATCH_DB}"], database=None)


# --- what each visitor sees -------------------------------------------------

@requires_local_db
def test_the_owner_sees_their_private_topics(deck):
    names = [name for name, _count in deck.get_topics(viewer_id=ANTON)]

    assert sorted(names) == ["Diary", "Travel", "Work", "Work"], (
        "both Works -- the public one and their own -- and everything public")


@requires_local_db
def test_everybody_else_sees_only_the_public_one(deck):
    names = [name for name, _count in deck.get_topics(viewer_id=OLENA)]

    assert sorted(names) == ["Travel", "Work"]
    assert "Diary" not in names


@requires_local_db
def test_an_anonymous_visitor_sees_only_public_topics(deck):
    names = [name for name, _count in deck.get_topics()]

    assert sorted(names) == ["Travel", "Work"]


@requires_local_db
def test_the_admin_sees_everything(deck):
    names = [name for name, _count in deck.get_topics(viewer_id=OLENA,
                                                      admin=True)]

    assert sorted(names) == ["Diary", "Travel", "Work", "Work"]


@requires_local_db
def test_the_cards_of_a_private_topic_are_hidden_too(deck):
    """The topic is the unit, and the cards go with it. Asked for by *name*,
    which is how a URL or a remembered game selection asks."""
    words = [c["word"] for c in deck.get_flashcards_by_topics(
        ["Work", "Diary"], viewer_id=OLENA)]

    assert words == ["shared"]


@requires_local_db
def test_the_owner_gets_both_topics_worth(deck):
    words = sorted(c["word"] for c in deck.get_flashcards_by_topics(
        ["Work", "Diary"], viewer_id=ANTON))

    assert words == ["journal", "secret", "shared"]


@requires_local_db
def test_the_preference_and_the_permission_compose(deck):
    """#127 on, as somebody else: their own cards only, and still nothing from
    a topic that is not theirs. The setting narrows what is already allowed --
    it can never widen it."""
    words = [c["word"] for c in deck.get_flashcards_by_topics(
        ["Work", "Diary", "Travel"], owner_id=OLENA, viewer_id=OLENA)]

    assert words == ["abroad"]


@requires_local_db
def test_the_browse_page_hides_it_as_well(deck):
    """`get_topics_by_section()` counts and groups, and the clause has to sit
    in a WHERE there rather than in the ON where #127's lives -- a topic you
    may not see should not be counted, let alone returned."""
    sections = deck.get_topics_by_section(viewer_id=OLENA)
    names = [name for _section, topics in sections for name, _c in topics]

    assert sorted(names) == ["Travel", "Work"]


# --- resolving a name that two topics hold ---------------------------------

@requires_local_db
def test_a_name_resolves_to_your_own_first(deck):
    found = deck.resolve_topic("Work", viewer_id=ANTON)

    assert found["id"] == 11 and found["is_public"] is False


@requires_local_db
def test_and_to_the_public_one_for_everybody_else(deck):
    found = deck.resolve_topic("Work", viewer_id=OLENA)

    assert found["id"] == 10 and found["is_public"] is True


@requires_local_db
def test_a_name_you_may_not_see_resolves_to_nothing(deck):
    assert deck.resolve_topic("Diary", viewer_id=OLENA) is None
    assert deck.resolve_topic("Diary") is None


@requires_local_db
def test_an_id_still_goes_through_the_rule(deck):
    """`?t=` is a guess like any other."""
    assert deck.resolve_topic("Diary", viewer_id=OLENA, topic_id=12) is None
    assert deck.resolve_topic("Diary", viewer_id=ANTON, topic_id=12)["id"] == 12


@requires_local_db
def test_a_card_files_into_your_own_topic_of_that_name(deck):
    """`_get_or_create_topic()` prefers the caller's namespace, which is the
    whole of what private topics cost the save path."""
    conn = deck.get_db_connection()
    cursor = conn.cursor()
    try:
        assert deck._get_or_create_topic(cursor, "Work", ANTON)[0] == 11
        assert deck._get_or_create_topic(cursor, "Work", OLENA)[0] == 10
        assert deck._get_or_create_topic(cursor, "Work", None)[0] == 10
    finally:
        cursor.close()
        conn.close()


# --- the key, which is the guarantee ---------------------------------------

@requires_local_db
def test_two_public_topics_cannot_share_a_name(deck):
    import mysql.connector

    with pytest.raises(mysql.connector.IntegrityError):
        _execute(["INSERT INTO topics (name, created_by_user_id, is_public, "
                  "namespace) VALUES ('Work', 2, 1, 0)"])


@requires_local_db
def test_one_learner_cannot_hold_two_private_topics_of_a_name(deck):
    import mysql.connector

    with pytest.raises(mysql.connector.IntegrityError):
        _execute(["INSERT INTO topics (name, created_by_user_id, is_public, "
                  "namespace) VALUES ('Work', 1, 0, 1)"])


@requires_local_db
def test_two_learners_may_each_hold_one(deck):
    _execute(["INSERT INTO topics (name, created_by_user_id, is_public, "
              "namespace) VALUES ('Work', 2, 0, 2)"])

    assert deck.resolve_topic("Work", viewer_id=OLENA)["is_public"] is False


# --- changing it ------------------------------------------------------------

@requires_local_db
def test_making_a_topic_private_writes_both_columns(deck):
    """`namespace` is the app's job only because MySQL would not derive it, and
    the two disagreeing is the one way this breaks quietly: the key would then
    be reserving the wrong name."""
    assert deck.set_topic_visibility(13, False, viewer_id=OLENA) == "changed"

    conn = deck.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_public, namespace FROM topics WHERE id = 13")
    assert cursor.fetchone() == (0, OLENA)
    cursor.close()
    conn.close()


@requires_local_db
def test_it_is_refused_when_the_topic_holds_other_peoples_cards(deck):
    _execute(["INSERT INTO flashcards (word, topic, topic_id, added_by_user_id)"
              " VALUES ('borrowed', 'Travel', 13, 1)"])

    assert deck.set_topic_visibility(13, False, viewer_id=OLENA) == "shared"
    assert deck.resolve_topic("Travel", viewer_id=OLENA)["is_public"] is True


@requires_local_db
def test_an_unowned_card_counts_as_somebody_elses(deck):
    """The seeded deck (#203) is unowned and shared by construction."""
    _execute(["INSERT INTO flashcards (word, topic, topic_id) "
              "VALUES ('seeded', 'Travel', 13)"])

    assert deck.set_topic_visibility(13, False, viewer_id=OLENA) == "shared"


@requires_local_db
def test_a_topic_with_no_creator_cannot_be_private(deck):
    """Nothing could ever see it again: every visibility test is
    `created_by_user_id = me`."""
    _execute(["INSERT INTO topics (id, name, is_public, namespace) "
              "VALUES (20, 'Seeded', 1, 0)"])

    assert deck.set_topic_visibility(20, False, viewer_id=ANTON,
                                     admin=True) == "nobodys"


@requires_local_db
def test_somebody_elses_topic_is_not_yours_to_hide(deck):
    assert deck.set_topic_visibility(13, False, viewer_id=ANTON) == "denied"


@requires_local_db
def test_releasing_a_name_the_public_deck_holds_is_refused(deck):
    """Anton's private *Work* cannot become public while the public *Work*
    exists. The database answers, rather than a check beforehand -- a check has
    a gap between the question and the write."""
    assert deck.set_topic_visibility(11, True, viewer_id=ANTON) == "taken"


@requires_local_db
def test_the_admin_may_change_somebody_elses(deck):
    """Their decision (#382): the admin monitors the deck."""
    assert deck.set_topic_visibility(12, True, viewer_id=OLENA,
                                     admin=True) == "changed"


# --- and what a departing account leaves behind ----------------------------

@requires_local_db
def test_deleting_an_account_frees_its_private_topics(deck):
    """A private topic whose creator is gone is one nobody can see and nobody
    can un-hide, and its name stays reserved in a dead namespace."""
    deck.resolve_user_cards(ANTON, keep_cards=True)

    conn = deck.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_public, namespace FROM topics WHERE id = 12")
    assert cursor.fetchone() == (1, 0), "Diary is public again"
    cursor.close()
    conn.close()


@requires_local_db
def test_a_released_name_that_collides_is_merged_rather_than_lost(deck):
    """Anton's private *Work* cannot be released into a name the public deck
    already holds, so its cards move to the public *Work* and the empty row
    goes -- where they would have been if the topic had never been private.

    The alternative is the foreign key rejecting the release and account
    deletion failing, which is #165 broken for anyone who ever made a topic
    private.
    """
    deck.resolve_user_cards(ANTON, keep_cards=True)

    conn = deck.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT topic_id FROM flashcards WHERE word = 'secret'")
    assert cursor.fetchone()[0] == 10, "moved to the public Work"
    cursor.execute("SELECT COUNT(*) FROM topics WHERE id = 11")
    assert cursor.fetchone()[0] == 0, "and the empty private row is gone"
    cursor.close()
    conn.close()


@requires_local_db
def test_the_account_can_then_actually_be_deleted(deck):
    """The whole point of the sweep: `delete_user()` runs the foreign key's
    ON DELETE SET NULL over these rows, and it must not meet one it cannot
    settle."""
    deck.resolve_user_cards(ANTON, keep_cards=True)

    assert deck.delete_user(ANTON) is True
