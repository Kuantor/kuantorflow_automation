"""
Blocking an account (kuantorflow#126).

A blocked user keeps reading — flashcards, the deck, the quiz, word lookups
and their own settings — but cannot change the database or talk to Mykola, and
is shown the admin's address so they can ask for access back.

The block lives on the users row, read live on each request rather than
stamped into the session: a session cookie lasts 30 days, and a block has to
take effect on the blocked person's next request, not their next sign-in.

`block_state` (autouse, conftest) is how a test blocks the signed-in account;
without it every signed-in request here would query a real database.
"""

import json

import pytest
from flask import session

import utils
from conftest import TEST_USER_ID, TEST_USER_EMAIL

CARD_FORM = {
    "word": "resilient",
    "pos": "adjective",
    "topic": "character",
    "explanation_en": "able to recover quickly",
}

STORED_CARD = {
    "id": 1, "word": "resilient", "pos": "adjective",
    "explanation_en": "able to recover quickly", "examples_en": [],
    "translation_ukr": "стійкий", "examples_ukr": [],
    "translation_rus": None, "examples_rus": [], "topic": "character",
    "added_by_user_id": TEST_USER_ID,
}


@pytest.fixture()
def blocked_client(user_client, block_state):
    """A signed-in client whose account has been blocked."""
    block_state.block()
    return user_client


# --- writing is refused -------------------------------------------------


def test_adding_a_card_is_refused(blocked_client, saved):
    resp = blocked_client.post("/cards/add", data=dict(CARD_FORM))
    assert resp.status_code == 403
    assert saved == []


def test_the_refusal_says_it_is_a_block_not_a_sign_in(blocked_client, saved):
    """A blocked user is signed in already — telling them to sign in would
    send them round a loop that changes nothing."""
    body = blocked_client.post("/cards/add", data=dict(CARD_FORM)).get_json()
    assert "blocked" in body["error"].lower()
    assert "sign in" not in body["error"].lower()


def test_the_refusal_names_an_admin_to_write_to(blocked_client, app_module,
                                                monkeypatch, saved):
    monkeypatch.setattr(app_module, "ADMIN_EMAILS", {"admin@example.com"})
    body = blocked_client.post("/cards/add", data=dict(CARD_FORM)).get_json()
    assert "admin@example.com" in body["error"]


def test_with_no_admin_configured_the_message_still_makes_sense(
        blocked_client, app_module, monkeypatch, saved):
    """ADMIN_EMAILS may be empty (#158) — then there is nobody to name, and
    the sentence has to stop rather than trail off into an empty address."""
    monkeypatch.setattr(app_module, "ADMIN_EMAILS", set())
    body = blocked_client.post("/cards/add", data=dict(CARD_FORM)).get_json()
    assert "blocked" in body["error"].lower()
    assert "@" not in body["error"]


def test_the_automatic_add_path_is_refused(blocked_client, app_module,
                                           monkeypatch, saved):
    monkeypatch.setattr(app_module, "lookup_word", lambda *a, **k: [
        {"word": "resilient", "pos": "adjective", "topic": "vocab"}])
    monkeypatch.setattr(app_module, "current_settings", lambda: dict(
        translator="google", explanatory_dictionary="oxford",
        cards_automatically=True, show_ukrainian=True, show_russian=True,
        quiz_lang="ukr", restart_chat_interval=2))
    body = blocked_client.post("/", data={"action": "parse_word",
                                          "word": "resilient",
                                          "topic": "vocab"}).get_data(as_text=True)
    assert saved == []
    # The dialog is raised with the block wording, not #125's sign-in prompt.
    # Matched on the literal-argument call: the popup's own handler passes a
    # variable (kfSignInRequired(err.message)) and would match too.
    raised = body[body.index('kfSignInRequired("'):]
    raised = raised[:raised.index(");")]
    assert "blocked" in raised.lower()
    assert "sign in" not in raised.lower()


