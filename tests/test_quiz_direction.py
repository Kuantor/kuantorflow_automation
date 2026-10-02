"""The Quiz in the other direction: see the translation, type the English word
(kuantorflow#540).

The Quiz always showed the English word and took its translation. This adds a
direction switch beside the language switch: the translation shown, with the
part of speech and the first letter as a hint, and the English word typed --
the productive direction, which no other activity asks for.

What is pinned here:

* **the default is unchanged**, and `?dir=to-en` turns the questions round;
* **a synonym from the selection counts** (*vidstavka* is both *resignation*
  and *dismissal*), one from outside it does not, and the result says which
  word the card was;
* **typing is forgiven** as every English answer is (#267);
* **the direction is remembered for the visit** and carried by both switches,
  the form and *Try again* -- and a review keeps its flag beside it;
* the round's log line says which way it was asked.
"""

import re

import pytest

import rounds

CARDS = [
    {"id": 1, "word": "resignation", "pos": "noun", "topic": "Work",
     "translation_ukr": "відставка, звільнення", "translation_rus": "отставка"},
    {"id": 2, "word": "dismissal", "pos": "noun", "topic": "Work",
     "translation_ukr": "звільнення", "translation_rus": "увольнение"},
    {"id": 3, "word": "well-being", "pos": "noun", "topic": "Work",
     "translation_ukr": "добробут", "translation_rus": "благополучие"},
    {"id": 4, "word": "commute", "pos": "verb", "topic": "Travel",
     "translation_ukr": "їздити на роботу", "translation_rus": "ездить"},
]
OUTSIDE = {"id": 9, "word": "sacking", "pos": "noun", "topic": "Elsewhere",
           "translation_ukr": "звільнення", "translation_rus": "увольнение"}


@pytest.fixture()
def deck(stub_deck):
    return stub_deck(cards=CARDS)


def _text(response):
    return " ".join(response.get_data(as_text=True).split())


def _post(client, answers, direction="to-en", url="/quiz/Work"):
    return client.post(f"{url}?lang=ukr&dir={direction}",
                       data={f"answer_{cid}": given for cid, given in answers.items()})


# --- the questions ----------------------------------------------------------------

def test_the_default_is_the_quiz_as_it_was(client, deck):
    text = _text(client.get("/quiz/Work?lang=ukr"))

    assert "Type the Ukrainian translation for each English word" in text
    assert re.search(r'class="quiz-pair".*?<span class="quiz-side">English</span>'
                     r'.*?class="quiz-swap".*?<details class="quiz-lang">', text),         "English on the left: you see English, you type Ukrainian"
    assert 'lang="uk">' in text


def test_to_english_shows_the_translation_with_a_hint(client, deck):
    text = _text(client.get("/quiz/Work?lang=ukr&dir=to-en"))

    assert "Type the English word for each Ukrainian translation" in text
    assert re.search(r'class="quiz-pair".*?<details class="quiz-lang">.*?'
                     r'class="quiz-swap".*?<span class="quiz-side">English</span>', text),         "the language on the left: you see Ukrainian, you type English"
    assert "відставка, звільнення</span>" in text
    assert '<span class="quiz-hint">(noun, r&hellip;)</span>' in text
    assert re.search(r'name="answer_1"[^>]*lang="en"', text)
    assert "resignation" not in re.sub(r"<script.*?</script>", "", text, flags=re.S) \
        .split("Type the English word")[1].split("Check answers")[0], \
        "the answer must not be on the question page"


# --- marking ----------------------------------------------------------------------

def test_the_cards_own_word_is_right(client, deck):
    text = _text(_post(client, {1: "resignation", 2: "dismissal", 3: "well-being"}))

    assert "Score: 3 / 3" in text


def test_a_synonym_from_the_selection_is_right_and_says_which_card_it_was(
        client, deck):
    """*звільнення* is in both cards: answering card 1 with *dismissal* is
    right, and the result names *resignation* so the learner leaves with
    both."""
    text = _text(_post(client, {1: "dismissal"}))

    assert "Score: 1 / 1" in text
    assert "Also right: resignation" in text


def test_a_synonym_from_outside_the_selection_is_not(client, stub_deck):
    """*sacking* shares the translation but is in a topic not being played."""
    stub_deck(cards=CARDS + [OUTSIDE])
    accepted = rounds._english_accepted(CARDS[1], "translation_ukr", CARDS)

    assert set(accepted) == {"dismissal", "resignation"}
    assert "sacking" not in accepted


