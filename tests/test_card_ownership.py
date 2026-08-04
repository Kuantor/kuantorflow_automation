"""Who added a card: the added_by_user_id column (kuantorflow#89).

Every card the app writes records the id of the signed-in user who saved it.
The id comes from the server-side session only — the review popup posts hidden
fields, so anything the browser sends about ownership has to be ignored. The
field is stored, never displayed.

Since kuantorflow#125 a visitor with no account cannot write at all, so the
app no longer produces an unowned card: NULL now means "saved before #89", and
the storage layer's NULL path (exercised directly against `utils` below) is
reachable only by the maintenance scripts. The refusal itself is
test_anonymous_writes.py; what is checked here is that nothing slips through
it into the database with no owner.
"""

import pytest
from flask import session

import utils
from conftest import TEST_USER_ID, fake_card_db, inserted_card


CARD_FORM = {
    "word": "resilient",
    "pos": "adjective",
    "topic": "character",
    "explanation_en": "able to recover quickly",
    "translation_ukr": "стійкий",
}


# --- the column reaches the database ------------------------------------------

class FakeCursor:
    def __init__(self, existing_row=None):
        self.existing = existing_row
        self.queries = []
        self.lastrowid = 42

    def execute(self, query, params=None):
        self.queries.append((" ".join(query.split()), params))

    def fetchone(self):
        return self.existing

    def close(self):
        pass


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, **kwargs):
        return self._cursor

    def commit(self):
        pass

    def close(self):
        pass


def _fake_db(monkeypatch, cursor):
    monkeypatch.setattr(utils, "get_db_connection", lambda: FakeConn(cursor))


# Where the owner sits among the bound values. It used to be last; since
# kuantorflow#207 topic_id trails it, so the position is derived from the field
# list rather than counted backwards from the end.
OWNER = len(utils.FLASHCARD_FIELDS)


def test_the_id_is_inserted_with_the_card(monkeypatch):
    cursor, _ = fake_card_db(monkeypatch)
    utils.save_flashcard({"word": "resilient", "topic": "vocab"},
                         added_by_user_id=7)
    query, params = inserted_card(cursor)
    assert "added_by_user_id" in query
    assert params[OWNER] == 7, "the id follows the card's own fields"


def test_no_id_is_stored_as_null(monkeypatch):
    cursor, _ = fake_card_db(monkeypatch)
    utils.save_flashcard({"word": "resilient", "topic": "vocab"})
    _, params = inserted_card(cursor)
    assert params[OWNER] is None, \
        "an anonymous save must store NULL, not a sentinel"


def test_the_id_is_never_read_out_of_the_entry(monkeypatch):
    """The entry dict is built from form data, so it must not be a source of
    ownership even if a key of that name turns up in it."""
    cursor, _ = fake_card_db(monkeypatch)
    utils.save_flashcard(
        {"word": "resilient", "topic": "vocab", "added_by_user_id": 999})
    _, params = inserted_card(cursor)
    assert 999 not in params
    assert params[OWNER] is None


def test_the_same_id_creates_the_topic(monkeypatch):
    """One argument serves both (kuantorflow#207), so the card's owner and the
    topic's creator cannot disagree about who was here."""
    cursor, _ = fake_card_db(monkeypatch, topic=None)
    utils.save_flashcard({"word": "resilient", "topic": "a new topic"},
                         added_by_user_id=7)
    insert = next(q for q, _ in cursor.queries if q.startswith("INSERT INTO topics"))
    params = next(p for q, p in cursor.queries if q.startswith("INSERT INTO topics"))
    assert "created_by_user_id" in insert
    assert params == ("a new topic", 7)


def test_a_topic_creator_is_never_read_out_of_the_entry(monkeypatch):
    """Same trap as the card's owner, one column along."""
    cursor, _ = fake_card_db(monkeypatch, topic=None)
    utils.save_flashcard({"word": "resilient", "topic": "a new topic",
                          "created_by_user_id": 999})
    params = next(p for q, p in cursor.queries if q.startswith("INSERT INTO topics"))
    assert params == ("a new topic", None)


# --- every save path records the owner ----------------------------------------

def test_review_popup_records_the_signed_in_user(user_client, saved):
    resp = user_client.post("/cards/add", data=dict(CARD_FORM))
    assert resp.get_json() == {"ok": True, "saved": True}
    assert saved.owner_ids == [TEST_USER_ID]


def test_the_review_popup_writes_nothing_for_anonymous(client, saved):
    """Before #125 this saved a card with no owner; now it saves nothing."""
    resp = client.post("/cards/add", data=dict(CARD_FORM))
    assert resp.status_code == 403
    assert saved.owner_ids == []


def _stub_automatic_add(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "lookup_word", lambda *a, **k: [
        {"word": "resilient", "pos": "adjective", "topic": "vocab"}])
    monkeypatch.setattr(app_module, "current_settings", lambda: dict(
        translator="google", explanatory_dictionary="oxford",
        cards_automatically=True, show_ukrainian=True, show_russian=True,
        quiz_lang="ukr"))


def test_automatic_add_records_the_signed_in_user(user_client, app_module,
                                                  monkeypatch, saved):
    _stub_automatic_add(app_module, monkeypatch)
    user_client.post("/", data={"action": "parse_word", "word": "resilient",
                                "topic": "vocab"})
    assert saved.owner_ids == [TEST_USER_ID]


def test_automatic_add_writes_nothing_for_anonymous(client, app_module,
                                                    monkeypatch, saved):
    _stub_automatic_add(app_module, monkeypatch)
    client.post("/", data={"action": "parse_word", "word": "resilient",
                           "topic": "vocab"})
    assert saved.owner_ids == []


