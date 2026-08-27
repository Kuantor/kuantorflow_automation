"""
The topic picker (kuantorflow#250).

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

What a *round* then does with the selection is in test_quiz_rounds.py, and how
long it is in test_round_length.py (#69).
"""

import pytest

import games

from conftest import in_other, TEST_USER_ID


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


@pytest.fixture()
def deck(stub_deck):
    """Three topics across two sections -- the grouping is spelled out because
    several tests below assert on the order it renders in."""
    return stub_deck(cards=CARDS, sections=SECTIONS)


# --- the picker --------------------------------------------------------


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
                        lambda owner_id=None, alphabetical=False: in_other([("animals", 4)]))
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
                        lambda owner_id=None, alphabetical=False: [])
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


# --- who may see what (#127) -------------------------------------------


def test_the_picker_lists_only_what_this_visitor_may_see(
        user_client, app_module, monkeypatch):
    """The owner filter reaches the topic listing, so a game never offers a
    topic the site is hiding."""
    seen = []

    def fake_sections(owner_id=None, alphabetical=False):
        seen.append(owner_id)
        return in_other([("mine", 1)])

    monkeypatch.setattr(app_module, "get_topics_by_section", fake_sections)
    monkeypatch.setattr(app_module, "current_settings",
                        lambda: dict(__import__("settings_store").DEFAULTS,
                                     individual_cards=True))
    user_client.get("/quiz")
    assert seen == [TEST_USER_ID]


# --- remembering the selection -----------------------------------------


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
                        lambda owner_id=None, alphabetical=False: in_other([("animals", 4)]))
    response = client.get("/quiz")
    body = response.get_data(as_text=True)
    assert response.status_code == 200, "a stale name is not an error"
    animals = body.index('value="animals"')
    assert "checked" in body[animals:animals + 300]
    assert 'value="Work"' not in body


# --- what a round writes back (#342) -----------------------------------
#
# `/quiz` cannot have this problem: no `topic` parameter there means *the
# picker*, so nothing is ever resolved and remembered behind the learner's
# back. A game's round has its own `/play` URL, where an absent parameter
# safely means the whole deck -- and that is exactly where the expansion could
# be mistaken for a choice.


def _ticked(body, name):
    at = body.index(f'value="{name}"')
    return "checked" in body[at:at + 300]


def test_a_round_that_named_no_topics_remembers_nothing(client, deck):
    """A bare `/play` plays over the whole visible deck (#248), which is what
    keeps a shared link meaningful. Writing that expansion back is a different
    claim: it rewrites *I named no topics* as *I chose all of them*, and the
    picker then opens fully ticked for somebody who chose nothing.
    """
    client.get("/games/fill_the_gap/play")

    with client.session_transaction() as sess:
        assert games.SELECTION_KEY not in sess,             "a round with no topics in its URL expressed no preference"

    body = client.get("/games/fill_the_gap").get_data(as_text=True)
    assert not any(_ticked(body, n) for n in ("Work", "Travel", "animals"))


def test_choosing_every_topic_explicitly_is_still_remembered(client, deck):
    """The case a careless fix breaks. *Select all* submits every name, so the
    URL really did name them and the picker must reopen on all three --
    `remembered_selection()` promises exactly this."""
    client.get("/games/fill_the_gap/play"
               "?topic=Work&topic=Travel&topic=animals")
    body = client.get("/games/fill_the_gap").get_data(as_text=True)
    assert all(_ticked(body, n) for n in ("Work", "Travel", "animals"))


def test_a_bare_round_does_not_overwrite_a_real_choice(client, deck):
    """Following a shared link that names no topics must not wipe what the
    learner picked last time."""
    client.get("/games/fill_the_gap/play?topic=Travel")
    client.get("/games/fill_the_gap/play")
    body = client.get("/games/fill_the_gap").get_data(as_text=True)
    assert _ticked(body, "Travel")
    assert not _ticked(body, "Work")


# --- game slugs --------------------------------------------------------


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


# --- choosing the language before the words are drawn ------------------


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


def test_the_picker_offers_a_word_box_on_both_panels(client, deck):
    body = client.get("/quiz").get_data(as_text=True)
    assert body.count('class="picker-words-box"') == 2
    assert body.count(f'value="{games.QUIZ_WORDS_DEFAULT}"') >= 1


def test_the_start_panel_appears_above_and_below_the_topics(client, deck):
    """The list runs to a screenful and more, so a learner who finished ticking
    near the top should not have to scroll past everything to start."""
    body = client.get("/quiz").get_data(as_text=True)
    assert body.count('class="picker-start"') == 2
    first = body.index("picker-actions")
    topics = body.index('class="picker-topic-box"')
    assert first < topics < body.rindex("picker-actions")
