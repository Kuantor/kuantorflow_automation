"""Who added a card: the added_by_user_id column (kuantorflow#89).

Every card the app writes records the id of the signed-in user who saved it,
or NULL for an anonymous visitor. The id comes from the server-side session
only — the review popup posts hidden fields, so anything the browser sends
about ownership has to be ignored. The field is stored, never displayed.
"""

import pytest
from flask import session

import utils
from conftest import TEST_USER_ID


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


def _insert(cursor):
    return next((q, p) for q, p in cursor.queries if q.startswith("INSERT"))


def test_the_id_is_inserted_with_the_card(monkeypatch):
    cursor = FakeCursor()
    _fake_db(monkeypatch, cursor)
    utils.save_flashcard({"word": "resilient", "topic": "vocab"},
                         added_by_user_id=7)
    query, params = _insert(cursor)
    assert "added_by_user_id" in query
    assert params[-1] == 7, "the id must be the last bound value"


def test_no_id_is_stored_as_null(monkeypatch):
    cursor = FakeCursor()
    _fake_db(monkeypatch, cursor)
    utils.save_flashcard({"word": "resilient", "topic": "vocab"})
    _, params = _insert(cursor)
    assert params[-1] is None, "an anonymous save must store NULL, not a sentinel"


def test_the_id_is_never_read_out_of_the_entry(monkeypatch):
    """The entry dict is built from form data, so it must not be a source of
    ownership even if a key of that name turns up in it."""
    cursor = FakeCursor()
    _fake_db(monkeypatch, cursor)
    utils.save_flashcard(
        {"word": "resilient", "topic": "vocab", "added_by_user_id": 999})
    _, params = _insert(cursor)
    assert 999 not in params
    assert params[-1] is None


# --- every save path records the owner ----------------------------------------

def test_review_popup_records_the_signed_in_user(user_client, saved):
    resp = user_client.post("/cards/add", data=dict(CARD_FORM))
    assert resp.get_json() == {"ok": True, "saved": True}
    assert saved.owner_ids == [TEST_USER_ID]


def test_review_popup_records_nothing_for_anonymous(client, saved):
    client.post("/cards/add", data=dict(CARD_FORM))
    assert saved.owner_ids == [None]


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


def test_automatic_add_records_nothing_for_anonymous(client, app_module,
                                                     monkeypatch, saved):
    _stub_automatic_add(app_module, monkeypatch)
    client.post("/", data={"action": "parse_word", "word": "resilient",
                           "topic": "vocab"})
    assert saved.owner_ids == [None]


@pytest.mark.parametrize("identity, expected", [
    ({"id": TEST_USER_ID, "email": "test.user@gmail.com"}, TEST_USER_ID),
    (None, None),
])
def test_mykola_chat_saver_records_the_owner(app_module, saved, identity,
                                             expected):
    """Mykola's card saver runs inside the chat request, so it sees the same
    session as every other save path (ai_agent#20)."""
    with app_module.app.test_request_context("/mykola/chat"):
        if identity is not None:
            session["user"] = identity
        app_module._save_card_from_chat(
            {"word": "resilient", "pos": "adjective", "topic": "vocab"})
    assert saved.owner_ids == [expected]


def test_a_sign_in_without_a_row_saves_anonymously(client, saved):
    """A users row that could not be written leaves id None in the session
    (kuantorflow#148) — the card is saved, just without an owner."""
    with client.session_transaction() as sess:
        sess["user"] = {"id": None, "name": "Test User",
                        "email": "test.user@gmail.com"}
    resp = client.post("/cards/add", data=dict(CARD_FORM))
    assert resp.get_json()["saved"] is True
    assert saved.owner_ids == [None]


# --- ownership cannot be forged from the browser ------------------------------

def test_a_forged_id_from_an_anonymous_visitor_is_ignored(client, saved):
    client.post("/cards/add", data=dict(CARD_FORM, added_by_user_id="7"))
    assert saved.owner_ids == [None], \
        "a posted id must never become the card's owner"


def test_a_signed_in_user_cannot_attribute_a_card_to_someone_else(user_client,
                                                                  saved):
    user_client.post("/cards/add", data=dict(CARD_FORM, added_by_user_id="99"))
    assert saved.owner_ids == [TEST_USER_ID]


def test_the_posted_field_does_not_reach_the_card_either(client, saved):
    client.post("/cards/add", data=dict(CARD_FORM, added_by_user_id="7"))
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
                        lambda topic: [dict(STORED_CARD)])
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
