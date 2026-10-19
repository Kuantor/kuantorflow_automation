"""An exact Quiz answer also shows the card's other translations (kuantorflow#636).

*precious* answered *дорогий* used to be simply right, with nothing more on the
panel, though the card also lists *дорогоцінний, безцінний*. Every other kind
of right answer already says something: a green verdict lists the card's
translations (#612), the other aspect names its pair (#100), a synonym in the
English direction says "Also right" (#540). Now the exact match does too:

    Also right: дорогоцінний, безцінний

-- the card's other variants, in its order, without the one written (compared
as the Quiz compares: case and ё folded). Free: no model call.
"""

import re
import types

import pytest

import answercheck

CARDS = [
    {"id": 1, "word": "precious", "pos": "adjective", "topic": "t",
     "translation_ukr": "дорогоцінний, безцінний, дорогий",
     "translation_rus": "драгоценный, бесценный, дорогой"},
    {"id": 2, "word": "verdict", "pos": "noun", "topic": "t",
     "translation_ukr": "вирок", "translation_rus": "вердикт"},
    {"id": 3, "word": "trust", "pos": "verb", "topic": "t",
     "translation_ukr": "довіряти, покладатися",
     "translation_rus": "доверять, полагаться"},
    {"id": 4, "word": "heritage", "pos": "noun", "topic": "t",
     "translation_ukr": "спадщина, спадок", "translation_rus": "наследие"},
]


@pytest.fixture()
def quiz(user_client, monkeypatch):
    for name in ("utils.get_flashcards_by_topics", "utils.get_flashcards_by_topic"):
        monkeypatch.setattr(name, lambda *a, **k: [dict(c) for c in CARDS])
    state = types.SimpleNamespace(calls=[])

    def judge(language, items):
        state.calls.append([i["answer"] for i in items])
        return {n: ("green", "a synonym") for n, i in enumerate(items)
                if i["answer"] == "наслідок"}
    monkeypatch.setattr(answercheck, "judge", judge)
    monkeypatch.setattr("utils.claim_answer_check", lambda *a, **k: (True, None, 0))
    # #100's pairs, as the database would return them for this round.
    monkeypatch.setattr("utils.aspect_partners",
                        lambda lang, forms: {"довіряти": {"довірити"}} if lang == "ukr" else {})
    user_client.state = state
    return user_client


def _post(client, direction=None, **answers):
    url = "/quiz/t?lang=ukr" + (f"&dir={direction}" if direction else "")
    return client.post(url, data={f"answer_{k[1:]}": v for k, v in answers.items()}
                       ).get_data(as_text=True)


def _panel(body, word):
    for chunk in body.split('<div class="panel question ')[1:]:
        text = " ".join(re.sub(r"<[^>]+>", " ", chunk.partition('">')[2]
                               .split('<div class="panel')[0]).split())
        if word in text:
            return text
    raise AssertionError(f"no panel for {word}")


def test_an_exact_answer_shows_the_other_translations_in_the_cards_order(quiz):
    text = _panel(_post(quiz, a1="дорогий"), "precious")

    assert "Also right: дорогоцінний, безцінний" in text


def test_the_variant_written_is_left_out_whatever_its_case(quiz):
    text = _panel(_post(quiz, a1="Безцінний "), "precious")

    assert "Also right: дорогоцінний, дорогий" in text
    assert "Also right: дорогоцінний, безцінний" not in text


def test_a_card_with_one_translation_shows_no_line(quiz):
    text = _panel(_post(quiz, a2="вирок"), "verdict")

    assert "Also right" not in text


def test_the_other_aspect_keeps_its_own_line(quiz):
    text = _panel(_post(quiz, a3="довірити"), "trust")

    assert "other aspect of довіряти" in text
    assert "Also right" not in text


def test_a_green_answer_keeps_its_own_line(quiz):
    text = _panel(_post(quiz, a4="наслідок"), "heritage")

    assert "Accepted" in text and "Also right" not in text


def test_a_wrong_answer_shows_the_correct_answer_only(quiz):
    text = _panel(_post(quiz, a1="важний"), "precious")

    assert "Correct answer: дорогоцінний, безцінний, дорогий" in text
    assert "Also right" not in text


def test_the_english_direction_is_unchanged(quiz):
    # One expected English word per card: nothing else to list.
    text = _panel(_post(quiz, direction="to-en", a1="precious"), "дорогоцінний")

    assert "Also right" not in text


def test_an_exact_answer_costs_no_model_call(quiz):
    _post(quiz, a1="дорогий")

    assert quiz.state.calls == []