def test_mykola_chat_saver_records_the_owner(app_module, saved):
    """Mykola's card saver runs inside the chat request, so it sees the same
    session as every other save path (ai_agent#20)."""
    with app_module.app.test_request_context("/mykola/chat"):
        session["user"] = {"id": TEST_USER_ID, "email": "test.user@gmail.com"}
        app_module._save_card_from_chat(
            {"word": "resilient", "pos": "adjective", "topic": "vocab"})
    assert saved.owner_ids == [TEST_USER_ID]


# --- sessions from before the users table -------------------------------------

PRE_148_SESSION = {"name": "Test User", "email": "test.user@gmail.com",
                   "picture": "https://example.com/a.jpg"}


def test_a_session_without_an_id_key_is_signed_out(client):
    """A session created before kuantorflow#148 has no `id` and no users row
    behind it, so it would attribute every card to nobody while still looking
    signed in. It is dropped once; the next sign-in repairs it."""
    with client.session_transaction() as sess:
        sess["user"] = dict(PRE_148_SESSION)
    client.get("/")
    with client.session_transaction() as sess:
        assert "user" not in sess


def test_dropping_the_identity_keeps_the_gate_pass(client):
    """Only the identity goes — being sent back to the keyword gate as well
    would make an invisible repair very visible."""
    with client.session_transaction() as sess:
        sess["user"] = dict(PRE_148_SESSION)
    assert client.get("/").status_code == 200
    with client.session_transaction() as sess:
        assert sess.get("access_granted") is True


def test_a_gated_request_is_repaired_too(fresh_client):
    """The check runs before the gate, which short-circuits the chain."""
    with fresh_client.session_transaction() as sess:
        sess["user"] = dict(PRE_148_SESSION)
    assert fresh_client.get("/").status_code == 302      # still gated
    with fresh_client.session_transaction() as sess:
        assert "user" not in sess


def test_an_id_of_none_is_left_alone(client, saved):
    """A sign-in whose users row could not be written stores id=None (#148).
    That is tolerated by design — signing in again would fail the same way —
    so the identity must survive."""
    with client.session_transaction() as sess:
        sess["user"] = dict(PRE_148_SESSION, id=None)
    client.get("/")
    with client.session_transaction() as sess:
        assert sess["user"]["email"] == "test.user@gmail.com"


def test_a_current_session_is_untouched(user_client, saved):
    user_client.get("/")
    with user_client.session_transaction() as sess:
        assert sess["user"]["id"] == TEST_USER_ID


def test_the_dropped_session_cannot_save_a_card(client, saved):
    """The symptom this repairs: the card was saved unattributed while the
    visitor looked signed in. Dropping the identity now also stops the save
    outright (#125), which is the louder and more honest failure."""
    with client.session_transaction() as sess:
        sess["user"] = dict(PRE_148_SESSION)
    assert client.post("/cards/add", data=dict(CARD_FORM)).status_code == 403
    assert saved.owner_ids == []
    with client.session_transaction() as sess:
        assert "user" not in sess, "and the next request signs them in again"


def test_a_sign_in_without_a_row_cannot_save(client, saved):
    """A users row that could not be written leaves id None in the session
    (kuantorflow#148). Before #125 the card was saved without an owner; now it
    is refused — the fail-closed direction, because an unowned card cannot be
    deleted by the person who added it (#162)."""
    with client.session_transaction() as sess:
        sess["user"] = {"id": None, "name": "Test User",
                        "email": "test.user@gmail.com"}
    resp = client.post("/cards/add", data=dict(CARD_FORM))
    assert resp.status_code == 403
    assert saved.owner_ids == []


# --- ownership cannot be forged from the browser ------------------------------

def test_a_forged_id_from_an_anonymous_visitor_buys_nothing(client, saved):
    """Posting an id does not make the visitor signed in: #125 refuses the
    save, and the id never reaches the database either way."""
    resp = client.post("/cards/add", data=dict(CARD_FORM, added_by_user_id="7"))
    assert resp.status_code == 403
    assert saved.owner_ids == []


def test_a_signed_in_user_cannot_attribute_a_card_to_someone_else(user_client,
                                                                  saved):
    user_client.post("/cards/add", data=dict(CARD_FORM, added_by_user_id="99"))
    assert saved.owner_ids == [TEST_USER_ID]


def test_the_posted_field_does_not_reach_the_card_either(user_client, saved):
    user_client.post("/cards/add", data=dict(CARD_FORM, added_by_user_id="7"))
    assert "added_by_user_id" not in saved[0]


# --- invisible to the user ----------------------------------------------------

STORED_CARD = {
    "id": 1,
    "word": "resilient",
    "pos": "adjective",
    "explanation_en": "able to recover quickly",
    "examples_en": [],
    "translation_ukr": "стійкий",
    "examples_ukr": [],
    "translation_rus": None,
    "examples_rus": [],
    "topic": "character",
    "added_by_user_id": 7,
}


@pytest.mark.parametrize("path", ["/flashcards/character", "/deck/character"])
def test_the_owner_is_not_rendered(client, app_module, monkeypatch, path):
    """SELECT * now returns the column, so the card pages must not leak it."""
    monkeypatch.setattr(app_module, "get_flashcards_by_topic",
                        lambda topic, owner_id=None: [dict(STORED_CARD)])
    body = client.get(path).get_data(as_text=True)
    assert "added_by_user_id" not in body
    assert ">7<" not in body


def test_the_review_popup_posts_no_owner_field(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "lookup_word", lambda *a, **k: [
        {"word": "resilient", "pos": "adjective", "topic": "vocab",
         "explanation_en": "able to recover quickly"}])
    body = client.post("/", data={"action": "parse_word", "word": "resilient",
                                  "topic": "vocab"}).get_data(as_text=True)
    assert "added_by_user_id" not in body
