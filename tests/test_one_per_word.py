"""A round never asks the same word twice (kuantorflow#334 follow-up).

Reported from play: *Fill the gap* asked "tipped the waiter" twice in one
round. Two compounding causes, both in the data — #101 keeps one card per word
*and part of speech*, so `tip` is a noun card and a verb card, and the deck
holds true duplicates besides (two identical `tip` nouns). 131 words in the
local deck are held by more than one card.

**Four rounds had the defect and three already had the fix written out
inline**, which is what #266 exists to stop. There is now one helper, and these
tests cover it and the rounds together — a round-level test per game, because
the helper being right proves nothing about a round that forgot to call it.
"""

import re

import pytest

import games


DUPES = [
    {"id": 39, "word": "tip", "pos": "noun", "topic": "general",
     "translation_ukr": "порада", "explanation_en": "a useful suggestion",
     "examples_en": ["Here are my top tips for interview success."]},
    {"id": 40, "word": "tip", "pos": "verb", "topic": "general",
     "translation_ukr": "давати чайові", "explanation_en": "to give money",
     "examples_en": ["They tended to tip heavily in restaurants."]},
    {"id": 41, "word": "tip", "pos": "noun", "topic": "general",
     "translation_ukr": "порада", "explanation_en": "a useful suggestion",
     "examples_en": ["Here are my top tips for interview success."]},
    {"id": 42, "word": "resign", "pos": "verb", "topic": "general",
     "translation_ukr": "звільнятися", "explanation_en": "to leave a job",
     "examples_en": ["He decided to resign from the board."]},
]


# --- the helper -----------------------------------------------------------


def test_a_word_held_by_several_cards_is_kept_once():
    kept = games.one_per_word(DUPES)
    assert [c["id"] for c in kept] == [39, 42]


def test_the_first_of_each_word_wins():
    """Rather than a random pick: the caller has usually shuffled already, and
    choosing again here would be a second source of randomness for no gain."""
    assert games.one_per_word(DUPES)[0]["id"] == 39
    assert games.one_per_word(list(reversed(DUPES)))[0]["id"] == 42


def test_case_does_not_make_a_different_word():
    cards = [{"word": "Tip"}, {"word": "tip"}, {"word": "TIP"}]
    assert len(games.one_per_word(cards)) == 1


def test_surrounding_space_does_not_either():
    assert len(games.one_per_word([{"word": "tip"}, {"word": "  tip "}])) == 1


def test_a_card_with_no_word_is_dropped():
    kept = games.one_per_word([{"word": ""}, {"word": None}, {}, {"word": "x"}])
    assert [c["word"] for c in kept] == ["x"]


def test_it_takes_any_iterable():
    """Two callers pass a generator over `(card, made)` pairs from
    `games.playable()` rather than a list."""
    assert len(games.one_per_word(c for c in DUPES)) == 2


def test_it_does_not_touch_what_it_was_given():
    cards = [dict(c) for c in DUPES]
    games.one_per_word(cards)
    assert len(cards) == 4


# --- every round that draws cards ------------------------------------------
#
# `resign` rather than `tip` for the shared word: six letters, so it clears
# *Scrambled*'s four-letter floor and *Spell it*'s. With `tip` those two rounds
# dropped it as ineligible and the test passed whether or not the dedupe was
# there -- checked by disabling the helper, which is the only way to find a
# vacuous test.


SHARED = [
    {"id": 1, "word": "resign", "pos": "verb", "topic": "general",
     "translation_ukr": "звільнятися", "explanation_en": "to leave a job",
     "examples_en": ["He decided to resign from the board this year."]},
    {"id": 2, "word": "resign", "pos": "noun", "topic": "general",
     "translation_ukr": "відставка", "explanation_en": "the act of leaving",
     "examples_en": ["She announced her resign to the board this year."]},
    {"id": 3, "word": "burnout", "pos": "noun", "topic": "general",
     "translation_ukr": "вигорання", "explanation_en": "exhaustion from work",
     "examples_en": ["Burnout is common among junior doctors these days."]},
]


@pytest.fixture()
def shared(stub_deck):
    return stub_deck(cards=SHARED, topics=[("general", 3)])


ROUNDS = [
    ("fill_the_gap", ""),
    ("scrambled", "&words=20"),
    ("spell_it", "&words=20"),
    ("rebuild_the_sentence", "&words=20"),
    ("multiple_choice", "&words=20"),
    ("listen_and_type", "&words=20"),
]


@pytest.mark.parametrize("slug,extra", ROUNDS, ids=[r[0] for r in ROUNDS])
def test_no_round_asks_the_same_word_twice(client, shared, slug, extra):
    """Parameterised over every game that draws from the cards, because the
    helper being right proves nothing about a round that forgot to call it --
    which is exactly how three of these shipped without it.

    Counted as **questions**, which every game shows one of per card: with two
    `resign` cards and one `burnout`, a round that does not dedupe asks three
    and a round that does asks two. **Confirmed to fail with the helper
    disabled** -- five of the six do; multiple choice cannot build a third
    question from so small a pool either way, and its own file covers its
    dedupe directly."""
    url = f"/games/{slug}/play?topic=general{extra}"
    body = client.get(url).get_data(as_text=True)
    # Distinct **card ids**, not field occurrences: rebuild_the_sentence
    # emits two fields per question and would otherwise count double.
    ids = set(re.findall(r'name="(?:answer|sentence)_(\d+)"', body))
    asked = len(ids) or body.count('class="gap-sentence"')
    assert asked <= 2, f"{slug} asked {asked} questions for 2 distinct words"


def test_the_duplicate_is_not_reported_as_unusable(client, shared):
    """`dropped` is printed beside what the game *needs*, so a duplicate must
    not land in it -- it is usable, just already asked (#272)."""
    body = client.get("/games/spell_it/play?topic=general&words=20")                  .get_data(as_text=True)
    assert "not usable for this game" not in " ".join(body.split())
