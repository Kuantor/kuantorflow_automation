"""
How many words a round asks, and which ones (kuantorflow#250).

A quiz over the whole curriculum was ninety-three typed answers, which is not a
round so much as an afternoon. Twenty is the default and the picker offers a
box; this file is the rule and the draw.

Split out of test_topic_picker.py (#69). Two things here would be expensive to
get wrong, and both have their own test: the draw is **uniform over every card
in the selection** rather than the top of the list, and grading marks the words
that were **asked** rather than a fresh sample.
"""

import re

import pytest

import games


# --- how many words a round asks (kuantorflow#250) ---------------------


MANY = [{"id": i, "word": f"word{i}", "pos": "noun", "topic": "Work",
         "translation_ukr": f"слово{i}", "translation_rus": f"слово{i}"}
        for i in range(1, 61)]


@pytest.fixture()
def big_deck(stub_deck):
    """Sixty cards in one topic — more than a round asks for."""
    return stub_deck(cards=MANY)


@pytest.fixture()
def deck(stub_deck):
    """A small deck, for the test that reads the box off the picker rather than
    counting questions in a round."""
    return stub_deck(topics=[("Work", 2), ("Travel", 1)])


def _asked(body):
    """The answer_<id> fields a rendered round is asking about."""
    return re.findall(r'name="answer_(\d+)"', body)


def test_a_round_asks_the_default_number_of_words(client, big_deck):
    """Sixty cards is not a round, it is an afternoon.

    Read off `games.QUIZ_WORDS_DEFAULT` rather than written down, so tuning the
    default is one edit in the app and none here — the number itself is a
    product judgement that will move again."""
    body = client.get("/quiz?topic=Work").get_data(as_text=True)
    default = games.QUIZ_WORDS_DEFAULT
    assert len(_asked(body)) == default
    assert f"({default} questions)" in body


def test_the_word_count_can_be_asked_for_in_the_url(client, big_deck):
    body = client.get("/quiz?topic=Work&words=5").get_data(as_text=True)
    assert len(_asked(body)) == 5


def test_asking_for_more_words_than_exist_plays_what_there_is(client, big_deck):
    body = client.get("/quiz?topic=Work&words=200").get_data(as_text=True)
    assert len(_asked(body)) == 60


@pytest.mark.parametrize("raw,expected", [
    ("0", games.QUIZ_WORDS_MIN), ("-4", games.QUIZ_WORDS_MIN),
    ("9999", 60),                       # clamped to the deck, not to the ceiling
    ("abc", games.QUIZ_WORDS_DEFAULT), ("", games.QUIZ_WORDS_DEFAULT)])
def test_an_unusable_word_count_is_clamped_or_ignored(client, big_deck,
                                                      raw, expected):
    """It arrives from a URL anybody can edit, and a round is not the place to
    argue about it."""
    body = client.get(f"/quiz?topic=Work&words={raw}").get_data(as_text=True)
    assert len(_asked(body)) == expected


def test_the_words_are_drawn_at_random_rather_than_off_the_top(client, big_deck):
    """Uniformly over every card in the selection — so two rounds differ, and
    across several the draw reaches well past the first twenty."""
    draws = [set(_asked(client.get("/quiz?topic=Work&words=20")
                        .get_data(as_text=True))) for _ in range(6)]
    assert all(len(d) == 20 for d in draws)
    assert len({frozenset(d) for d in draws}) > 1, "every round drew the same words"
    assert len(set().union(*draws)) > 30, "the draw never left the top of the list"


def test_grading_marks_the_words_that_were_asked_not_a_fresh_draw(
        client, big_deck):
    """The round is a random sample, so re-drawing here would mark answers
    against words the learner never saw."""
    asked = _asked(client.get("/quiz?topic=Work&words=8").get_data(as_text=True))
    answers = {f"answer_{i}": f"слово{i}" for i in asked}
    body = client.post("/quiz?topic=Work&words=8&lang=ukr",
                       data=answers).get_data(as_text=True)
    assert "Score: 8 / 8" in body


def test_the_results_are_numbered_in_the_order_the_questions_were_asked(
        client, big_deck):
    """A learner reading '3. wrong' has to find the third question they
    answered, not the third alphabetically."""
    asked = _asked(client.get("/quiz?topic=Work&words=6").get_data(as_text=True))
    answers = {f"answer_{i}": "" for i in asked}
    body = client.post("/quiz?topic=Work&words=6&lang=ukr",
                       data=answers).get_data(as_text=True)
    order = [body.index(f"word{i}<") if f"word{i}<" in body else -1 for i in asked]
    assert order == sorted(order), "the results were re-ordered"


def test_the_word_count_is_remembered_like_the_topics(client, deck):
    client.get("/quiz?topic=Work&words=7")
    body = client.get("/quiz").get_data(as_text=True)
    assert 'value="7"' in body
