"""
Shared fixtures for the KuantorFlow test suite.

The app-level tests import the Flask app from the kuantorflow repository
(path from KUANTORFLOW_PATH in .env, defaulting to a sibling checkout)
and stub out the database and external services — they run fully offline
and never write anywhere.
"""

import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

KUANTORFLOW_PATH = os.environ.get(
    "KUANTORFLOW_PATH",
    str(Path(__file__).resolve().parent.parent.parent / "kuantorflow"),
)
sys.path.insert(0, KUANTORFLOW_PATH)

# Keyword used by the app-level tests (patched into the app; the real
# keyword from .env is only used by the live site tests).
TEST_KEYWORD = "test-keyword"

# The curriculum section #215 creates empty and #203 will fill. Named here
# because tests assert on it by name and it is spelled with an en dash.
CURRICULUM_SECTION = "B2–C1 Conversational Topics"


def in_other(topics):
    """`get_topics_by_section()`'s shape, with `topics` filed under 'Other'.

    What a real database looks like today (kuantorflow#218): every topic is in
    'Other', and the curriculum section exists but is empty. Tests that only
    care *that* some topics reach the page use this rather than spelling the
    grouping out, and get the empty-section heading exercised for free.
    """
    return [(CURRICULUM_SECTION, []), ("Other", list(topics))]


@pytest.fixture(autouse=True)
def settings_dir(tmp_path, monkeypatch):
    """Redirect the settings store to a per-test temp directory.

    Autouse because the store creates a config file on first read (#86), so
    any test that renders a page would otherwise write into the real
    kuantorflow checkout's settings/ directory."""
    import settings_store

    directory = tmp_path / "settings"
    monkeypatch.setattr(settings_store, "SETTINGS_DIR", directory)
    return directory


@pytest.fixture(autouse=True)
def action_logs(tmp_path, monkeypatch):
    """Redirect the action logs (kuantorflow#30) to a per-test temp directory.

    Autouse for the same reason as settings_dir: any test that saves a card,
    looks a word up or uploads a file writes a log line, which would otherwise
    land in the real kuantorflow checkout's logs/ directory."""
    import applog

    directory = tmp_path / "logs"
    monkeypatch.setattr(applog, "LOGS_DIR", directory)
    return directory


@pytest.fixture(autouse=True)
def chat_logs(tmp_path, monkeypatch):
    """Redirect Mykola's chat logs to a per-test temp directory.

    Same reason as settings_dir and action_logs: the chat endpoint appends a
    log file per exchange, and a restarted chat (ai_agent#54) opens one — all
    of which otherwise pile up in the real kuantorflow checkout's
    mykola_logs/. Tests that need a pre-existing conversation write it here."""
    import app as app_mod

    directory = tmp_path / "mykola_logs"
    directory.mkdir()
    monkeypatch.setattr(app_mod, "LOG_DIR", directory)
    return directory


@pytest.fixture()
def keyword():
    return TEST_KEYWORD


@pytest.fixture()
def app_module(monkeypatch):
    """The imported app module with a known gate keyword and a stubbed
    topic list (so no test touches a real database by accident)."""
    import app as app_mod

    monkeypatch.setattr(app_mod, "ACCESS_KEYWORD", TEST_KEYWORD)
    monkeypatch.setattr(app_mod, "get_topics", lambda owner_id=None: [])
    # The index page reads the grouped shape now (kuantorflow#218); /topics.json
    # reads both. Stubbed alongside get_topics so no test reaches a real
    # database by accident, which is the whole point of this fixture.
    monkeypatch.setattr(app_mod, "get_topics_by_section",
                        lambda owner_id=None: [], raising=False)
    # Any anonymous chat message counts itself against the daily ceiling
    # (kuantorflow#164) — a real database write. Stub it here so the whole
    # suite stays offline; the tests that care patch it themselves.
    monkeypatch.setattr(app_mod, "claim_anonymous_message",
                        lambda limit: (True, 0), raising=False)
    # Default: no word already exists, so lookup tests reach the review popup
    # without touching a real DB (#145). Tests opt in by re-patching this.
    monkeypatch.setattr(app_mod, "flashcard_word_exists", lambda word: False,
                        raising=False)
    return app_mod


