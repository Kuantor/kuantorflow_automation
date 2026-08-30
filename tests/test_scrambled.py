"""
Scrambled — the Cambridge effect (kuantorflow#133).

First and last letters held, the middle shuffled, the learner types the word
back. The first game under #233 to have a real round rather than a stub.

The rule everything here circles: **a word that cannot be scrambled is not
asked.** `cat` has no middle, `book`'s middle is two of the same letter, and
`noon` shuffles to itself however the dice fall. Showing any of them unchanged
would put the answer on screen as the question, which is worse than a shorter
round — so `scramble()` returns None and the round filters on it, rather than
returning the original and hoping a caller notices.
"""

import collections
import random
import re

import pytest

import games


CARDS = [
    {"id": 1, "word": "delegate", "topic": "Work"},
    {"id": 2, "word": "resign", "topic": "Work"},
    {"id": 3, "word": "burnout", "topic": "Work"},
    {"id": 4, "word": "cat", "topic": "Work"},          # no middle
    {"id": 5, "word": "noon", "topic": "Work"},         # shuffles to itself
    {"id": 6, "word": "take for granted", "topic": "Work"},
]


@pytest.fixture()
def deck(stub_deck):
    """The count comes from the cards, so it cannot drift from them."""
    return stub_deck(cards=CARDS)


def _asked(body):
    return re.findall(r'name="answer_(\d+)"', body)


def _shown(body):
    return [w.strip() for w in
            re.findall(r'<div class="word">\d+\.\s*([^<]+)</div>', body)]


# --- the scrambler ------------------------------------------------------


def test_the_first_and_last_letters_are_held():
    """The shape a reader recognises survives; only the inside is disturbed."""
    for word in ("because", "ambiguous", "streamline", "delegate"):
        out = games.scramble(word, random.Random(7))
        assert out[0] == word[0] and out[-1] == word[-1], word


def test_a_scramble_is_an_anagram_of_its_word():
    for word in ("because", "ambiguous", "streamline"):
        out = games.scramble(word, random.Random(3))
        assert collections.Counter(out) == collections.Counter(word), word


def test_a_scramble_actually_differs_from_the_word():
    """#133 asks for this outright, and it is the whole point: an unchanged
    word is the answer, printed as the question."""
    for word in ("because", "ambiguous", "streamline", "delegate", "resign"):
        for seed in range(12):
            assert games.scramble(word, random.Random(seed)) != word, word


@pytest.mark.parametrize("word", ["", "a", "at", "cat", "book", "noon", "aaaa"])
def test_a_word_that_cannot_differ_comes_back_as_none(word):
    """None rather than the original — see this module's docstring. Three
    letters have no middle; `book` and `noon` have a middle of one repeated
    letter, so every shuffle of it is the word again."""
    assert games.scramble(word, random.Random(1)) is None


def test_an_expression_keeps_its_shape_and_word_count():
    """A card's word may be a phrase, and scrambling it whole would lose the
    spaces that make it readable as one."""
    out = games.scramble_entry("take for granted", random.Random(5))
    assert len(out.split()) == 3
    assert out.split()[1] == "for", "too short to scramble, so left alone"
    assert out != "take for granted"


def test_an_expression_of_only_short_words_cannot_be_scrambled():
    assert games.scramble_entry("up to now", random.Random(5)) is None


def test_scrambling_nothing_is_none_rather_than_an_error():
    assert games.scramble_entry("", random.Random(1)) is None
    assert games.scramble_entry("   ", random.Random(1)) is None


# --- the round ----------------------------------------------------------


def test_the_round_asks_only_words_it_could_scramble(client, deck):
    """`cat` and `noon` are in the deck and must not be asked."""
    body = client.get("/games/scrambled/play?topic=Work&words=20").get_data(as_text=True)
    assert sorted(_asked(body)) == ["1", "2", "3", "6"]


def test_no_word_is_ever_shown_unchanged(client, deck):
    """The failure this game has to avoid, checked against the round rather
    than the function."""
    body = client.get("/games/scrambled/play?topic=Work&words=20").get_data(as_text=True)
    assert "delegate" not in _shown(body)
    assert "resign" not in _shown(body)


def test_the_round_says_how_many_words_were_too_short(client, deck):
    """The picker counts cards, so a round shorter than the count looks like a
    bug unless it says otherwise — the same reason the quiz reports cards with
    no translation."""
    body = client.get("/games/scrambled/play?topic=Work&words=20").get_data(as_text=True)
    flat = " ".join(body.split())
    # kuantorflow#266 made this sentence shared by every round, and it now
    # names what the game needs in the activity's own words.
    assert "2 cards here are not usable for this game" in flat
    assert "four letters or more" in flat


def test_the_round_length_follows_the_word_count(client, deck):
    body = client.get("/games/scrambled/play?topic=Work&words=2").get_data(as_text=True)
    assert len(_asked(body)) == 2