def test_deleting_a_card_is_refused(blocked_client, app_module, monkeypatch):
    """Their own card, which they could delete before the block (#162)."""
    deleted = []
    monkeypatch.setattr(app_module, "delete_flashcard",
                        lambda *a, **k: deleted.append(a) or ("resilient", "deleted"))
    resp = blocked_client.post("/flashcards/character/delete/1",
                               follow_redirects=True)
    assert resp.status_code == 200
    assert deleted == [], "the route must not reach the database at all"
    assert "blocked" in resp.get_data(as_text=True).lower()


def test_the_delete_cross_is_greyed_with_the_reason(blocked_client, app_module,
                                                    monkeypatch):
    """Read off the cross itself, not the page: a blocked visitor's page also
    carries the Settings notice, so `"blocked" in body` would prove nothing."""
    monkeypatch.setattr(app_module, "ADMIN_EMAILS", {"admin@example.com"})
    monkeypatch.setattr(app_module, "get_flashcards_by_topic",
                        lambda topic: [dict(STORED_CARD)])
    body = blocked_client.get("/flashcards/character").get_data(as_text=True)
    cross = body[body.index('class="card-delete"'):]
    cross = cross[:cross.index(">")]
    assert 'aria-disabled="true"' in cross
    assert "blocked" in cross.lower() and "admin@example.com" in cross


def test_a_blocked_admin_cannot_delete_either(blocked_client, app_module,
                                              monkeypatch):
    """Admin-ness is checked after the block, so an admin who blocked their
    own account is taken at their word. #165 stops them deleting that account,
    so this cannot become permanent."""
    monkeypatch.setattr(app_module, "ADMIN_EMAILS", {TEST_USER_EMAIL})
    with blocked_client.session_transaction() as sess:
        sess["user"]["email_verified"] = True
    monkeypatch.setattr(app_module, "get_flashcards_by_topic",
                        lambda topic: [dict(STORED_CARD, added_by_user_id=99)])
    with app_module.app.test_request_context("/"):
        session["user"] = {"id": TEST_USER_ID, "email": TEST_USER_EMAIL,
                           "email_verified": True}
        assert app_module.is_admin() is True
        assert app_module.can_delete_card(dict(STORED_CARD)) is False


# --- Mykola is not available to them ------------------------------------


