"""
The topic picker, and the quiz that proves it (kuantorflow#250).

The step between an activity button and a round. #233 gives every activity the
same picker, so what is proved here for the quiz is what the four games inherit.

Two rules run through most of these, and both are about *not lying to the
learner*:

* the picker shows the topics the learner can see and no others, so a round
  never quizzes anybody on cards the site is hiding from them (#127);
* and a remembered selection is a hint, never a source of truth -- topics
  disappear between rounds, and the stale ones are dropped in silence rather
  than erroring or, worse, being played anyway.

The tri-state checkbox behaviour is in the page's own script and is not
exercised here: these tests are server-side, and what they check is the markup
that script needs -- the members, their sections, and their counts.
"""

import pytest

from conftest import in_other, TEST_USER_ID


CARDS = [
    {"id": 1, "word": "resign", "pos": "verb", "topic": "Work",
     "translation_ukr": "звільнятися", "translation_rus": "увольняться"},
    {"id": 2, "word": "commute", "pos": "noun", "topic": "Work",
     "translation_ukr": "поїздка", "translation_rus": "поездка"},
    {"id": 3, "word": "itinerary", "pos": "noun", "topic": "Travel",
     "translation_ukr": "маршрут", "translation_rus": "маршрут"},
]

SECTIONS = [
    ("B2–C1 Conversational Topics", [("Work", 2), ("Travel", 1)]),
    ("Other", [("animals", 4)]),
]


@pytest.fixture()
def deck(app_module, monkeypatch):
    """A visible deck of three topics across two sections."""
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None: [(s, list(t)) for s, t in SECTIONS])
    monkeypatch.setattr(app_module, "get_flashcards_by_topics",
                        lambda topics, owner_id=None: [dict(c) for c in CARDS])
    monkeypatch.setattr(app_module, "get_flashcards_by_topic",
                        lambda topic, owner_id=None: [dict(c) for c in CARDS])


# --- the picker ---------------------------------------------------------


def test_quiz_without_topics_opens_the_picker(client, deck):
    body = client.get("/quiz").get_data(as_text=True)
    assert "Choose the topics to be quizzed on" in body
    assert 'id="topic-picker"' in body


def test_the_picker_submits_as_a_get_form_to_the_activity(client, deck):
    """A GET form is what makes the round's URL shareable and bookmarkable, and
    it is why no JavaScript is needed to submit — the ticked boxes are the
    query string."""
    body = client.get("/quiz").get_data(as_text=True)
    assert 'method="GET" action="/quiz"' in body
    assert body.count('name="topic"') == 3


def test_every_visible_topic_is_offered_with_its_count(client, deck):
    body = client.get("/quiz").get_data(as_text=True)
    for topic in ("Work", "Travel", "animals"):
        assert f'value="{topic}"' in body
    assert "2 cards" in body and "1 card" in body and "4 cards" in body


def test_topics_appear_in_the_order_the_page_renders_them(client, deck):
    """#215's (section.position, topic.position, topic.name), not re-sorted.
    Alphabetically 'Travel' precedes 'Work'; the curriculum order does not."""
    body = client.get("/quiz").get_data(as_text=True)
    assert body.index('value="Work"') < body.index('value="Travel"') \
        < body.index('value="animals"')


def test_topics_are_grouped_under_their_section_headings(client, deck):
    body = client.get("/quiz").get_data(as_text=True)
    assert "B2–C1 Conversational Topics" in body and "Other" in body
    # counted by the control's class, not its label: the page's own script
    # mentions "Select section" in a comment explaining that it and "Select
    # all" are one implementation, and that would inflate a text count.
    assert body.count('class="picker-section-box"') == 2


def test_each_topic_knows_which_section_box_governs_it(client, deck):
    """The script pairs them by this attribute, so a wrong one would put a topic
    under a heading that does not control it."""
    body = client.get("/quiz").get_data(as_text=True)
    work = body.index('value="Work"')
    animals = body.index('value="animals"')
    assert 'data-section="1"' in body[work:work + 300]
    assert 'data-section="2"' in body[animals:animals + 300]


def test_a_section_with_no_topics_is_left_out(client, app_module, monkeypatch):
    """#218 shows an empty heading on the browse page deliberately, because
    there it promises what the deck will become. In a form it is a heading over
    nothing with a Select-section box that selects nothing."""
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None: in_other([("animals", 4)]))
    body = client.get("/quiz").get_data(as_text=True)
    assert "animals" in body
    assert "B2–C1 Conversational Topics" not in body
    assert body.count('class="picker-section-box"') == 1


