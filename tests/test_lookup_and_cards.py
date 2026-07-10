"""Word lookup (review popup), card adding, MHT upload, card deletion."""

import io


def _stub_lookup(app_module, monkeypatch):
    monkeypatch.setattr(
        app_module,
        "parse_google_word",
        lambda word, topic=None: [
            {"word": word, "pos": "adjective", "translation_ukr": "стійкий",
             "explanation_en": "able to recover quickly", "topic": topic},
            {"word": word, "pos": "noun", "translation_ukr": "стійкість",
             "topic": topic},
        ],
    )


def test_lookup_shows_review_popup_without_saving(client, app_module, monkeypatch, saved):
    _stub_lookup(app_module, monkeypatch)
    r = client.post("/", data={"action": "parse_word", "word": "resilient",
                               "topic": "character"})
    body = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "Do you want to add the card(s) to the database?" in body
    assert saved == [], "lookup must not save anything before review"
    assert body.count('class="proposal-card"') == 2
    assert 'name="translation_ukr" value="стійкий"' in body
    assert "able to recover quickly" in body
    assert 'name="topic" value="character"' in body
    assert ">Add</button>" in body and "proposal-remove" in body


def test_add_card_saves_edited_values(client, saved):
    r = client.post("/cards/add", data={
        "word": "resilient", "pos": "adjective", "topic": "character",
        "explanation_en": "my edited explanation",
        "translation_ukr": "стійкий", "translation_rus": "",
    })
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert len(saved) == 1
    assert saved[0]["explanation_en"] == "my edited explanation"
    assert saved[0]["translation_rus"] is None, "empty field must become NULL"
    assert saved[0]["topic"] == "character"


def test_add_card_requires_word(client, saved):
    r = client.post("/cards/add", data={"word": "   "})
    assert r.status_code == 400
    assert saved == []


def test_empty_word_shows_error_and_no_popup(client, saved):
    r = client.post("/", data={"action": "parse_word", "word": ""})
    body = r.get_data(as_text=True)
    assert "Please enter a word." in body
    assert "proposal-card" not in body


def test_mht_upload_saves_directly(client, saved):
    mht = b"""From: <saved>
MIME-Version: 1.0
Content-Type: multipart/related; boundary="----=_B"

------=_B
Content-Type: text/html; charset="utf-8"
Content-Transfer-Encoding: 8bit

<html><body><p>ubiquitous - present everywhere</p></body></html>
------=_B--
"""
    r = client.post(
        "/",
        data={"action": "upload_mht", "topic": "vocab",
              "mht_file": (io.BytesIO(mht), "notes.mht")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    body = r.get_data(as_text=True)
    assert "Saved to Database" in body and "1 flashcard(s)" in body
    assert len(saved) == 1 and saved[0]["word"] == "ubiquitous"


CARD = {"id": 7, "word": "resilient", "pos": "adjective", "topic": "vocab",
        "examples_en": [], "examples_ukr": [], "examples_rus": []}


def test_flashcards_page_has_delete_cross_and_modal(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "get_flashcards_by_topic",
                        lambda topic: [dict(CARD)])
    body = client.get("/flashcards/vocab").get_data(as_text=True)
    assert 'class="card-delete"' in body
    assert 'data-word="resilient (adjective)"' in body
    assert 'data-url="/flashcards/vocab/delete/7"' in body
    assert 'id="delete-modal"' in body
    assert "Do you really want to delete the card" in body


def test_delete_card_flow(client, app_module, monkeypatch):
    deleted = []
    monkeypatch.setattr(app_module, "delete_flashcard",
                        lambda card_id: deleted.append(card_id) or "resilient")
    r = client.post("/flashcards/vocab/delete/7", follow_redirects=True)
    body = r.get_data(as_text=True)
    assert deleted == [7]
    assert "Deleted card" in body and "resilient" in body


def test_delete_missing_card_is_friendly(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "delete_flashcard", lambda card_id: None)
    body = client.post("/flashcards/vocab/delete/999",
                       follow_redirects=True).get_data(as_text=True)
    assert "Card not found" in body


def test_delete_rejects_get(client):
    assert client.get("/flashcards/vocab/delete/7").status_code == 405
