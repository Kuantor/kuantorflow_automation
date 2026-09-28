"""The draw prefers the words a learner needs (kuantorflow#480).

A signed-in learner's SM-2 schedule (#479) weights every round whose question
is one card: a word due today or never answered weighs 1, a word scheduled
for a later day weighs 0.2. Three layers, tested separately:

* `games.sample()` -- weighted sampling without replacement that knows
  nothing of schedules, never excludes, and without a weight is the old
  uniform draw exactly;
* `recall.draw_weight()` -- the schedule as weights, keyed the way the
  schedule is;
* the rounds -- which pass it, which deliberately do not, and who gets it.

The draw is random, so the round-level tests do not count outcomes: they
capture the weight each round hands `sample()` and check what it says about
each card. The statistics are tested once, on `sample()` itself, with a
pinned rng.
"""

import random
from collections import Counter
from datetime import date

import pytest

import games
import recall

TODAY = date(2026, 9, 29)


def _weight(schedule, on_day=TODAY):
    return recall.draw_weight(
        {recall.word_key(w, p): due for (w, p), due in schedule.items()}, on_day)


# --- games.sample() ----------------------------------------------------------

CARDS = [{"id": n, "word": f"word{n}", "pos": "noun"} for n in range(20)]


def test_without_a_weight_the_draw_is_exactly_the_old_one():
    """An anonymous visitor, and a learner with no schedule, must see nothing
    change -- down to which cards a given seed deals."""
    assert (games.sample(CARDS, 5, rng=random.Random(7))
            == random.Random(7).sample(CARDS, 5))


def test_heavier_cards_are_dealt_more_often():
    """Half the cards at 1 and half at 0.2. Drawing 5 of 20 without
    replacement, the heavy half should come up about four times as often --
    not five, because a heavy card once drawn cannot be drawn again."""
    heavy = {card["id"] for card in CARDS[:10]}
    rng = random.Random(1)
    dealt = Counter()
    for _ in range(4000):
        for card in games.sample(CARDS, 5, rng=rng,
                                 weight=lambda c: 1 if c["id"] in heavy else 0.2):
            dealt[card["id"] in heavy] += 1

    assert 3.5 < dealt[True] / dealt[False] < 5


def test_a_weighted_draw_still_deals_count_distinct_cards():
    rng = random.Random(3)
    for _ in range(200):
        drawn = games.sample(CARDS, 7, rng=rng, weight=lambda c: c["id"] + 1)
        assert len(drawn) == 7
        assert len({card["id"] for card in drawn}) == 7


def test_no_weight_excludes_a_card():
    """Down-weighted, never excluded: with three heavy cards and a round of
    four, the fourth is a light one -- even at weight zero."""
    cards = CARDS[:5]
    drawn = games.sample(cards, 4, rng=random.Random(2),
                         weight=lambda c: 1 if c["id"] < 3 else 0)

    assert {0, 1, 2} <= {card["id"] for card in drawn}
    assert len(drawn) == 4


def test_a_round_as_long_as_the_selection_deals_everything():
    assert len(games.sample(CARDS, 20, weight=lambda c: 0.2)) == 20


def test_the_heaviest_cards_are_not_always_first():
    """The keys sort heavy cards to the top; without the shuffle every round
    would open with its due words, which is a tell.

    The weights are extreme on purpose. At 1 against 0.2 a light card often
    out-keys a heavy one, so an unshuffled draw would still sometimes open
    light and a check on it could not tell the two apart -- which is how the
    first version of this test passed with the shuffle removed. At 1 against
    0.001 the five heavy cards always take the top five keys, so unshuffled
    they are always first, and shuffled a light card leads about half the
    time."""
    rng = random.Random(4)
    firsts = Counter()
    for _ in range(500):
        drawn = games.sample(CARDS, 10, rng=rng,
                             weight=lambda c: 1 if c["id"] < 5 else 0.001)
        firsts[drawn[0]["id"] < 5] += 1

    assert firsts[False] > 150


# --- recall.draw_weight() ----------------------------------------------------

def test_due_today_and_overdue_and_unseen_all_weigh_one():
    weight = _weight({("acquit", "verb"): TODAY,
                      ("verdict", "noun"): date(2026, 9, 20)})

    assert weight({"word": "acquit", "pos": "verb"}) == recall.DUE_WEIGHT == 1
    assert weight({"word": "verdict", "pos": "noun"}) == 1
    assert weight({"word": "bail", "pos": "noun"}) == recall.UNSEEN_WEIGHT == 1


def test_a_word_scheduled_later_weighs_a_fifth():
    weight = _weight({("acquit", "verb"): date(2026, 10, 5)})

    assert weight({"word": "acquit", "pos": "verb"}) == recall.NOT_DUE_WEIGHT == 0.2


def test_the_card_finds_its_row_the_way_the_schedule_keys_it():
    """Case-insensitive, and a NULL part of speech is ''. `tip` the verb is
    a different word from `tip` the noun, as #101 says."""
    weight = _weight({("Tip", "noun"): date(2026, 10, 5),
                      ("gist", None): date(2026, 10, 5)})

    assert weight({"word": "tip", "pos": "Noun"}) == 0.2
    assert weight({"word": "gist", "pos": None}) == 0.2
    assert weight({"word": "gist"}) == 0.2
    assert weight({"word": "tip", "pos": "verb"}) == 1