def test_a_wrong_answer_shows_the_word(client, deck):
    text = _text(_post(client, {3: "welfare"}))

    assert "Score: 0 / 1" in text
    assert "Correct answer: well-being" in text


@pytest.mark.parametrize("typed", ["Well-Being", "  well being ", "well-being."])
def test_typing_is_forgiven_as_every_english_answer_is(client, deck, typed):
    assert "Score: 1 / 1" in _text(_post(client, {3: typed}))


def test_the_usual_direction_still_marks_translations(client, deck):
    """`from-en` is untouched: the Ukrainian variants are the answers."""
    text = _text(_post(client, {1: "звільнення", 3: "добробут"}, direction="from-en"))

    assert "Score: 2 / 2" in text


def test_the_answers_are_recorded_against_the_asked_card(user_client, deck,
                                                         monkeypatch):
    recorded = []
    monkeypatch.setattr("utils.record_answers",
                        lambda user_id, game, answers: recorded.append(
                            (game, [(c["id"], ok) for c, ok in answers])))
    _post(user_client, {1: "dismissal", 3: "wellness"})

    assert recorded == [("quiz", [(1, True), (3, False)])]


# --- the switch, and remembering it -----------------------------------------------

def test_the_direction_rides_on_every_link_and_the_form(client, deck):
    text = _text(client.get("/quiz/Work?lang=ukr&dir=to-en"))

    assert 'action="/quiz/Work?lang=ukr&amp;dir=to-en' in text
    assert 'href="/quiz/Work?lang=ukr&amp;dir=from-en' in text, "the switch back"
    assert 'href="/quiz/Work?lang=rus&amp;dir=to-en' in text, \
        "the language switch keeps the direction"


def test_the_swap_and_the_language_menu_ask_before_dealing_again(client, deck):
    """One row (Anton, 2 Oct): what you see, a swap, what you type. Both
    controls re-deal the round, so both go through the confirmation."""
    text = _text(client.get("/quiz/Work?lang=ukr"))

    assert re.search(r'class="quiz-swap"[^>]*aria-label="Swap: Ukrainian → English"', text)
    assert 'data-confirm="Do you want to switch to Ukrainian → English?' in text
    assert 'data-confirm="Do you want to switch to Russian translations?' in text
    assert 'querySelectorAll(".quiz-pair a[data-confirm]")' in text
    assert "lang-switch\">" not in text, "the two rows of pills are gone"


def test_one_visible_language_is_a_plain_box(client, deck, monkeypatch):
    """With Russian hidden in Settings there is nothing to choose, so no menu."""
    import web
    real = web.current_settings
    monkeypatch.setattr(web, "current_settings",
                        lambda: dict(real(), show_russian=False))
    text = _text(client.get("/quiz/Work?lang=ukr"))

    assert '<span class="quiz-side">Ukrainian</span>' in text
    assert 'class="quiz-lang"' not in text


def test_the_direction_is_remembered_for_the_visit(client, deck):
    """The Quiz button knows nothing about directions; the session does."""
    client.get("/quiz/Work?lang=ukr&dir=to-en")
    text = _text(client.get("/quiz/Work?lang=ukr"))

    assert "Type the English word" in text
    with client.session_transaction() as sess:
        assert sess[rounds.QUIZ_DIR_KEY] == "to-en"


def test_an_unknown_direction_is_ignored(client, deck):
    text = _text(client.get("/quiz/Work?lang=ukr&dir=sideways"))

    assert "Type the Ukrainian translation" in text


def test_a_review_keeps_its_flag_beside_the_direction(user_client, stub_deck,
                                                      monkeypatch):
    from datetime import date

    import recall
    import utils

    stub_deck(cards=CARDS)
    monkeypatch.setattr(recall, "today", lambda: date(2026, 10, 2))
    monkeypatch.setattr(utils, "due_dates", lambda user_id: {
        recall.word_key("resignation", "noun"): date(2026, 10, 1)})
    text = _text(user_client.get("/quiz?review=1&lang=ukr&dir=to-en"))

    assert 'action="/quiz?review=1&amp;lang=ukr&amp;dir=to-en' in text
    assert "відставка, звільнення" in text


def test_the_round_line_says_which_way(client, deck, action_logs):
    _post(client, {1: "resignation"})
    line = next(l for l in (action_logs / "games.log").read_text(encoding="utf-8")
                .splitlines() if "ROUND" in l)

    assert "game=quiz" in line and "direction=to-en" in line
