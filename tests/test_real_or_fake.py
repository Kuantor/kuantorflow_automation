"""
Real or fake — n-gram pseudowords (kuantorflow#132).

Real words from the learner's selection, mixed with words invented by a
character n-gram model over the deck, and the learner says which is which.

The rule the whole file is built around: **an invented word must not be a real
one.** The model is trained on English, so it will sometimes produce English —
`out`, `sent`, `legate`, `embark` all came out of real runs — and a fake that
is really a word is marked wrong for being right, which in a language-learning
app teaches something false. Four filters push back on it (known words, the
cards' own vocabulary, a shared stem, a length floor) and none of them closes
it completely; what they do is make it rare. That limit is deliberate and
documented rather than hidden, and it is why the filters have tests of their
own rather than being trusted.
"""

import random
import re

import pytest

import games


# Sixty words, not six. A trigram over ten words can only hand those ten back,
# and every one of them is rejected for being real — so a small deck invents
# nothing at all, which is true of the app as well and is why the round trains
# on the **whole visible deck** rather than on the topics that were ticked.
REAL = [
    "burglary", "evidence", "custody", "sentence", "verdict", "acquittal",
    "testimony", "prosecute", "defendant", "sentencing", "conviction",
    "magistrate", "probation", "surveillance", "trespass", "forgery",
    "embezzle", "restitution", "arraignment", "indictment", "misconduct",
    "negligence", "plaintiff", "subpoena", "warrant", "custodial",
    "adjourned", "appellate", "prosecutor", "detention", "liability",
    "affidavit", "deposition", "extradite", "injunction", "jurisdiction",
    "manslaughter", "perjury", "precedent", "remanded", "sanction",
    "settlement", "solicitor", "statutory", "tribunal", "acquitted",
    "allegation", "barrister", "clemency", "complainant", "contempt",
    "coroner", "counsel", "custodian", "damages", "defence", "detainee",
    "disclosure", "exonerate", "grievance",
]

CARDS = [{"id": i, "word": word, "topic": "Crime",
          "explanation_en": "a word used in court",
          "examples_en": ["The court reached a verdict."]}
         for i, word in enumerate(REAL, start=1)]


@pytest.fixture()
def deck(stub_deck):
    return stub_deck(cards=CARDS)


def _items(body):
    """(word, is_real) for each thing the round is asking about."""
    words = dict(re.findall(r'name="item_(\d+)" value="([^"]+)"', body))
    truth = dict(re.findall(r'name="real_(\d+)" value="(\d)"', body))
    return [(words[i], truth[i] == "1") for i in sorted(words, key=int)]


# --- inventing a word ---------------------------------------------------


def test_an_invented_word_is_never_one_of_the_words_it_learned_from():
    """The model is built from these, so handing one back is its likeliest
    output — and it would be marked wrong for being right."""
    out = games.pseudowords(REAL, 30, random.Random(3))
    assert not (set(out) & {w.lower() for w in REAL})


def test_a_word_the_cards_use_anywhere_is_not_invented():
    """`known` is the cards' own English — explanations and examples — which is
    where the common short words a trigram stumbles onto actually live."""
    out = games.pseudowords(REAL, 30, random.Random(3),
                            known={"burglar", "sentenced", "verdicts"})
    assert "burglar" not in out and "sentenced" not in out


def test_nothing_shorter_than_the_floor_is_offered():
    """Short output is where the model collides with real English."""
    out = games.pseudowords(REAL, 40, random.Random(9))
    assert all(len(w) >= games.MIN_INVENTED_LENGTH for w in out), out


def test_a_word_sharing_a_stem_with_a_real_one_is_rejected():
    """The model recombines real morphemes, so it invents `litigate` from
    `litigation`. A shared opening is a blunt way of catching that, and it is
    the filter that took the error rate from about one in five to rare."""
    out = games.pseudowords(REAL, 40, random.Random(9))
    stems = {w[:games.STEM_LENGTH] for w in REAL
             if len(w) >= games.STEM_LENGTH}
    assert not {w[:games.STEM_LENGTH] for w in out} & stems


def test_every_invented_word_has_a_vowel():
    """`plimber` is arguable; `blkstr` is spotted without knowing English."""
    out = games.pseudowords(REAL, 40, random.Random(5))
    assert all(set(w) & games.VOWELS for w in out), out


def test_invented_words_do_not_repeat():
    out = games.pseudowords(REAL, 30, random.Random(4))
    assert len(out) == len(set(out))


def test_expressions_are_not_trained_on_or_invented():
    """"Is this a real *word*" is not the question being asked about `take for
    granted`, and a page where half the entries have spaces gives itself
    away."""
    out = games.pseudowords(REAL + ["take for granted"], 20, random.Random(6))
    assert all(" " not in w for w in out)


def test_a_deck_with_nothing_to_learn_from_invents_nothing():
    """Fewer than asked for rather than looping forever — a real possibility
    for a small or repetitive deck."""
    assert games.pseudowords([], 10, random.Random(1)) == []
    assert games.pseudowords(["take for granted"], 10, random.Random(1)) == []


def test_the_same_seed_invents_the_same_words():
    """Injectable randomness, so a failure can be reproduced."""
    assert games.pseudowords(REAL, 8, random.Random(42)) == \
        games.pseudowords(REAL, 8, random.Random(42))


# --- the cards' vocabulary ----------------------------------------------


