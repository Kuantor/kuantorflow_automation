"""
Only an account may change the database (kuantorflow#125).

A visitor with no users-row id cannot add a card by any route — the review
popup, the automatic-add path, or Mykola saving one from chat. Reading stays
open: browsing, the deck, the quiz and word lookups are untouched.

The refusal is the route's, not the template's. Nothing is hidden or disabled
in the UI (that reading of the issue was settled deliberately), so every one of
these posts is exactly what a visitor's browser sends — and a hand-made post
gets the same answer.
"""

import json

import pytest
from flask import session

from conftest import TEST_USER_ID

CARD_FORM = {
    "word": "resilient",
    "pos": "adjective",
    "topic": "character",
    "explanation_en": "able to recover quickly",
}

# A sign-in whose users row could not be written (kuantorflow#148): looks
# signed in, has no id, and so may not write either.
NO_ROW_SESSION = {"id": None, "name": "Test User",
                  "email": "test.user@gmail.com"}


def _stub_lookup(app_module, monkeypatch, cards_automatically=True):
    monkeypatch.setattr(app_module, "lookup_word", lambda *a, **k: [
        {"word": "resilient", "pos": "adjective", "topic": "vocab"}])
    monkeypatch.setattr(app_module, "current_settings", lambda: dict(
        translator="google", explanatory_dictionary="oxford",
        cards_automatically=cards_automatically, show_ukrainian=True,
        show_russian=True, quiz_lang="ukr"))


# --- the review popup ---------------------------------------------------


def test_the_review_popup_is_refused(client, saved):
    resp = client.post("/cards/add", data=dict(CARD_FORM))
    assert resp.status_code == 403
    body = resp.get_json()
    assert body["ok"] is False
    assert body["sign_in_required"] is True
    assert body["error"] == ("Please sign in with Google to make any changes "
                             "of the database.")
    assert saved == [], "nothing may reach the database"


def test_a_signed_in_user_is_unaffected(user_client, saved):
    resp = user_client.post("/cards/add", data=dict(CARD_FORM))
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "saved": True}
    assert saved.owner_ids == [TEST_USER_ID]


def test_a_sign_in_with_no_users_row_is_refused(client, saved):
    """Fail closed: an unowned card cannot later be deleted by its author."""
    with client.session_transaction() as sess:
        sess["user"] = dict(NO_ROW_SESSION)
    assert client.post("/cards/add", data=dict(CARD_FORM)).status_code == 403
    assert saved == []


def test_the_refusal_comes_before_the_duplicate_check(client, app_module,
                                                      monkeypatch, saved):
    """A refused save must not be reported as 'already in the database' —
    the visitor would go looking for a card that was never written."""
    monkeypatch.setattr(app_module, "save_flashcard",
                        lambda entry, added_by_user_id=None: None)
    body = client.post("/cards/add", data=dict(CARD_FORM)).get_json()
    assert body.get("duplicate") is not True
    assert body["sign_in_required"] is True


def test_a_missing_word_is_still_a_400(client, saved):
    """The refusal does not swallow the older validation error."""
    assert client.post("/cards/add", data={"word": "  "}).status_code == 400


# --- the automatic-add path ---------------------------------------------


def test_automatic_add_saves_nothing(client, app_module, monkeypatch, saved):
    _stub_lookup(app_module, monkeypatch)
    resp = client.post("/", data={"action": "parse_word", "word": "resilient",
                                  "topic": "vocab"})
    assert resp.status_code == 200
    assert saved == []


def test_the_looked_up_cards_are_still_offered(client, app_module, monkeypatch,
                                               saved):
    """The lookup already happened, so its cards go to the review popup rather
    than being thrown away — signing in from the prompt leaves them there."""
    _stub_lookup(app_module, monkeypatch)
    body = client.post("/", data={"action": "parse_word", "word": "resilient",
                                  "topic": "vocab"}).get_data(as_text=True)
    assert "proposal-modal" in body
    assert "kfSignInRequired" in body, "and the prompt is raised on load"


