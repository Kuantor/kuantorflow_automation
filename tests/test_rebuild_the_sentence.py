"""Rebuild the sentence — the words of an example, shuffled (kuantorflow#271).

Not #133 with bigger pieces. Scrambled shuffles letters inside a word and
trains spelling; this shuffles words inside a sentence and trains **word
order**, which is where Ukrainian- and Russian-speaking learners actually lose
marks.

**The tap interaction is not tested here and cannot be.** Moving a chip is
browser behaviour; what pytest can see is the markup it starts from and the
grading it ends in. Both were checked in a real browser instead — building the
sentence by tapping produced the right hidden field, tapping a placed chip
returned it to the pool, and every chip is `type="button"` so a tap cannot
submit the round. Recorded on the PR.

What is covered here: the sentence rules, which are pure and are where the
subtle decisions live, and the grading, which is on the server precisely so
that it *can* be covered.
"""

import random
import re

import pytest

import games


def _rng(seed=0):
    return random.Random(seed)


SENTENCE = "The jury acquitted him of murder."


# --- turning a sentence into chips ----------------------------------------


def test_the_words_become_chips():
    assert games.sentence_tokens(SENTENCE) == [
        "The", "jury", "acquitted", "him", "of", "murder"]


def test_the_terminal_full_stop_is_removed():
    """It is punctuation rather than a word, and a chip reading `murder.`
    announces itself as the end of the sentence — half the giveaway, removed
    for nothing."""
    assert "murder" in games.sentence_tokens(SENTENCE)
    assert "murder." not in games.sentence_tokens(SENTENCE)


@pytest.mark.parametrize("mark", [".", "!", "?", "..."])
def test_any_terminal_mark_is_removed(mark):
    assert games.sentence_tokens(f"one two three four five{mark}")[-1] == "five"


def test_internal_punctuation_stays_attached_to_its_token():
    """A comma inside a clause is part of where that clause goes. Moving it
    separately is how a real sentence becomes a wrong one."""
    tokens = games.sentence_tokens("He was, in the end, entirely wrong")
    assert "was," in tokens and "end," in tokens


def test_the_opening_capital_is_left_alone():
    """Lowercasing it would mangle every sentence opening with a proper noun or
    *I*, and the app cannot reliably tell which those are. A learner who uses
    the capital to find the start has still had to order everything after it."""
    assert games.sentence_tokens(SENTENCE)[0] == "The"


@pytest.mark.parametrize("sentence", [
    "Too short here.",                       # 3 tokens
    "She resigned.",                         # 2
    "a b c d e f g h i j k l m n o p",       # 16
    "", "   ", None,
])
def test_a_sentence_of_the_wrong_size_is_refused(sentence):
    """Four words is not a puzzle; twenty-five is an afternoon."""
    assert games.sentence_tokens(sentence) is None


def test_the_bounds_themselves_are_accepted():
    assert games.sentence_tokens(" ".join(["w"] * games.SENTENCE_MIN))
    assert games.sentence_tokens(" ".join(["w"] * games.SENTENCE_MAX))


# --- shuffling ------------------------------------------------------------


def test_the_shuffle_is_never_the_original_order():
    """The same subtlety `scramble()` documents: a pool that comes out in the
    right order is a question whose answer is already on screen."""
    tokens = games.sentence_tokens(SENTENCE)
    for seed in range(50):
        assert games.shuffle_tokens(tokens, _rng(seed)) != tokens


def test_the_shuffle_keeps_every_word():
    tokens = games.sentence_tokens(SENTENCE)
    for seed in range(20):
        assert sorted(games.shuffle_tokens(tokens, _rng(seed))) == sorted(tokens)


def test_tokens_that_cannot_differ_are_refused():
    """None rather than the original, so the caller filters instead of having
    to notice."""
    assert games.shuffle_tokens(["a"] * 6, _rng(1)) is None


# --- choosing an example --------------------------------------------------


def test_the_first_usable_example_is_taken():
    sentence, chips = games.rebuildable([SENTENCE], _rng(1))
    assert sentence == "The jury acquitted him of murder"
    assert sorted(chips) == sorted(sentence.split())


def test_an_example_of_the_wrong_size_is_skipped_for_one_that_fits():
    assert games.rebuildable(["Too short.", SENTENCE], _rng(1))[0] \
        == "The jury acquitted him of murder"


def test_a_card_with_no_usable_example_is_none():
    assert games.rebuildable(["Too short.", "Also short."], _rng(1)) is None
    assert games.rebuildable([], _rng(1)) is None
    assert games.rebuildable(None, _rng(1)) is None


def test_the_examples_are_tried_in_a_random_order():
    """So a card with two usable sentences is not the same question every
    round."""
    both = ["The jury acquitted him of murder.",
            "She was offered the job on Tuesday."]
    seen = {games.rebuildable(both, _rng(s))[0] for s in range(20)}
    assert len(seen) == 2, seen


# --- the round ------------------------------------------------------------


CARDS = [
    {"id": 1, "word": "acquit", "topic": "Law",
     "examples_en": ["The jury acquitted him of murder."]},
    {"id": 2, "word": "parole", "topic": "Law",
     "examples_en": ["He was released on parole after two years."]},
    {"id": 3, "word": "arson", "topic": "Law",
     "examples_en": ["Short one."]},          # too short
    {"id": 4, "word": "verdict", "topic": "Law"},   # no examples
]


@pytest.fixture()
def deck(stub_deck):
    return stub_deck(cards=CARDS, topics=[("Law", 4)])