def test_the_start_button_carries_the_activitys_minimum_and_reason(client, deck):
    body = client.get("/quiz").get_data(as_text=True)
    assert 'data-min-cards="1"' in body
    assert "Tick at least one topic to start the quiz." in body


def test_an_empty_deck_is_explained_in_the_picker(client, app_module, monkeypatch):
    """#233: the tile that sent the learner here has no selection to reason
    about, so this is the only place that can say it."""
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None: [])
    body = client.get("/quiz").get_data(as_text=True)
    assert "nothing to play on yet" in body
    assert 'id="topic-picker"' not in body


def test_a_dead_database_leaves_an_empty_picker_not_a_500(
        client, app_module, monkeypatch):
    def boom(owner_id=None):
        raise RuntimeError("no database")

    monkeypatch.setattr(app_module, "get_topics_by_section", boom)
    response = client.get("/quiz")
    assert response.status_code == 200
    assert "nothing to play on yet" in response.get_data(as_text=True)


# --- who may see what (#127) --------------------------------------------


def test_the_picker_lists_only_what_this_visitor_may_see(
        user_client, app_module, monkeypatch):
    """The owner filter reaches the topic listing, so a game never offers a
    topic the site is hiding."""
    seen = []

    def fake_sections(owner_id=None):
        seen.append(owner_id)
        return in_other([("mine", 1)])

    monkeypatch.setattr(app_module, "get_topics_by_section", fake_sections)
    monkeypatch.setattr(app_module, "current_settings",
                        lambda: dict(__import__("settings_store").DEFAULTS,
                                     individual_cards=True))
    user_client.get("/quiz")
    assert seen == [TEST_USER_ID]


# --- remembering the selection ------------------------------------------


def test_the_picker_opens_with_the_previous_selection_ticked(client, deck):
    client.get("/quiz?topic=Work&topic=animals")
    body = client.get("/quiz").get_data(as_text=True)
    work = body.index('value="Work"')
    travel = body.index('value="Travel"')
    assert "checked" in body[work:work + 300]
    assert "checked" not in body[travel:travel + 300]


def test_an_anonymous_visitor_is_remembered_too(client, deck):
    """#233 chose the session over settings_store precisely for this: settings
    are read-only for anonymous visitors (#102), so a settings-backed selection
    would be remembered for accounts and silently forgotten for everybody
    else."""
    client.get("/quiz?topic=Travel")
    body = client.get("/quiz").get_data(as_text=True)
    travel = body.index('value="Travel"')
    assert "checked" in body[travel:travel + 300]


def test_a_remembered_topic_that_has_gone_is_dropped_and_the_rest_survive(
        client, deck, app_module, monkeypatch):
    client.get("/quiz?topic=Work&topic=animals")
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None: in_other([("animals", 4)]))
    response = client.get("/quiz")
    body = response.get_data(as_text=True)
    assert response.status_code == 200, "a stale name is not an error"
    animals = body.index('value="animals"')
    assert "checked" in body[animals:animals + 300]
    assert 'value="Work"' not in body


# --- the quiz over several topics ---------------------------------------


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


# --- the original single-topic route ------------------------------------


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


# --- game slugs ---------------------------------------------------------


def test_a_registered_game_has_a_picker_and_a_round(client, deck):
    """Since kuantorflow#253 every activity registers as soon as the panel
    exists, so its picker and its Start button are real from the first day —
    only the round is a stub. A tile whose Start led to a 404 would be worse
    than no tile."""
    assert client.get("/games/scrambled").status_code == 200
    assert client.get("/games/scrambled/play").status_code == 200


def test_a_slug_nobody_declared_is_still_not_a_page(client, deck):
    assert client.get("/games/invented").status_code == 404
    assert client.get("/games/invented/play").status_code == 404


def test_the_quiz_is_not_reachable_as_a_game(client, deck):
    """It has its own URL, and two ways in would be two things to keep
    working."""
    assert client.get("/games/quiz").status_code == 404


# --- naming the topics under the title ----------------------------------


def test_a_multi_topic_quiz_names_the_topics_under_its_title(client, deck):
    """The title counts them; this says which. A count alone leaves the learner
    unable to tell one selection from another."""
    body = client.get("/quiz?topic=Work&topic=Travel").get_data(as_text=True)
    assert "Quiz: 2 topics" in body
    assert '<p class="quiz-topics">Work, Travel</p>' in body