def test_automatic_add_still_works_when_signed_in(user_client, app_module,
                                                  monkeypatch, saved):
    _stub_lookup(app_module, monkeypatch)
    user_client.post("/", data={"action": "parse_word", "word": "resilient",
                                "topic": "vocab"})
    assert saved.owner_ids == [TEST_USER_ID]


# --- Mykola saving a card from chat -------------------------------------


def test_mykola_cannot_save_for_an_anonymous_visitor(app_module, saved):
    """The agent turns an exception from its card_saver into an error it
    relays (ai_agent), so Mykola says why instead of claiming a saved card."""
    with app_module.app.test_request_context("/mykola/chat"):
        with pytest.raises(PermissionError) as excinfo:
            app_module._save_card_from_chat(
                {"word": "resilient", "pos": "adjective", "topic": "vocab"})
    assert "sign in with google" in str(excinfo.value).lower()
    assert saved == []


def test_mykola_still_saves_for_a_signed_in_user(app_module, saved):
    with app_module.app.test_request_context("/mykola/chat"):
        session["user"] = {"id": TEST_USER_ID, "email": "test.user@gmail.com"}
        app_module._save_card_from_chat(
            {"word": "resilient", "pos": "adjective", "topic": "vocab"})
    assert saved.owner_ids == [TEST_USER_ID]


# --- the funnel itself --------------------------------------------------


def test_the_save_funnel_refuses_even_without_a_route(app_module, saved):
    """_save_and_log is the single write path, and enforces #125 itself: a
    future save route that forgets to ask fails loudly instead of writing."""
    with app_module.app.test_request_context("/"):
        with pytest.raises(PermissionError):
            app_module._save_and_log({"word": "resilient"}, source="test")
    assert saved == []


def test_the_refusal_is_logged(client, saved, action_logs):
    client.post("/cards/add", data=dict(CARD_FORM))
    lines = (action_logs / "cards.log").read_text(encoding="utf-8").splitlines()
    denied = [line for line in lines if "ADD-DENIED" in line]
    assert len(denied) == 1
    assert "word=resilient" in denied[0]
    assert "reason=anonymous" in denied[0]
    assert "source='review popup'" in denied[0]


# --- reading is untouched -----------------------------------------------


@pytest.mark.parametrize("path", ["/", "/flashcards/character", "/deck/character",
                                  "/quiz/character"])
def test_reading_pages_stay_open(client, app_module, monkeypatch, path):
    monkeypatch.setattr(app_module, "get_flashcards_by_topic", lambda topic, owner_id=None: [{
        "id": 1, "word": "resilient", "pos": "adjective",
        "explanation_en": "able to recover quickly", "examples_en": [],
        "translation_ukr": "стійкий", "examples_ukr": [],
        "translation_rus": None, "examples_rus": [], "topic": "character",
        "added_by_user_id": 7}])
    assert client.get(path).status_code == 200


def test_looking_a_word_up_stays_open(client, app_module, monkeypatch, saved):
    """Lookup is a read path: it fetches and offers cards, it just cannot
    save them. Refusing it too would lock anonymous visitors out of the
    dictionary, which #125 does not ask for."""
    _stub_lookup(app_module, monkeypatch, cards_automatically=False)
    body = client.post("/", data={"action": "parse_word", "word": "resilient",
                                  "topic": "vocab"}).get_data(as_text=True)
    assert "resilient" in body
    assert saved == []


def test_the_prompt_offers_a_working_sign_in_link(client):
    """#125 asks for the link to be functional, not decorative."""
    body = client.get("/").get_data(as_text=True)
    assert 'id="signin-required-modal"' in body
    assert "/login/google" in body


def test_settings_are_unaffected(client):
    """Anonymous settings were already frozen by #102 with their own message;
    #125 must not change that answer."""
    resp = client.post("/settings", data=json.dumps({"quiz_lang": "russian"}),
                       content_type="application/json")
    assert resp.status_code == 403