def test_a_selection_with_nothing_scrambleable_says_so(client, app_module,
                                                       monkeypatch, deck):
    monkeypatch.setattr(app_module, "get_flashcards_by_topics",
                        lambda topics, owner_id=None, **kw: [dict(CARDS[3]),
                                                       dict(CARDS[4])])
    body = client.get("/games/scrambled/play?topic=Work").get_data(as_text=True)
    assert "No words here can be scrambled yet" in body
    # One page for "this selection cannot produce a round" (#266), with
    # the picker a click away and the selection still ticked.
    assert "Choose different topics" in body


# --- grading ------------------------------------------------------------


def _play(client, words=20):
    body = client.get(f"/games/scrambled/play?topic=Work&words={words}") \
                 .get_data(as_text=True)
    return _asked(body), _shown(body)


def _answers(ids, by_id, wrong=()):
    return {f"answer_{i}": ("zzz" if i in wrong else by_id[i]) for i in ids}


BY_ID = {str(c["id"]): c["word"] for c in CARDS}


def test_every_word_right_scores_full_marks(client, deck):
    ids, _ = _play(client)
    body = client.post("/games/scrambled/play?topic=Work",
                       data=_answers(ids, BY_ID)).get_data(as_text=True)
    assert f"Score: {len(ids)} / {len(ids)}" in body


def test_a_wrong_word_costs_a_mark_and_reveals_the_answer(client, deck):
    ids, _ = _play(client)
    body = client.post("/games/scrambled/play?topic=Work",
                       data=_answers(ids, BY_ID, wrong={ids[0]})
                       ).get_data(as_text=True)
    assert f"Score: {len(ids) - 1} / {len(ids)}" in body
    assert BY_ID[ids[0]] in body


def test_grading_ignores_case(client, deck):
    """Typing is the mechanic; capitalisation is not what is being tested."""
    ids, _ = _play(client)
    shouted = {f"answer_{i}": BY_ID[i].upper() for i in ids}
    body = client.post("/games/scrambled/play?topic=Work",
                       data=shouted).get_data(as_text=True)
    assert f"Score: {len(ids)} / {len(ids)}" in body


def test_grading_ignores_surrounding_space(client, deck):
    ids, _ = _play(client)
    padded = {f"answer_{i}": f"  {BY_ID[i]} " for i in ids}
    body = client.post("/games/scrambled/play?topic=Work",
                       data=padded).get_data(as_text=True)
    assert f"Score: {len(ids)} / {len(ids)}" in body


def test_the_results_show_the_puzzle_that_was_actually_asked(client, deck):
    """The round is a random sample *and* the shuffle is random, so nothing on
    the results page could be rebuilt from the card alone — the puzzle travels
    with the answer."""
    ids, shown = _play(client)
    data = _answers(ids, BY_ID)
    data.update({f"scrambled_{i}": s for i, s in zip(ids, shown)})
    body = client.post("/games/scrambled/play?topic=Work",
                       data=data).get_data(as_text=True)
    assert shown[0] in body


def test_grading_marks_what_was_asked_rather_than_a_fresh_draw(client, deck):
    """A re-draw on POST would mark answers against words the learner never
    saw — the same rule the quiz follows."""
    body = client.post("/games/scrambled/play?topic=Work",
                       data={"answer_1": "delegate"}).get_data(as_text=True)
    assert "Score: 1 / 1" in body


# --- it is no longer a stub ---------------------------------------------


def test_scrambled_no_longer_carries_a_ticket(client, deck):
    """The field is present while an activity is a stub and removed when it
    lands, so the stub page can name its ticket."""
    assert games.ACTIVITIES["scrambled"].ticket == ""
    body = client.get("/games/scrambled/play?topic=Work").get_data(as_text=True)
    assert "built yet" not in body


def test_the_results_offer_a_way_out_as_well_as_another_round(client, deck):
    """The row at the top of the page has one, but a learner reading their
    score is at the bottom of ten answers."""
    ids, _ = _play(client)
    body = client.post("/games/scrambled/play?topic=Work",
                       data=_answers(ids, BY_ID)).get_data(as_text=True)
    row = body.split('<p class="crumbs">')[-1].split("</p>")[0]
    assert "Play again" in row
    assert 'href="/"' in row


def test_playing_again_keeps_the_round_the_same_length(client, deck):
    """The same defect the real-or-fake results had (kuantorflow#132)."""
    played = "/games/scrambled/play?topic=Work&words=3"
    ids = _asked(client.get(played).get_data(as_text=True))
    body = client.post(played, data=_answers(ids, BY_ID)).get_data(as_text=True)
    row = body.split('<p class="crumbs">')[-1].split("</p>")[0]
    assert "words=3" in row
