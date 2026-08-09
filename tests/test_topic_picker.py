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


def test_a_game_with_no_ticket_yet_is_not_a_page(client, deck):
    """Every game slug 404s until its own ticket registers it. A tile opening a
    picker whose start button led nowhere would be worse than no tile."""
    assert client.get("/games/scrambled").status_code == 404
    assert client.get("/games/scrambled/play").status_code == 404


def test_the_quiz_is_not_reachable_as_a_game(client, deck):
    """It has its own URL, and two ways in would be two things to keep
    working."""
    assert client.get("/games/quiz").status_code == 404
