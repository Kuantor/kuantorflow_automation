"""A round says what it needs (kuantorflow#266).

Two questions the picker cannot answer, because #248 built it on card *counts*
so a page render stays one query:

* **does this card carry what the game needs?** — an explanation, examples, a
  translation in the chosen language. Of production's 503 cards, 74 have no
  English explanation and 86 no examples, so a learner really can tick a full
  topic and meet an empty round.
* **are enough topics ticked?** — odd one out shows three words from one topic
  and a stranger from another, which one topic cannot produce however many
  cards it holds.

The first was open-coded in five rounds with five field names and five
phrasings of the same sentence. This is the one helper, the one message, and
the one page for a round that cannot be dealt.
"""

import pytest

import games


CARDS = [
    {"id": 1, "word": "delegate", "topic": "Work", "translation_ukr": "делегувати"},
    {"id": 2, "word": "resign", "topic": "Work", "translation_ukr": "звільнятися"},
    {"id": 3, "word": "burnout", "topic": "Work"},          # no translation
    {"id": 4, "word": "commute", "topic": "Work", "translation_ukr": "їздити"},
]


# --- the helper ----------------------------------------------------------


def test_it_keeps_the_cards_the_rule_accepts_and_counts_the_rest():
    kept, dropped = games.playable(CARDS, lambda c: c.get("translation_ukr"))
    assert [card["word"] for card, _ in kept] == ["delegate", "resign", "commute"]
    assert dropped == 1


def test_it_hands_back_what_the_rule_made_not_just_a_yes():
    """The point of the shape. Asking "can this be scrambled?" and then
    scrambling it would either state the rule twice, in two places that drift,
    or spend the random draw twice and shuffle a different word than it
    tested."""
    kept, _ = games.playable(CARDS, lambda c: (c.get("translation_ukr") or "").upper())
    assert kept[0][1] == "ДЕЛЕГУВАТИ"


def test_a_rule_returning_false_drops_the_card_like_none():
    """Predicates are the common case and read naturally as booleans; a rule
    that derives a value returns None. Both have to mean the same thing or the
    helper is a trap for whichever style the next caller picks."""
    kept, dropped = games.playable(CARDS, lambda c: bool(c.get("translation_ukr")))
    assert len(kept) == 3 and dropped == 1


def test_nothing_eligible_is_an_empty_list_and_a_full_count():
    kept, dropped = games.playable(CARDS, lambda c: None)
    assert kept == [] and dropped == len(CARDS)


def test_an_empty_selection_drops_nothing():
    """Zero of zero. The round has a different thing to say about an empty
    selection, and a shortfall sentence claiming `0 cards` would be noise."""
    assert games.playable([], lambda c: True) == ([], 0)


def test_it_does_not_touch_the_cards_it_is_given():
    cards = [dict(CARDS[0])]
    games.playable(cards, lambda c: c.get("translation_ukr"))
    assert cards == [dict(CARDS[0])]


# --- what an activity declares -------------------------------------------


def test_every_activity_declares_at_least_one_topic():
    for activity in games.ACTIVITIES.values():
        assert activity.min_topics >= 1, activity.slug


def test_an_activity_wanting_several_topics_says_why():
    """`too_few_topics` is only read above one, so an activity that does not
    care leaves it empty — but one that does care must not, or the picker
    disables Start with no explanation."""
    for activity in games.ACTIVITIES.values():
        if activity.min_topics > 1:
            assert activity.too_few_topics, activity.slug


def test_odd_one_out_needs_two_topics():
    """The case the field exists for: a stranger has to come from somewhere
    else, and no number of cards in one topic can supply it."""
    assert games.ACTIVITIES["odd_one_out"].min_topics == 2


def test_a_game_that_filters_its_cards_says_what_it_needs():
    """`needs` is what the shared sentence prints. A game that drops cards
    without saying why leaves a learner unable to tell a filter from a bug —
    the reason the quiz started saying it in the first place."""
    for slug in ("quiz", "multiple_choice", "scrambled", "fill_the_gap",
                 "real_or_fake", "spell_it", "rebuild_the_sentence"):
        assert games.ACTIVITIES[slug].needs, slug


def test_a_game_that_asks_nothing_of_a_card_leaves_needs_empty():
    """Odd one out uses a word and the topic it lives in, which every card has.
    An empty `needs` keeps the sentence from ever rendering."""
    assert games.ACTIVITIES["odd_one_out"].needs == ""


# --- the round ------------------------------------------------------------


@pytest.fixture()
def deck(stub_deck):
    return stub_deck(cards=CARDS, topics=[("Work", 4), ("Play", 2)])


def _text(body):
    return " ".join(body.split())


def test_the_round_names_what_it_could_not_use(client, deck):
    body = client.get("/quiz?topic=Work&words=20").get_data(as_text=True)
    flat = _text(body)
    assert "1 card here is not usable for this game" in flat
    assert "a translation in the language you chose" in flat


def test_a_round_that_can_use_everything_says_nothing(client, stub_deck):
    """The sentence renders only when something was dropped, so a caller can
    include it unconditionally and a clean round stays quiet."""
    stub_deck(cards=[c for c in CARDS if c.get("translation_ukr")],
              topics=[("Work", 3)])
    body = client.get("/quiz?topic=Work&words=20").get_data(as_text=True)
    assert "not usable for this game" not in body


def test_too_few_topics_is_explained_and_not_a_404(client, deck):
    """A hand-typed or shared `?topic=` reaches the round without passing the
    Start button that would have been disabled."""
    body = client.get("/games/odd_one_out/play?topic=Work").get_data(as_text=True)
    assert "at least 2 topics" in body
    assert games.ACTIVITIES["odd_one_out"].too_few_topics in body
    assert "Choose different topics" in body


def test_an_empty_selection_is_its_own_sentence(client, deck):
    """Not "needs at least 1 topics", which is arithmetic where a sentence was
    wanted — every activity needs one, so nothing is being refused."""
    body = client.get("/games/scrambled/play?topic=__nothing__").get_data(as_text=True)
    assert "No topics are selected" in body


def test_enough_topics_reaches_the_round(client, deck):
    body = client.get("/games/odd_one_out/play?topic=Work&topic=Play").get_data(as_text=True)
    assert "at least 2 topics" not in body


def test_the_picker_carries_both_limits(client, deck):
    """One control, two reasons it can be disabled, each with its own message
    — they send a learner to different parts of the same page."""
    body = client.get("/games/odd_one_out").get_data(as_text=True)
    assert 'data-min-topics="2"' in body
    assert 'data-min-cards="4"' in body
    assert games.ACTIVITIES["odd_one_out"].too_few_topics in body
