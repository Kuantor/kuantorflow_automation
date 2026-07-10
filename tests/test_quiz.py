"""The quiz: grading tolerance, per-language filtering, POS display."""

import pytest

CARDS = [
    {"id": 1, "word": "house", "pos": "noun", "translation_rus": "дом, здание",
     "translation_ukr": "дім, будинок", "topic": "basics"},
    {"id": 2, "word": "hedgehog", "pos": "noun", "translation_rus": "ёж",
     "translation_ukr": None, "topic": "basics"},   # not quizzable in ukr
    {"id": 3, "word": "cat", "pos": "noun", "translation_rus": None,
     "translation_ukr": "кіт", "topic": "basics"},  # not quizzable in rus
]


@pytest.fixture()
def quiz_client(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "get_flashcards_by_topic",
                        lambda topic: [dict(c) for c in CARDS])
    return client


def test_default_language_is_russian(quiz_client):
    body = quiz_client.get("/quiz/basics").get_data(as_text=True)
    assert "Type the Russian translation" in body
    assert "house" in body and "hedgehog" in body and "cat" not in body


def test_ukrainian_mode_filters_cards(quiz_client):
    body = quiz_client.get("/quiz/basics?lang=ukr").get_data(as_text=True)
    assert "Type the Ukrainian translation" in body
    assert "house" in body and "cat" in body and "hedgehog" not in body
    assert 'lang="uk"' in body


def test_unknown_language_falls_back_to_russian(quiz_client):
    body = quiz_client.get("/quiz/basics?lang=hacker").get_data(as_text=True)
    assert "Type the Russian translation" in body


def test_grading_accepts_any_variant_case_insensitive(quiz_client):
    r = quiz_client.post("/quiz/basics",
                         data={"answer_1": "ЗДАНИЕ ", "answer_2": "еж"})
    assert "Score: 2 / 2" in r.get_data(as_text=True)  # ё/е tolerated too


def test_grading_in_ukrainian(quiz_client):
    r = quiz_client.post("/quiz/basics?lang=ukr",
                         data={"answer_1": "Будинок", "answer_3": "кіт"})
    assert "Score: 2 / 2" in r.get_data(as_text=True)


def test_russian_answer_rejected_in_ukrainian_mode(quiz_client):
    r = quiz_client.post("/quiz/basics?lang=ukr",
                         data={"answer_1": "дом", "answer_3": "кіт"})
    assert "Score: 1 / 2" in r.get_data(as_text=True)


def test_wrong_answers_reveal_expected(quiz_client):
    r = quiz_client.post("/quiz/basics", data={"answer_1": "кошка", "answer_2": ""})
    body = r.get_data(as_text=True)
    assert "Score: 0 / 2" in body
    assert "дом, здание" in body


def test_empty_topic_message(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "get_flashcards_by_topic", lambda topic: [])
    body = client.get("/quiz/empty").get_data(as_text=True)
    assert "nothing to quiz on" in body
