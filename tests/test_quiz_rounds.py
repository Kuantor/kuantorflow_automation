"""
What a round does with the selection the picker made (kuantorflow#250).

The several-topic quiz and the single-topic route it was grown from, the line
that names which topics are in play, why a round can be shorter than the cards
that were ticked, and the confirmation that guards a language switch.

Split out of test_topic_picker.py (#69), which had become four features under
one name. The picker's own markup is still there; how long a round is lives in
test_round_length.py.

The rule most of these protect: **the round is a random sample**, so anything
that re-draws -- a language switch, a POST that graded a fresh draw -- would
mark or show words the learner never saw.
"""

import pytest


CARDS = [
    {"id": 1, "word": "resign", "pos": "verb", "topic": "Work",
     "translation_ukr": "звільнятися",
     "translation_rus": "увольняться"},
    {"id": 2, "word": "commute", "pos": "noun", "topic": "Work",
     "translation_ukr": "поїздка",
     "translation_rus": "поездка"},
    {"id": 3, "word": "itinerary", "pos": "noun", "topic": "Travel",
     "translation_ukr": "маршрут",
     "translation_rus": "маршрут"},
]

SECTIONS = [
    ("B2–C1 Conversational Topics", [("Work", 2), ("Travel", 1)]),
    ("Other", [("animals", 4)]),
]

MIXED = (
    [{"id": i, "word": f"both{i}", "topic": "Work",
      "translation_ukr": f"укр{i}", "translation_rus": f"рус{i}"}
     for i in range(1, 6)]
    + [{"id": 50 + i, "word": f"rusonly{i}", "topic": "Work",
        "translation_ukr": None, "translation_rus": f"рус{i}"}
       for i in range(1, 4)]
)


@pytest.fixture()
def deck(stub_deck):
    return stub_deck(cards=CARDS, sections=SECTIONS)


@pytest.fixture()
def mixed_deck(stub_deck):
    """Eight cards, three of which have no Ukrainian."""
    return stub_deck(cards=MIXED)


def _flat(body):
    """The body with runs of whitespace collapsed.

    The explanations below are laid out over several template lines, so the
    rendered HTML carries newlines and indentation inside a sentence. What is
    being asserted is the prose a reader sees, not how Jinja wrapped it.
    """
    return " ".join(body.split())


# --- the quiz over several topics --------------------------------------


def test_several_topics_are_quizzed_as_one_run(client, deck):
    body = client.get("/quiz?topic=Work&topic=Travel").get_data(as_text=True)
    assert "Quiz: 2 topics" in body
    assert "3 questions" in body


def test_one_selected_topic_is_named_rather_than_counted(client, deck):
    body = client.get("/quiz?topic=Work").get_data(as_text=True)
    assert "Quiz: Work" in body


def test_the_selection_survives_into_the_language_switch(client, deck):
    body = client.get("/quiz?topic=Work&topic=Travel").get_data(as_text=True)
    assert "topic=Work&amp;topic=Travel&amp;lang=rus" in body


def test_grading_a_multi_topic_run_scores_the_whole_selection(client, deck):
    response = client.post("/quiz?topic=Work&topic=Travel&lang=ukr",
                           data={"answer_1": "звільнятися", "answer_2": "",
                                 "answer_3": "маршрут"})
    body = response.get_data(as_text=True)
    assert "Score: 2 / 3" in body


def test_playing_remembers_what_was_played(client, deck):
    """So the picker opens on it next time, whether the learner arrived through
    the picker or followed a link."""
    client.get("/quiz?topic=Travel")
    body = client.get("/quiz").get_data(as_text=True)
    travel = body.index('value="Travel"')
    assert "checked" in body[travel:travel + 300]


def test_an_unknown_topic_in_the_url_is_ignored_rather_than_played(client, deck):
    body = client.get("/quiz?topic=Work&topic=Nonexistent").get_data(as_text=True)
    assert "Quiz: Work" in body, "one topic survived, so it is named not counted"


# --- the original single-topic route -----------------------------------


def test_the_single_topic_quiz_still_works(client, deck):
    body = client.get("/quiz/Work").get_data(as_text=True)
    assert "Quiz: Work" in body
    assert "3 questions" in body