# --- the rounds ------------------------------------------------------------------

SENTENCE = "She had to {} the whole task before the end of the week."

DECK = [
    {"id": n, "word": word, "pos": pos, "topic": "Work",
     "translation_ukr": f"ukr {word}", "translation_rus": f"rus {word}",
     "explanation_en": f"a meaning of {word} in plain words",
     "examples_en": [SENTENCE.format(word)]}
    for n, (word, pos) in enumerate([("delegate", "verb"), ("resign", "verb"),
                                     ("appraise", "verb"), ("commute", "verb"),
                                     ("negotiate", "verb")], 1)
]

# Each round whose question is one card, and the URL that deals it.
WEIGHTED = [
    ("quiz", "/quiz?topic=Work&lang=ukr"),
    ("multiple_choice", "/games/multiple_choice/play?topic=Work&lang=ukr"),
    ("scrambled", "/games/scrambled/play?topic=Work"),
    ("fill_the_gap", "/games/fill_the_gap/play?topic=Work"),
    ("spell_it", "/games/spell_it/play?topic=Work"),
    ("rebuild_the_sentence", "/games/rebuild_the_sentence/play?topic=Work"),
    ("listen_and_type", "/games/listen_and_type/play?topic=Work"),
]

# The rounds that keep their own draw, and why.
UNWEIGHTED = {
    "odd_one_out": "builds each question from four words across two topics",
    "real_or_fake": "draws bare words with no part of speech to key on",
    "read_a_text": "sends the selection to a model rather than dealing cards",
}


@pytest.fixture()
def draws(app_module, monkeypatch):
    """Every `games.sample()` call's weight, applied to what it sampled."""
    calls = []
    original = games.sample

    def recording(items, count, rng=None, weight=None):
        calls.append(None if weight is None else
                     {_card(item)["id"]: weight(item) for item in items})
        return original(items, count, rng=rng, weight=weight)

    monkeypatch.setattr("games.sample", recording)
    return calls


def _card(item):
    return item[0] if isinstance(item, tuple) else item


@pytest.fixture()
def schedule(monkeypatch):
    """Card 1 (`delegate`) due today; card 2 (`resign`) due next week; the
    other three never answered."""
    import utils

    def install(rows=None, error=None):
        def due_dates(user_id):
            if error:
                raise error
            return rows if rows is not None else {
                recall.word_key("delegate", "verb"): date(2020, 1, 1),
                recall.word_key("resign", "verb"): date(2099, 1, 1)}
        monkeypatch.setattr(utils, "due_dates", due_dates)
    return install


def test_every_activity_is_either_weighted_or_excluded_for_a_reason():
    """A new activity has to be put on one side of the line."""
    classified = {slug for slug, _ in WEIGHTED} | set(UNWEIGHTED)

    assert classified == set(games.ACTIVITIES)


@pytest.mark.parametrize("slug,url", WEIGHTED, ids=[s for s, _ in WEIGHTED])
def test_a_signed_in_learners_round_is_weighted_by_their_schedule(
        user_client, stub_deck, draws, schedule, slug, url):
    """Due and unseen weigh 1, the word scheduled for next week 0.2 --
    applied to the items each round really samples, pairs included."""
    stub_deck(cards=DECK)
    schedule()
    response = user_client.get(url + "&words=3")

    assert response.status_code == 200
    weighted = [call for call in draws if call is not None]
    assert weighted, f"{slug} dealt without the learner's schedule"
    assert weighted[0] == {1: 1.0, 2: 0.2, 3: 1.0, 4: 1.0, 5: 1.0}


@pytest.mark.parametrize("slug,url", WEIGHTED, ids=[s for s, _ in WEIGHTED])
def test_an_anonymous_round_is_the_uniform_draw(client, stub_deck, draws,
                                               schedule, slug, url):
    stub_deck(cards=DECK)
    schedule()
    client.get(url + "&words=3")

    assert draws and all(call is None for call in draws)


def test_a_learner_with_no_answers_gets_the_uniform_draw(
        user_client, stub_deck, draws, schedule):
    stub_deck(cards=DECK)
    schedule(rows={})
    user_client.get("/games/spell_it/play?topic=Work&words=3")

    assert draws == [None]


def test_an_unreadable_schedule_still_deals_the_round(
        user_client, stub_deck, draws, schedule, caplog):
    """A round that will not deal is worse than one dealt without preference."""
    stub_deck(cards=DECK)
    schedule(error=RuntimeError("the database is not answering"))
    response = user_client.get("/games/spell_it/play?topic=Work&words=3")

    assert response.status_code == 200
    assert draws == [None]
    assert "#480" in caplog.text


def test_grading_a_round_reads_no_schedule(user_client, stub_deck, monkeypatch):
    """The weight is for dealing. A POST grades what was asked, and reading
    the schedule there would be a query for nothing."""
    import utils

    stub_deck(cards=DECK)
    monkeypatch.setattr(utils, "due_dates",
                        lambda user_id: pytest.fail("read the schedule on POST"))
    user_client.post("/games/spell_it/play?topic=Work",
                     data={"answer_1": "delegate"})