def test_the_vocabulary_reads_explanations_and_examples():
    """Examples alone gave about six hundred words over the seeded deck and let
    `author` through; the explanations are the larger half."""
    vocab = games.vocabulary([
        {"word": "verdict", "explanation_en": "a decision reached by a jury",
         "examples_en": ["The jury delivered its verdict."]}])
    assert {"verdict", "decision", "jury", "delivered"} <= vocab


def test_the_vocabulary_strips_punctuation_and_case():
    vocab = games.vocabulary([
        {"word": "x", "explanation_en": "", "examples_en": ["Stop! (Really.)"]}])
    assert "stop" in vocab and "really" in vocab


def test_the_vocabulary_survives_a_card_with_nothing_on_it():
    assert games.vocabulary([{"word": None, "explanation_en": None,
                              "examples_en": None}]) == set()


# --- the round ----------------------------------------------------------


def test_a_round_mixes_real_words_with_invented_ones(client, deck):
    body = client.get("/games/real_or_fake/play?topic=Crime&words=10") \
                 .get_data(as_text=True)
    items = _items(body)
    assert len(items) == 10
    assert any(real for _, real in items)
    assert any(not real for _, real in items)


def test_the_real_words_come_from_the_selection(client, deck):
    body = client.get("/games/real_or_fake/play?topic=Crime&words=10") \
                 .get_data(as_text=True)
    reals = [w for w, real in _items(body) if real]
    assert set(reals) <= set(REAL)


def test_a_word_is_not_asked_about_twice(client, deck):
    """#101 keeps one card per word *and part of speech*, so a word that is
    both a noun and a verb is two cards — and the same word twice on a page is
    a free mark that looks like a mistake."""
    body = client.get("/games/real_or_fake/play?topic=Crime&words=10") \
                 .get_data(as_text=True)
    words = [w.lower() for w, _ in _items(body)]
    assert len(words) == len(set(words))


def test_both_halves_share_a_length_floor(client, deck):
    """The fakes cannot be shorter than the floor, so a shorter real word would
    be a giveaway in the opposite direction: every short word would be real."""
    body = client.get("/games/real_or_fake/play?topic=Crime&words=10") \
                 .get_data(as_text=True)
    assert all(len(w) >= games.MIN_INVENTED_LENGTH for w, _ in _items(body))


def test_a_selection_too_thin_for_a_round_says_so(client, stub_deck):
    stub_deck(cards=[{"id": 1, "word": "cat", "topic": "Crime",
                      "explanation_en": "", "examples_en": []}])
    body = client.get("/games/real_or_fake/play?topic=Crime") \
                 .get_data(as_text=True)
    assert "enough words here for a round" in body


# --- grading ------------------------------------------------------------


def _answer(items, strategy):
    data = {}
    for index, (word, real) in enumerate(items, start=1):
        data[f"item_{index}"] = word
        data[f"real_{index}"] = "1" if real else "0"
        data[f"answer_{index}"] = strategy(real)
    return data


def test_answering_every_one_correctly_scores_full_marks(client, deck):
    items = _items(client.get("/games/real_or_fake/play?topic=Crime&words=10")
                   .get_data(as_text=True))
    body = client.post("/games/real_or_fake/play?topic=Crime",
                       data=_answer(items, lambda real: "real" if real else "fake")
                       ).get_data(as_text=True)
    assert f"Score: {len(items)} / {len(items)}" in body


def test_answering_every_one_wrongly_scores_nothing(client, deck):
    items = _items(client.get("/games/real_or_fake/play?topic=Crime&words=10")
                   .get_data(as_text=True))
    body = client.post("/games/real_or_fake/play?topic=Crime",
                       data=_answer(items, lambda real: "fake" if real else "real")
                       ).get_data(as_text=True)
    assert f"Score: 0 / {len(items)}" in body


def test_calling_everything_real_scores_only_the_real_ones(client, deck):
    items = _items(client.get("/games/real_or_fake/play?topic=Crime&words=10")
                   .get_data(as_text=True))
    body = client.post("/games/real_or_fake/play?topic=Crime",
                       data=_answer(items, lambda real: "real")
                       ).get_data(as_text=True)
    assert f"Score: {sum(1 for _, real in items if real)} / {len(items)}" in body


def test_the_results_keep_the_order_the_round_asked(client, deck):
    """Numbered, so "3. wrong" has to mean the third thing they judged."""
    items = _items(client.get("/games/real_or_fake/play?topic=Crime&words=10")
                   .get_data(as_text=True))
    body = client.post("/games/real_or_fake/play?topic=Crime",
                       data=_answer(items, lambda real: "real")
                       ).get_data(as_text=True)
    shown = [w.strip() for w in
             re.findall(r'<div class="word">\d+\.\s*([^<]+)</div>', body)]
    assert shown == [w for w, _ in items]


def test_the_results_say_which_it_actually_was(client, deck):
    items = _items(client.get("/games/real_or_fake/play?topic=Crime&words=10")
                   .get_data(as_text=True))
    body = client.post("/games/real_or_fake/play?topic=Crime",
                       data=_answer(items, lambda real: "real")
                       ).get_data(as_text=True)
    assert "was invented for this round" in body
    assert "is a real word" in body


def test_the_answers_travel_with_the_question(client, deck):
    """Half of them were invented a moment ago and are in no database, so a
    POST could not look them up."""
    body = client.get("/games/real_or_fake/play?topic=Crime&words=6") \
                 .get_data(as_text=True)
    assert body.count('name="item_') == 6
    assert body.count('name="real_') == 6