def test_the_single_topic_quiz_still_links_back_to_its_topic_page(client, deck):
    """Three templates build url_for('quiz', topic=...), and #233 requires that
    none of them break."""
    body = client.get("/quiz/Work").get_data(as_text=True)
    assert "/flashcards/Work" in body
    assert 'action="/quiz/Work?lang=' in body


def test_the_two_quiz_shapes_are_separate_endpoints(app_module):
    """One endpoint carrying both rules would leave url_for choosing between the
    path converter and a repeated query parameter — and it picks the converter,
    making the multi-topic URL unbuildable."""
    with app_module.app.test_request_context():
        from flask import url_for
        assert url_for("quiz", topic="Work") == "/quiz/Work"
        assert url_for("quiz_topics", topic=["Work", "Travel"]) == \
            "/quiz?topic=Work&topic=Travel"


# --- naming the topics under the title ---------------------------------


def test_a_multi_topic_quiz_names_the_topics_under_its_title(client, deck):
    """The title counts them; this says which. A count alone leaves the learner
    unable to tell one selection from another."""
    body = client.get("/quiz?topic=Work&topic=Travel").get_data(as_text=True)
    assert "Quiz: 2 topics" in body
    assert '<p class="quiz-topics">Work, Travel</p>' in body


def test_three_topics_are_all_named_without_an_ellipsis(client, app_module,
                                                        monkeypatch, deck):
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None, alphabetical=False, **kw: [("Sec", [("Work", 2), ("Travel", 1),
                                                        ("animals", 4)])])
    body = client.get("/quiz?topic=Work&topic=Travel&topic=animals").get_data(as_text=True)
    assert '<p class="quiz-topics">Work, Travel, animals</p>' in body
    assert "…" not in body.split('class="quiz-topics"')[1].split("</p>")[0]


def test_more_than_three_topics_are_truncated_with_an_ellipsis(
        client, app_module, monkeypatch, deck):
    monkeypatch.setattr(
        app_module, "get_topics_by_section",
        lambda owner_id=None, alphabetical=False, **kw: [("Sec", [("Work", 2), ("Travel", 1),
                                        ("animals", 4), ("IT", 3)])])
    body = client.get(
        "/quiz?topic=Work&topic=Travel&topic=animals&topic=IT").get_data(as_text=True)
    assert '<p class="quiz-topics">Work, Travel, animals …</p>' in body
    assert "IT" not in body.split('class="quiz-topics"')[1].split("</p>")[0]


def test_the_named_topics_follow_page_order_not_parameter_order(client, deck):
    """Same order as the picker and the front page (#215), so the line matches
    what the learner just ticked rather than how the URL happened to be built."""
    body = client.get("/quiz?topic=animals&topic=Work").get_data(as_text=True)
    assert '<p class="quiz-topics">Work, animals</p>' in body


def test_a_single_topic_quiz_does_not_repeat_its_name(client, deck):
    """'Quiz: Work' above a line reading 'Work' is the same word twice."""
    for url in ("/quiz/Work", "/quiz?topic=Work"):
        body = client.get(url).get_data(as_text=True)
        assert "Quiz: Work" in body
        assert 'class="quiz-topics"' not in body, url


# --- saying why a round is short (kuantorflow#250) ---------------------


MIXED = (
    [{"id": i, "word": f"both{i}", "topic": "Work",
      "translation_ukr": f"укр{i}", "translation_rus": f"рус{i}"} for i in range(1, 6)]
    + [{"id": 50 + i, "word": f"rusonly{i}", "topic": "Work",
        "translation_ukr": None, "translation_rus": f"рус{i}"} for i in range(1, 4)]
)


@pytest.fixture()
def mixed_deck(stub_deck):
    """Eight cards, three of which have no Ukrainian."""
    return stub_deck(cards=MIXED)


def test_a_card_with_no_translation_in_this_language_is_never_asked(
        client, mixed_deck):
    """Filtered before the draw, so the sample can only hold answerable words."""
    body = client.get("/quiz?topic=Work&words=20&lang=ukr").get_data(as_text=True)
    assert "(5 questions)" in body
    assert "rusonly" not in body


def test_the_round_says_why_it_is_shorter_than_the_selection(client, mixed_deck):
    """The picker counts cards, not cards with a Ukrainian translation, so a
    learner who ticked eight and was asked five cannot otherwise tell that from
    the word limit."""
    body = client.get("/quiz?topic=Work&words=20&lang=ukr").get_data(as_text=True)
    assert "3 cards here are not usable for this game" in _flat(body)
    assert "they are not asked" in _flat(body)