class FakeCardCursor:
    """A cursor that answers the statements the card write paths run.

    `save_flashcard()` and `move_flashcard()` stopped being one query each when
    topics became a table (kuantorflow#207): a topic **name** now has to be
    resolved to an id, which adds a lookup and sometimes an insert. A fake that
    handed back the same canned row to every `fetchone()` cannot represent that
    — it would answer the topic lookup with a flashcards row — so this one
    dispatches on the statement it was last given.

    Each canned row says what the database *contains*, not what should happen:

    - `card` — the row behind ``SELECT ... FROM flashcards WHERE id``, as
      ``(word, topic, topic_id, added_by_user_id)``. None means no such card.
    - `duplicate` — the answer to the word+pos check; None means "not a
      duplicate", which is what lets a save proceed.
    - `topic` — the row behind ``SELECT id, name FROM topics WHERE name``, as
      ``(id, name)``. **None means the topic does not exist yet**, so the code
      under test creates it — the case worth exercising most.
    - `update_rows` — what the conditional UPDATE reports. 0 is a refusal, and
      is how "the card changed hands between the read and the write" is staged.
    """

    def __init__(self, *, card=None, duplicate=None, topic=None,
                 update_rows=1, topic_id=3, card_id=42, section_id=6):
        self.card = card
        self.duplicate = duplicate
        self.topic = topic
        self.update_rows = update_rows
        self.topic_id = topic_id
        self.card_id = card_id
        # The id of 'Other', the section a new topic is filed under
        # (kuantorflow#215). `None` models a database whose section rows have
        # not been inserted yet, where a topic is created without one.
        self.section_id = section_id
        self.queries = []
        self.rowcount = 1
        self.lastrowid = card_id
        self._last = ""

    def execute(self, query, params=None):
        collapsed = " ".join(query.split())
        self.queries.append((collapsed, params))
        self._last = collapsed
        if collapsed.startswith("INSERT INTO topics"):
            # A row that was not there: MySQL reports one affected row and
            # LAST_INSERT_ID() gives the new id. Both are what tell
            # _get_or_create_topic() that *it* created the topic.
            self.rowcount = 1
            self.lastrowid = self.topic_id
        elif collapsed.startswith("INSERT INTO flashcards"):
            self.lastrowid = self.card_id
        elif collapsed.startswith("UPDATE flashcards"):
            self.rowcount = self.update_rows

    def fetchone(self):
        if "FROM topics WHERE name" in self._last:
            return self.topic
        if "FROM topics WHERE id" in self._last:
            return (self.topic[1],) if self.topic else None
        # Answered explicitly rather than falling through to `duplicate`
        # (kuantorflow#215): the section lookup happens on the same cursor, and
        # a test that sets `duplicate` would otherwise hand its value back here
        # as a section id.
        if "FROM topic_sections WHERE name" in self._last:
            return (self.section_id,) if self.section_id is not None else None
        if "FROM flashcards WHERE id" in self._last:
            return self.card
        return self.duplicate       # the word+pos duplicate check

    def fetchall(self):
        return []

    def close(self):
        pass


class FakeCardConn:
    """The connection around a FakeCardCursor; records whether it committed."""

    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def cursor(self, **kwargs):
        return self._cursor

    def commit(self):
        self.committed = True

    def close(self):
        pass


def fake_card_db(monkeypatch, **kwargs):
    """Point utils at a FakeCardCursor. Returns (cursor, connection)."""
    import utils

    cursor = FakeCardCursor(**kwargs)
    conn = FakeCardConn(cursor)
    monkeypatch.setattr(utils, "get_db_connection", lambda: conn)
    return cursor, conn


def inserted_card(cursor):
    """The ``INSERT INTO flashcards`` statement and its parameters.

    Not simply "the first INSERT": creating a topic inserts too, and it happens
    first (kuantorflow#207).
    """
    return next((q, p) for q, p in cursor.queries
                if q.startswith("INSERT INTO flashcards"))


class SavedCards(list):
    """Cards captured from save_flashcard(), and who each was attributed to.

    Still a plain list of entries, so `saved[0]["word"]` keeps working; the
    owner ids (kuantorflow#89) ride alongside in `owner_ids`, index for index.
    """

    def __init__(self):
        super().__init__()
        self.owner_ids = []


@pytest.fixture()
def saved(app_module, monkeypatch):
    """Capture save_flashcard() calls instead of writing to MySQL."""
    captured = SavedCards()

    def fake_save(entry, added_by_user_id=None):
        captured.append(entry)
        captured.owner_ids.append(added_by_user_id)
        return 1

    monkeypatch.setattr(app_module, "save_flashcard", fake_save)
    return captured


@pytest.fixture(autouse=True)
def block_state(app_module, monkeypatch):
    """No account is blocked unless a test says so (kuantorflow#126).

    Autouse because `app.current_block()` runs on every signed-in request —
    the widget, the card pages and every save route ask it. Without this the
    offline suite would open a real connection to whatever `DB_*` points at:
    the same trap the `saved` fixture exists for, since local MySQL *is*
    reachable and "offline" is a property of the fixtures, not the network.

    A test that wants a blocked account calls `block_state.block(...)`.
    """
    class BlockState:
        def __init__(self):
            self.value = None

        def block(self, reason="spam in chat", at="2026-08-02 10:00:00"):
            """Block whoever the request is signed in as."""
            self.value = (at, reason)
            return self.value

    state = BlockState()
    # Keyed on there being a user id at all: an anonymous visitor has no
    # account to block, exactly as get_user_block() answers None for one.
    monkeypatch.setattr(app_module, "get_user_block",
                        lambda user_id: state.value if user_id else None)
    return state


@pytest.fixture()
def client(app_module):
    """A test client already through the keyword gate."""
    c = app_module.app.test_client()
    resp = c.post("/enter", data={"keyword": TEST_KEYWORD})
    assert resp.status_code == 302, "gate login failed in fixture"
    return c


@pytest.fixture()
def fresh_client(app_module):
    """A test client with no session — still outside the gate."""
    return app_module.app.test_client()


TEST_USER_EMAIL = "test.user@gmail.com"
TEST_USER_ID = 7


@pytest.fixture()
def user_client(client):
    """A test client through the gate AND signed in (session identity only).

    Changing settings requires a signed-in user since kuantorflow#102 —
    anonymous visitors share config-default.json, which is read-only for
    them. Settings saved through this client land in
    config-test.user.json.

    The session carries an `id` as a real one does since kuantorflow#148 —
    that is the id cards are attributed to (#89)."""
    with client.session_transaction() as sess:
        sess["user"] = {"id": TEST_USER_ID, "name": "Test User",
                        "email": TEST_USER_EMAIL}
    return client