def test_the_widget_is_not_rendered(blocked_client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    body = blocked_client.get("/").get_data(as_text=True)
    assert "mykola-panel" not in body


def test_the_widget_is_rendered_for_everyone_else(user_client, app_module,
                                                  monkeypatch):
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    body = user_client.get("/").get_data(as_text=True)
    assert "mykola-panel" in body


def test_a_hand_made_chat_request_is_refused(blocked_client, app_module,
                                             monkeypatch):
    """Hiding the widget is presentation; this is the part that holds."""
    called = []
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    monkeypatch.setattr(app_module, "_agent_answer",
                        lambda *a, **k: called.append(a) or {"response": "hi"})
    resp = blocked_client.post("/mykola/chat", json={"question": "hello"})
    assert resp.status_code == 403
    assert "blocked" in resp.get_json()["error"].lower()
    assert called == [], "the model must not be called for a blocked account"


def test_the_recap_endpoint_stays_quiet(blocked_client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    assert blocked_client.post("/mykola/recap").get_json() == {"recap": None}


def test_the_restart_check_answers_no(blocked_client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    body = blocked_client.post("/mykola/restart-check", json={}).get_json()
    assert body["restart"] is False
    assert body["reason"] == "blocked"


def test_mykola_cannot_save_a_card_for_them(app_module, saved, block_state):
    block_state.block()
    with app_module.app.test_request_context("/mykola/chat"):
        session["user"] = {"id": TEST_USER_ID, "email": TEST_USER_EMAIL}
        with pytest.raises(PermissionError) as excinfo:
            app_module._save_card_from_chat({"word": "resilient"})
    assert "blocked" in str(excinfo.value).lower()
    assert saved == []


# --- reading is untouched -----------------------------------------------


@pytest.mark.parametrize("path", ["/", "/flashcards/character",
                                  "/deck/character", "/quiz/character"])
def test_reading_pages_stay_open(blocked_client, app_module, monkeypatch, path):
    monkeypatch.setattr(app_module, "get_flashcards_by_topic",
                        lambda topic: [dict(STORED_CARD)])
    assert blocked_client.get(path).status_code == 200


def test_looking_a_word_up_still_works(blocked_client, app_module, monkeypatch,
                                       saved):
    monkeypatch.setattr(app_module, "lookup_word", lambda *a, **k: [
        {"word": "resilient", "pos": "adjective", "topic": "vocab",
         "explanation_en": "able to recover quickly"}])
    body = blocked_client.post("/", data={"action": "parse_word",
                                          "word": "resilient",
                                          "topic": "vocab"}).get_data(as_text=True)
    assert "able to recover quickly" in body
    assert saved == [], "offered for review, but not saved"


def test_their_own_settings_still_save(blocked_client):
    """The block is about shared things; a personal preference is not one."""
    resp = blocked_client.post("/settings",
                               data=json.dumps({"quiz_lang": "russian"}),
                               content_type="application/json")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_the_settings_popup_tells_them_how_to_ask(blocked_client, app_module,
                                                  monkeypatch):
    monkeypatch.setattr(app_module, "ADMIN_EMAILS", {"admin@example.com"})
    body = blocked_client.get("/").get_data(as_text=True)
    assert "settings-blocked" in body
    assert "admin@example.com" in body


# --- unblocking restores everything -------------------------------------


def test_clearing_the_block_restores_writing(user_client, block_state, saved):
    block_state.block()
    assert user_client.post("/cards/add", data=dict(CARD_FORM)).status_code == 403

    block_state.value = None            # as set_user_blocked(..., False) does
    resp = user_client.post("/cards/add", data=dict(CARD_FORM))
    assert resp.status_code == 200
    assert saved.owner_ids == [TEST_USER_ID]


# --- the block is read live, not from the session -----------------------


def test_the_block_is_read_once_per_request(user_client, app_module,
                                            monkeypatch):
    """Cached in `g`: the widget, the pages and the save routes all ask, and
    one page must not become one query per question."""
    calls = []
    monkeypatch.setattr(app_module, "get_user_block",
                        lambda user_id: calls.append(user_id) or None)
    user_client.get("/")
    assert len(calls) == 1


def test_an_anonymous_visitor_is_never_looked_up(client, app_module,
                                                 monkeypatch):
    """There is no account to block, so there is nothing to ask the database."""
    calls = []
    monkeypatch.setattr(app_module, "get_user_block",
                        lambda user_id: calls.append(user_id) or None)
    client.get("/")
    assert calls == [] or calls == [None]


def test_a_dead_database_does_not_lock_the_site(user_client, app_module,
                                                monkeypatch, saved):
    """Same tolerance as the rest of the app: a failed lookup means no block
    is visible, rather than every signed-in visitor being treated as blocked."""
    def boom(user_id):
        raise RuntimeError("database is down")
    monkeypatch.setattr(app_module, "get_user_block", boom)
    assert user_client.post("/cards/add", data=dict(CARD_FORM)).status_code == 200


# --- the stored side: utils.set_user_blocked ----------------------------


class FakeCursor:
    def __init__(self, row):
        self.row = row
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((" ".join(query.split()), params))

    def fetchone(self):
        return self.row

    def close(self):
        pass


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def cursor(self, **kwargs):
        return self._cursor

    def commit(self):
        self.committed = True

    def close(self):
        pass


def _fake_db(monkeypatch, row):
    cursor = FakeCursor(row)
    monkeypatch.setattr(utils, "get_db_connection", lambda: FakeConn(cursor))
    return cursor


def test_blocking_sets_the_timestamp_and_reason(monkeypatch):
    cursor = _fake_db(monkeypatch, (7, None))
    assert utils.set_user_blocked("someone@gmail.com", True, "spam") == (7, False)
    update = next(q for q, _ in cursor.queries if q.startswith("UPDATE"))
    assert "blocked_at = NOW()" in update
    assert "blocked_reason = %s" in update


def test_unblocking_clears_the_reason_too(monkeypatch):
    """A note about a block that is over would read as a live one."""
    cursor = _fake_db(monkeypatch, (7, "2026-08-02 10:00:00"))
    assert utils.set_user_blocked("someone@gmail.com", False) == (7, True)
    update = next(q for q, _ in cursor.queries if q.startswith("UPDATE"))
    assert "blocked_at = NULL" in update
    assert "blocked_reason = NULL" in update


def test_an_unknown_email_changes_nothing(monkeypatch):
    """A typo must report a miss, not report success on no rows."""
    cursor = _fake_db(monkeypatch, None)
    assert utils.set_user_blocked("nobody@gmail.com", True) is None
    assert not any(q.startswith("UPDATE") for q, _ in cursor.queries)


def test_the_email_is_matched_exactly(monkeypatch):
    """Never a LIKE or a prefix: one block must not catch a bystander."""
    cursor = _fake_db(monkeypatch, (7, None))
    utils.set_user_blocked("someone@gmail.com", True)
    select = next(q for q, _ in cursor.queries if q.startswith("SELECT"))
    assert "LOWER(email) = LOWER(%s)" in select
    assert "LIKE" not in select.upper()


def test_blocking_is_logged(monkeypatch, action_logs):
    _fake_db(monkeypatch, (7, None))
    utils.set_user_blocked("someone@gmail.com", True, "spam in chat")
    lines = (action_logs / "cards.log").read_text(encoding="utf-8")
    assert "USER-BLOCK" in lines
    assert "someone@gmail.com" in lines
    assert "spam in chat" in lines


def test_unblocking_is_logged(monkeypatch, action_logs):
    _fake_db(monkeypatch, (7, "2026-08-02 10:00:00"))
    utils.set_user_blocked("someone@gmail.com", False)
    assert "USER-UNBLOCK" in (action_logs / "cards.log").read_text(encoding="utf-8")


def test_unblocking_an_unblocked_account_logs_nothing(monkeypatch, action_logs):
    """The log counts blocks that were lifted; a no-op is not one of them."""
    _fake_db(monkeypatch, (7, None))
    utils.set_user_blocked("someone@gmail.com", False)
    log = action_logs / "cards.log"
    assert not log.exists() or "USER-UNBLOCK" not in log.read_text(encoding="utf-8")


def test_reblocking_is_logged_because_the_reason_may_change(monkeypatch,
                                                            action_logs):
    _fake_db(monkeypatch, (7, "2026-08-02 10:00:00"))
    utils.set_user_blocked("someone@gmail.com", True, "a new reason")
    log = (action_logs / "cards.log").read_text(encoding="utf-8")
    assert "USER-BLOCK" in log and "a new reason" in log


def test_get_user_block_reads_none_for_an_unblocked_account(monkeypatch):
    _fake_db(monkeypatch, (None, None))
    assert utils.get_user_block(7) is None


def test_get_user_block_returns_when_and_why(monkeypatch):
    _fake_db(monkeypatch, ("2026-08-02 10:00:00", "spam in chat"))
    assert utils.get_user_block(7) == ("2026-08-02 10:00:00", "spam in chat")


def test_get_user_block_never_asks_about_nobody(monkeypatch):
    def boom():
        raise AssertionError("an anonymous visitor must not reach the database")
    monkeypatch.setattr(utils, "get_db_connection", boom)
    assert utils.get_user_block(None) is None