def test_three_topics_are_all_named_without_an_ellipsis(client, app_module,
                                                        monkeypatch, deck):
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None: [("Sec", [("Work", 2), ("Travel", 1),
                                                        ("animals", 4)])])
    body = client.get("/quiz?topic=Work&topic=Travel&topic=animals").get_data(as_text=True)
    assert '<p class="quiz-topics">Work, Travel, animals</p>' in body
    assert "…" not in body.split('class="quiz-topics"')[1].split("</p>")[0]


def test_more_than_three_topics_are_truncated_with_an_ellipsis(
        client, app_module, monkeypatch, deck):
    monkeypatch.setattr(
        app_module, "get_topics_by_section",
        lambda owner_id=None: [("Sec", [("Work", 2), ("Travel", 1),
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


# --- how many words a round asks (kuantorflow#250) ----------------------


MANY = [{"id": i, "word": f"word{i}", "pos": "noun", "topic": "Work",
         "translation_ukr": f"слово{i}", "translation_rus": f"слово{i}"}
        for i in range(1, 61)]


@pytest.fixture()
def big_deck(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None: [("Sec", [("Work", 60)])])
    monkeypatch.setattr(app_module, "get_flashcards_by_topics",
                        lambda topics, owner_id=None: [dict(c) for c in MANY])


def _flat(body):
    """The body with runs of whitespace collapsed.

    The explanations below are laid out over several template lines, so the
    rendered HTML carries newlines and indentation inside a sentence. What is
    being asserted is the prose a reader sees, not how Jinja wrapped it."""
    return " ".join(body.split())


def _asked(body):
    """The answer_<id> fields a rendered round is asking about."""
    import re
    return re.findall(r'name="answer_(\d+)"', body)


def test_a_round_asks_twenty_words_by_default(client, big_deck):
    """Sixty cards is not a round, it is an afternoon."""
    body = client.get("/quiz?topic=Work").get_data(as_text=True)
    assert len(_asked(body)) == 20
    assert "(20 questions)" in body


def test_the_word_count_can_be_asked_for_in_the_url(client, big_deck):
    body = client.get("/quiz?topic=Work&words=5").get_data(as_text=True)
    assert len(_asked(body)) == 5


def test_asking_for_more_words_than_exist_plays_what_there_is(client, big_deck):
    body = client.get("/quiz?topic=Work&words=200").get_data(as_text=True)
    assert len(_asked(body)) == 60


@pytest.mark.parametrize("raw,expected", [("0", 1), ("-4", 1), ("9999", 60),
                                          ("abc", 20), ("", 20)])
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


def test_the_picker_offers_a_word_box_on_both_panels(client, deck):
    body = client.get("/quiz").get_data(as_text=True)
    assert body.count('class="picker-words-box"') == 2
    assert body.count('value="20"') >= 1


def test_the_start_panel_appears_above_and_below_the_topics(client, deck):
    """The list runs to a screenful and more, so a learner who finished ticking
    near the top should not have to scroll past everything to start."""
    body = client.get("/quiz").get_data(as_text=True)
    assert body.count('class="picker-start"') == 2
    first = body.index("picker-actions")
    topics = body.index('class="picker-topic-box"')
    assert first < topics < body.rindex("picker-actions")


def test_the_word_count_is_remembered_like_the_topics(client, deck):
    client.get("/quiz?topic=Work&words=7")
    body = client.get("/quiz").get_data(as_text=True)
    assert 'value="7"' in body


# --- saying why a round is short (kuantorflow#250) -----------------------


MIXED = (
    [{"id": i, "word": f"both{i}", "topic": "Work",
      "translation_ukr": f"укр{i}", "translation_rus": f"рус{i}"} for i in range(1, 6)]
    + [{"id": 50 + i, "word": f"rusonly{i}", "topic": "Work",
        "translation_ukr": None, "translation_rus": f"рус{i}"} for i in range(1, 4)]
)


@pytest.fixture()
def mixed_deck(app_module, monkeypatch):
    """Eight cards, three of which have no Ukrainian."""
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None: [("Sec", [("Work", 8)])])
    monkeypatch.setattr(app_module, "get_flashcards_by_topics",
                        lambda topics, owner_id=None: [dict(c) for c in MIXED])


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
    assert "3 cards in this selection have no Ukrainian translation" in _flat(body)
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
        lambda topics, owner_id=None: [dict(c) for c in MIXED[:5]]
        + [{"id": 99, "word": "lonely", "topic": "Work",
            "translation_ukr": None, "translation_rus": "рус"}])
    body = client.get("/quiz?topic=Work&words=20&lang=ukr").get_data(as_text=True)
    assert "1 card in this selection has no Ukrainian translation" in _flat(body)
    assert "it is not asked" in _flat(body)


def test_a_single_question_is_not_called_questions(client, app_module,
                                                   monkeypatch, mixed_deck):
    monkeypatch.setattr(app_module, "get_flashcards_by_topics",
                        lambda topics, owner_id=None: [dict(MIXED[0])])
    body = client.get("/quiz?topic=Work&lang=ukr").get_data(as_text=True)
    assert "(1 question)" in body


def test_a_selection_with_nothing_in_this_language_says_so(client, app_module,
                                                           monkeypatch, mixed_deck):
    """The picker's minimum counts cards, so Start can enable on a topic whose
    cards all lack this language — production has one. The round explains it
    rather than rendering empty."""
    monkeypatch.setattr(app_module, "get_flashcards_by_topics",
                        lambda topics, owner_id=None: [dict(c) for c in MIXED[5:]])
    body = client.get("/quiz?topic=Work&lang=ukr").get_data(as_text=True)
    assert "nothing to quiz on" in body


# --- confirming a language switch ---------------------------------------


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


# --- choosing the language before the words are drawn -------------------


def test_the_picker_offers_the_translation_language(client, deck):
    """Chosen before the draw rather than inside the round, where switching
    re-draws the words — which is also why this one needs no confirmation."""
    body = client.get("/quiz").get_data(as_text=True)
    assert "Translation to:" in body
    assert 'name="lang" value="ukr"' in body
    assert 'name="lang" value="rus"' in body


def test_the_language_starts_on_the_identitys_setting(client, deck):
    """#113's quiz_lang, which defaults to Ukrainian."""
    body = client.get("/quiz").get_data(as_text=True)
    ukr = body.index('value="ukr"')
    assert "checked" in body[ukr:ukr + 120]


def test_the_setting_decides_which_language_is_preselected(client, app_module,
                                                           monkeypatch, deck):
    import settings_store
    monkeypatch.setattr(app_module, "current_settings",
                        lambda: dict(settings_store.DEFAULTS, quiz_lang="russian"))
    body = client.get("/quiz").get_data(as_text=True)
    rus = body.index('value="rus"')
    assert "checked" in body[rus:rus + 120]


def test_the_chosen_language_reaches_the_round(client, mixed_deck):
    """What the picker submits is what the quiz runs in."""
    body = client.get("/quiz?topic=Work&lang=rus").get_data(as_text=True)
    assert "Type the Russian translation" in body


def test_the_language_row_appears_once_not_on_both_panels(client, deck):
    """Radios sharing a name are one group across the form, so a second copy
    could not show the same choice — checking one would clear the other. The
    word box is duplicated precisely because it can be."""
    body = client.get("/quiz").get_data(as_text=True)
    assert body.count("Translation to:") == 1
    assert body.count('class="picker-words-box"') == 2


def test_the_row_is_on_the_upper_panel(client, deck):
    body = client.get("/quiz").get_data(as_text=True)
    assert body.index("Translation to:") < body.index('class="picker-topic-box"')


def test_one_visible_language_offers_no_choice(client, app_module,
                                               monkeypatch, deck):
    """#46/#79: with a language hidden there is nothing to choose, and a lone
    radio is a control that cannot do anything."""
    import settings_store
    monkeypatch.setattr(app_module, "current_settings",
                        lambda: dict(settings_store.DEFAULTS, show_russian=False))
    body = client.get("/quiz").get_data(as_text=True)
    assert "Translation to:" not in body
    assert 'name="lang"' not in body


def test_only_an_activity_that_declares_it_gets_the_language_row():
    """A game that shows a word and asks about its spelling has no translation
    in it, so the flag is off unless an activity says otherwise."""
    import games
    assert games.ACTIVITIES["quiz"].picks_language is True
    other = games.Activity(slug="x", name="X", kind="game", picker_heading="h",
                           min_cards=1, too_small="t")
    assert other.picks_language is False