def test_the_reason_names_the_language_actually_being_quizzed(client, mixed_deck):
    """Every card has a Russian translation, so in Russian there is nothing to
    explain and the sentence is absent."""
    body = client.get("/quiz?topic=Work&words=20&lang=rus").get_data(as_text=True)
    assert "(8 questions)" in body
    assert "no Russian translation" not in _flat(body)


def test_one_missing_card_is_described_in_the_singular(client, app_module,
                                                       monkeypatch, mixed_deck):
    monkeypatch.setattr(
        app_module, "get_flashcards_by_topics",
        lambda topics, owner_id=None, **kw: [dict(c) for c in MIXED[:5]]
        + [{"id": 99, "word": "lonely", "topic": "Work",
            "translation_ukr": None, "translation_rus": "рус"}])
    body = client.get("/quiz?topic=Work&words=20&lang=ukr").get_data(as_text=True)
    assert "1 card here is not usable for this game" in _flat(body)
    assert "it is not asked" in _flat(body)


def test_a_single_question_is_not_called_questions(client, app_module,
                                                   monkeypatch, mixed_deck):
    monkeypatch.setattr(app_module, "get_flashcards_by_topics",
                        lambda topics, owner_id=None, **kw: [dict(MIXED[0])])
    body = client.get("/quiz?topic=Work&lang=ukr").get_data(as_text=True)
    assert "(1 question)" in body


def test_a_selection_with_nothing_in_this_language_says_so(client, app_module,
                                                           monkeypatch, mixed_deck):
    """The picker's minimum counts cards, so Start can enable on a topic whose
    cards all lack this language — production has one. The round explains it
    rather than rendering empty."""
    monkeypatch.setattr(app_module, "get_flashcards_by_topics",
                        lambda topics, owner_id=None, **kw: [dict(c) for c in MIXED[5:]])
    body = client.get("/quiz?topic=Work&lang=ukr").get_data(as_text=True)
    assert "nothing to quiz on" in body


# --- confirming a language switch --------------------------------------


def test_switching_language_asks_first(client, mixed_deck):
    """The words are a random sample, so switching re-draws the round — cheap to
    confirm, expensive to discover halfway through a set of typed answers."""
    body = client.get("/quiz?topic=Work&lang=ukr").get_data(as_text=True)
    assert 'id="lang-switch-modal"' in body
    assert 'data-lang-name="Russian"' in body


def test_the_confirmation_names_the_language_being_switched_to(client, mixed_deck):
    """Both directions, from one dialog that reads the name off the link it
    intercepted — so neither language is named in the script."""
    ukr = client.get("/quiz?topic=Work&lang=ukr").get_data(as_text=True)
    rus = client.get("/quiz?topic=Work&lang=rus").get_data(as_text=True)
    assert 'data-lang-name="Russian"' in ukr and 'data-lang-name="Ukrainian"' not in ukr
    assert 'data-lang-name="Ukrainian"' in rus and 'data-lang-name="Russian"' not in rus


def test_with_one_visible_language_there_is_nothing_to_confirm(
        client, app_module, monkeypatch, mixed_deck):
    """#46/#79: a hidden language offers no switch link, so the dialog's script
    returns early rather than wiring nothing."""
    import settings_store
    monkeypatch.setattr(app_module, "current_settings",
                        lambda: dict(settings_store.DEFAULTS, show_russian=False))
    body = client.get("/quiz?topic=Work").get_data(as_text=True)
    assert 'data-lang-name="' not in body


def test_the_quiz_results_offer_a_way_home(client, deck):
    """Same as the games' results page (kuantorflow#133): after a set of graded
    answers the row at the top of the page is a long way back up."""
    body = client.post("/quiz?topic=Work&lang=ukr",
                       data={"answer_1": ""}).get_data(as_text=True)
    row = body.split('<p class="crumbs">')[-1].split("</p>")[0]
    assert "Try again" in row
    assert 'href="/"' in row


def test_the_chosen_language_reaches_the_round(client, mixed_deck):
    """What the picker submits is what the quiz runs in."""
    body = client.get("/quiz?topic=Work&lang=rus").get_data(as_text=True)
    assert "Type the Russian translation" in body
