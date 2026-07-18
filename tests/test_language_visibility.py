"""Language-visibility switches (kuantorflow#46/#79/#111).

The Settings popup's 'Show Ukrainian/Russian translation' checkboxes hide a
language everywhere — flashcards, the lookup review popup, the quiz, and
Mykola's answers — while the underlying data stays stored.
"""

import re


CARD = {
    "id": 7, "word": "resilient", "pos": "adjective", "topic": "vocab",
    "explanation_en": "able to recover quickly",
    "translation_ukr": "стійкий", "translation_rus": "упругий",
    "examples_en": [], "examples_ukr": ["Він стійкий."], "examples_rus": ["Он упругий."],
}


def _cards(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "get_flashcards_by_topic",
                        lambda topic: [dict(CARD)])


# --- Settings popup (#111) ----------------------------------------------------

def test_popup_has_visibility_checkboxes_checked_by_default(client):
    body = client.get("/").get_data(as_text=True)
    assert re.search(r'name="show_ukrainian"\s+checked', body)
    assert re.search(r'name="show_russian"\s+checked', body)


def test_visibility_round_trip_through_settings_endpoint(user_client):
    r = user_client.post("/settings", json={"show_russian": False})
    stored = r.get_json()["settings"]
    assert stored["show_russian"] is False
    assert stored["show_ukrainian"] is True
    body = user_client.get("/").get_data(as_text=True)
    assert not re.search(r'name="show_russian"\s+checked', body)
    assert re.search(r'name="show_ukrainian"\s+checked', body)


# --- Flashcards page (#46/#79) ------------------------------------------------

def test_flashcards_show_both_languages_by_default(client, app_module, monkeypatch):
    _cards(app_module, monkeypatch)
    body = client.get("/flashcards/vocab").get_data(as_text=True)
    assert "Ukrainian" in body and "стійкий" in body
    assert "Russian" in body and "упругий" in body


def test_flashcards_hide_disabled_language(user_client, app_module, monkeypatch):
    _cards(app_module, monkeypatch)
    user_client.post("/settings", json={"show_russian": False})
    body = user_client.get("/flashcards/vocab").get_data(as_text=True)
    assert "Ukrainian" in body and "стійкий" in body
    assert "упругий" not in body and "Он упругий." not in body
    assert ">Russian<" not in body
    assert "Take quiz" in body, "one language still visible — quiz stays"


def test_flashcards_hide_quiz_link_when_no_language_visible(user_client, app_module, monkeypatch):
    _cards(app_module, monkeypatch)
    user_client.post("/settings", json={"show_russian": False, "show_ukrainian": False})
    body = user_client.get("/flashcards/vocab").get_data(as_text=True)
    assert "Take quiz" not in body
    assert "стійкий" not in body and "упругий" not in body


# --- Lookup review popup (#46/#79) --------------------------------------------

def test_review_popup_carries_hidden_language_as_hidden_input(user_client, app_module, monkeypatch):
    monkeypatch.setattr(
        app_module, "lookup_word",
        lambda word, topic=None, **providers: [
            {"word": word, "pos": "noun", "topic": topic,
             "translation_ukr": "дім", "translation_rus": "дом"}],
    )
    user_client.post("/settings", json={"show_russian": False})
    body = user_client.post("/", data={"action": "parse_word", "word": "house"})\
        .get_data(as_text=True)
    # the Settings popup on every page says "Show Russian translation", so
    # target the review card's exact label markup
    assert "<label>Ukrainian translation</label>" in body   # editable stays
    assert "<label>Russian translation</label>" not in body  # no editable field
    # the value still travels, so the saved card stays complete
    assert re.search(
        r'<input type="hidden" name="translation_rus" value="дом">', body)


# --- Quiz (#46/#79) -----------------------------------------------------------

def test_quiz_falls_back_to_visible_language(user_client, app_module, monkeypatch):
    _cards(app_module, monkeypatch)
    user_client.post("/settings", json={"show_russian": False})
    body = user_client.get("/quiz/vocab").get_data(as_text=True)   # default is rus
    assert "Type the Ukrainian translation" in body
    # the language switch must not offer Russian (the word still appears in
    # the Settings popup rendered on every page, so check the switch markup)
    assert ">Russian</a>" not in body and ">Russian</span>" not in body


def test_quiz_explains_itself_when_all_languages_hidden(user_client, app_module, monkeypatch):
    _cards(app_module, monkeypatch)
    user_client.post("/settings", json={"show_russian": False, "show_ukrainian": False})
    body = user_client.get("/quiz/vocab").get_data(as_text=True)
    assert "hidden in Settings" in body
    assert "Check answers" not in body


# --- Mykola integration (#46/#79) ---------------------------------------------

class FakeAgent:
    def __init__(self):
        self.calls = []

    def answer(self, question, history=None, on_text=None, user_name=None,
               hidden_languages=None):
        self.calls.append({"user_name": user_name,
                           "hidden_languages": hidden_languages})
        return {"response": "ok", "sources": [], "history": []}


def _chat(client, app_module, monkeypatch):
    agent = FakeAgent()
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    monkeypatch.setattr(app_module, "get_mykola", lambda: agent)
    r = client.post("/mykola/chat", json={"question": "hello"})
    assert r.status_code == 200, r.get_data(as_text=True)
    return agent.calls[-1]

def test_agent_receives_hidden_languages(user_client, app_module, monkeypatch):
    user_client.post("/settings", json={"show_russian": False})
    call = _chat(user_client, app_module, monkeypatch)
    assert call["hidden_languages"] == ["Russian"]


def test_agent_gets_no_hidden_languages_by_default(client, app_module, monkeypatch):
    call = _chat(client, app_module, monkeypatch)
    assert call["hidden_languages"] is None