def _play(client, query="topic=Law&words=20"):
    return client.get(f"/games/rebuild_the_sentence/play?{query}") \
                 .get_data(as_text=True)


def _questions(body):
    found = {}
    for block in body.split('class="panel question rebuild"')[1:]:
        card = re.search(r'name="sentence_(\d+)"', block).group(1)
        found[card] = {
            "sentence": re.search(r'name="sentence_\d+"\s+value="([^"]*)"',
                                  block).group(1),
            "chips": re.findall(r'class="chip">([^<]*)</button>', block),
        }
    return found


def test_only_cards_with_a_usable_example_are_asked(client, deck):
    asked = _questions(_play(client))
    assert set(asked) == {"1", "2"}


def test_the_round_says_how_many_it_could_not_use(client, deck):
    flat = " ".join(_play(client).split())
    assert "2 cards here are not usable for this game" in flat
    assert "example sentence" in flat


def test_the_chips_are_the_sentence_shuffled(client, deck):
    for question in _questions(_play(client)).values():
        assert sorted(question["chips"]) == sorted(question["sentence"].split())
        assert question["chips"] != question["sentence"].split()


def test_the_answer_line_starts_empty(client, deck):
    """Nothing is placed for the learner."""
    body = _play(client)
    assert 'class="rebuild-answer" value=""' in body


def test_every_chip_is_a_button_that_cannot_submit(client, deck):
    """`type="button"` matters more than it looks: without it a chip inside a
    form is a submit button, and the first tap would send the round."""
    body = _play(client)
    chips = re.findall(r'<button[^>]*class="chip"[^>]*>', body)
    assert chips
    assert all('type="button"' in chip for chip in chips)


def test_the_page_says_so_when_scripting_is_off(client, deck):
    """The chips cannot move without it, so the page must not look merely
    broken."""
    assert "<noscript>" in _play(client)


def test_a_selection_with_no_usable_sentence_is_explained(client, stub_deck):
    stub_deck(cards=[dict(CARDS[2]), dict(CARDS[3])], topics=[("Law", 2)])
    body = _play(client)
    assert "has a sentence to rebuild" in body
    assert "Choose different topics" in body


# --- grading, which is on the server --------------------------------------


def _grade(client, answers):
    data = {}
    for card, question in answers.items():
        data[f"sentence_{card}"] = question["sentence"]
        data[f"answer_{card}"] = question["given"]
    return client.post("/games/rebuild_the_sentence/play?topic=Law",
                       data=data).get_data(as_text=True)


def test_the_right_order_scores(client, deck):
    asked = _questions(_play(client))
    for q in asked.values():
        q["given"] = q["sentence"]
    assert f"Score: {len(asked)} / {len(asked)}" in _grade(client, asked)


def test_the_wrong_order_does_not(client, deck):
    asked = _questions(_play(client))
    for q in asked.values():
        q["given"] = " ".join(reversed(q["sentence"].split()))
    assert f"Score: 0 / {len(asked)}" in _grade(client, asked)


def test_a_doubled_space_between_chips_cannot_fail_a_correct_sentence(client,
                                                                      deck):
    """#267's normalisation on both sides — the learner assembled the right
    words in the right order and the join is not their problem."""
    asked = _questions(_play(client))
    for q in asked.values():
        q["given"] = "  ".join(q["sentence"].split())
    assert f"Score: {len(asked)} / {len(asked)}" in _grade(client, asked)


def test_an_empty_line_is_wrong_rather_than_an_error(client, deck):
    asked = _questions(_play(client))
    for q in asked.values():
        q["given"] = ""
    assert f"Score: 0 / {len(asked)}" in _grade(client, asked)


def test_a_repeated_word_accepts_either_arrangement(client, stub_deck):
    """The reason grading compares the **assembled string** rather than chip
    positions: a sentence with `the` twice has two genuinely interchangeable
    chips, and grading by position would mark one of two identical words wrong
    for sitting in the other's slot."""
    stub_deck(cards=[{"id": 9, "word": "x", "topic": "Law",
                      "examples_en": ["the cat sat on the mat"]}],
              topics=[("Law", 1)])
    asked = _questions(_play(client))
    for q in asked.values():
        q["given"] = "the cat sat on the mat"
    assert "Score: 1 / 1" in _grade(client, asked)


def test_grading_marks_what_was_asked(client, deck):
    body = client.post("/games/rebuild_the_sentence/play?topic=Law",
                       data={"answer_1": "The jury acquitted him of murder",
                             "sentence_1": "The jury acquitted him of murder"}
                       ).get_data(as_text=True)
    assert "Score: 1 / 1" in body


def test_the_results_show_the_sentence_as_written(client, deck):
    body = client.post("/games/rebuild_the_sentence/play?topic=Law",
                       data={"answer_1": "wrong order entirely",
                             "sentence_1": "The jury acquitted him of murder"}
                       ).get_data(as_text=True)
    assert "The jury acquitted him of murder" in body
    assert "wrong order entirely" in body


# --- the declaration ------------------------------------------------------


def test_the_activity_no_longer_carries_a_ticket():
    assert games.ACTIVITIES["rebuild_the_sentence"].ticket == ""


def test_no_activity_is_a_stub_any_more():
    """#271 was the last one. Every tile on the front page now leads to a real
    round."""
    assert [a.slug for a in games.ACTIVITIES.values() if a.ticket] == []


def test_the_round_is_registered_rather_than_stubbed(app_module):
    assert (app_module.GAME_ROUNDS["rebuild_the_sentence"]
            is not app_module._round_stub)
