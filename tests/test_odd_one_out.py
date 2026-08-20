"""Odd one out — three words from one topic, and a stranger (kuantorflow#269).

The one game built on the deck's own **structure** rather than on what a card
holds: it needs a word and the topic it lives in, and nothing else. So it is
also the one wave-two game with no card-level rule (#266), and the only one
whose eligibility question is about *topics* rather than cards.

Almost everything here is offline. `odd_one_out()` takes a `{topic: [word]}`
mapping and a `{topic: section}` mapping and returns a question — no request,
no database — which is what lets the two rules that keep a question answerable
be tested directly rather than inferred from a page.

Those two rules are what this file mostly guards, and both come from the same
fact: **a word can honestly belong to two topics.**
"""

import random
import re

import pytest
from werkzeug.datastructures import MultiDict

import games


BY_TOPIC = {
    "Work": ["delegate", "resign", "burnout", "commute", "appraisal"],
    "Law": ["verdict", "parole", "arson", "acquit"],
    "Money": ["revenue", "arrears", "deposit"],
}
SECTIONS = {"Work": "Business", "Money": "Business", "Law": "Society"}


def _rng(seed=0):
    return random.Random(seed)


# --- building one question ------------------------------------------------


def test_a_question_is_three_words_from_one_topic_and_one_from_another():
    q = games.odd_one_out(BY_TOPIC, SECTIONS, _rng(3))
    assert len(q["words"]) == 4
    home = set(BY_TOPIC[q["home"]])
    assert len([w for w in q["words"] if w in home]) == games.GROUP == 3
    assert q["answer"] in BY_TOPIC[q["intruder_topic"]]
    assert q["answer"] in q["words"]


def test_the_four_words_are_distinct():
    for seed in range(40):
        q = games.odd_one_out(BY_TOPIC, SECTIONS, _rng(seed))
        assert len({w.casefold() for w in q["words"]}) == 4, q


def test_the_stranger_is_not_always_in_the_same_place():
    """Shuffled, or its position would be the answer."""
    seen = {games.odd_one_out(BY_TOPIC, SECTIONS, _rng(s))["words"].index(
        games.odd_one_out(BY_TOPIC, SECTIONS, _rng(s))["answer"])
        for s in range(40)}
    assert len(seen) > 1, seen


def test_a_word_in_both_topics_is_never_the_stranger():
    """The rule that keeps a question answerable rather than merely hard.

    #101 keeps one card per word *and part of speech*, so the same word really
    can sit in two topics — and drawing it as the stranger asks the learner to
    spot something that is not true."""
    shared = {"A": ["work", "delegate", "resign", "burnout"],
              "B": ["work", "verdict"]}
    for seed in range(200):
        q = games.odd_one_out(shared, rng=_rng(seed))
        if q and q["home"] == "A":
            assert q["answer"].casefold() != "work", q


def test_a_stranger_from_another_section_is_preferred():
    """#236's difficulty knob, taken at the easy end: *Sport* against *Law* is
    a fair question, *Business* against *Money* is a coin flip."""
    picked = [games.odd_one_out(BY_TOPIC, SECTIONS, _rng(s))
              for s in range(60)]
    from_law = [q for q in picked if q["home"] == "Work"]
    assert from_law, "no question ever used Work as its home"
    assert all(q["intruder_topic"] == "Law" for q in from_law), \
        "Work's stranger should come from Law, the only other section"


def test_a_same_section_stranger_is_accepted_when_that_is_all_there_is():
    """Rather than refusing to build a question — a learner who ticked two
    neighbouring topics asked for exactly that."""
    same = {"Work": ["delegate", "resign", "burnout"],
            "Money": ["revenue", "arrears"]}
    q = games.odd_one_out(same, {"Work": "Business", "Money": "Business"},
                          _rng(1))
    assert q is not None
    assert q["intruder_topic"] != q["home"]


def test_sections_are_optional():
    """The preference simply does not fire — a topic missing from the map, or
    no map at all, must not stop a question being built."""
    assert games.odd_one_out(BY_TOPIC, None, _rng(1)) is not None
    assert games.odd_one_out(BY_TOPIC, {}, _rng(1)) is not None


# --- when a question cannot be built --------------------------------------


def test_one_topic_cannot_produce_a_stranger():
    """However many cards it holds — which is the whole reason this activity
    declares `min_topics = 2` (#266)."""
    assert games.odd_one_out({"Work": ["a", "b", "c", "d", "e"]},
                             rng=_rng(1)) is None


def test_a_home_topic_needs_three_words():
    assert games.odd_one_out({"A": ["x", "y"], "B": ["z", "w"]},
                             rng=_rng(1)) is None


def test_nothing_at_all_is_none_rather_than_an_error():
    assert games.odd_one_out({}, rng=_rng(1)) is None


def test_a_second_topic_of_only_shared_words_cannot_supply_a_stranger():
    shared = {"A": ["one", "two", "three"], "B": ["one", "two"]}
    assert games.odd_one_out(shared, rng=_rng(1)) is None


# --- a round --------------------------------------------------------------


def test_a_round_asks_for_what_it_was_given():
    assert len(games.odd_one_out_round(BY_TOPIC, 5, SECTIONS, _rng(2))) == 5


def test_a_round_never_repeats_the_same_four_words():
    asked = games.odd_one_out_round(BY_TOPIC, 12, SECTIONS, _rng(4))
    keys = [frozenset(w.casefold() for w in q["words"]) for q in asked]
    assert len(keys) == len(set(keys)), keys


def test_a_thin_selection_plays_what_it_can():
    """Fewer than asked is not an error — refusing a round because it yields
    seven questions instead of ten would be the wrong call."""
    thin = {"A": ["one", "two", "three"], "B": ["four"]}
    asked = games.odd_one_out_round(thin, 10, rng=_rng(1))
    assert 0 < len(asked) < 10


def test_a_selection_that_can_build_nothing_returns_nothing():
    assert games.odd_one_out_round({"A": ["x"]}, 10, rng=_rng(1)) == []


# --- grouping the cards ---------------------------------------------------


def test_cards_are_grouped_by_their_topic():
    cards = [{"word": "delegate", "topic": "Work"},
             {"word": "verdict", "topic": "Law"}]
    assert games.by_topic(cards) == {"Work": ["delegate"], "Law": ["verdict"]}


def test_the_same_word_twice_in_a_topic_is_kept_once():
    """#101 keeps a card per word *and part of speech*, so `work` the noun and
    `work` the verb are two cards — and the same word twice among four options
    is a free mark and looks like a mistake."""
    cards = [{"word": "work", "pos": "noun", "topic": "Work"},
             {"word": "work", "pos": "verb", "topic": "Work"}]
    assert games.by_topic(cards) == {"Work": ["work"]}


def test_a_card_with_no_topic_or_no_word_is_skipped():
    cards = [{"word": "delegate", "topic": ""}, {"word": "", "topic": "Work"},
             {"word": None, "topic": None}]
    assert games.by_topic(cards) == {}


# --- the round on the page ------------------------------------------------


CARDS = ([{"id": i, "word": w, "topic": "Work"}
          for i, w in enumerate(["delegate", "resign", "burnout", "commute"], 1)]
         + [{"id": i, "word": w, "topic": "Law"}
            for i, w in enumerate(["verdict", "parole", "arson"], 10)])


@pytest.fixture()
def deck(stub_deck):
    return stub_deck(cards=CARDS, topics=[("Work", 4), ("Law", 3)])


def _play(client, query="topic=Work&topic=Law&words=4"):
    return client.get(f"/games/odd_one_out/play?{query}").get_data(as_text=True)


def _groups(body):
    found = {}
    for name, value in re.findall(r'name="answer_(\d+)"\s+value="([^"]*)"', body):
        found.setdefault(name, []).append(value)
    return found


def test_every_question_offers_four_words(client, deck):
    for index, words in _groups(_play(client)).items():
        assert len(words) == 4, (index, words)


def test_the_answer_is_not_visible_in_the_question(client, deck):
    """It travels in a hidden field because the draw is random and could not be
    rebuilt on POST — but it must not be readable in the rendered text."""
    body = _play(client)
    visible = " ".join(re.sub(r"<[^>]+>", " ", body.split("<form")[1]).split())
    assert "intruder" not in visible


def test_one_topic_is_explained_rather_than_played(client, deck):
    """#266's `min_topics` gate, which this activity is the reason for."""
    body = _play(client, "topic=Work&words=4")
    assert "at least 2 topics" in body
    assert "Choose different topics" in body


def test_grading_scores_what_was_asked(client, deck):
    body = _play(client)
    data = []
    for index in _groups(body):
        answer = re.search(rf'name="intruder_{index}" value="([^"]*)"',
                           body).group(1)
        data.append((f"answer_{index}", answer))
        data.append((f"intruder_{index}", answer))
    graded = client.post("/games/odd_one_out/play",
                         data=MultiDict(data))
    text = graded.get_data(as_text=True)
    assert f"Score: {len(data) // 2} / {len(data) // 2}" in text


def test_a_wrong_pick_is_marked_and_the_stranger_named(client, deck):
    body = _play(client)
    index = sorted(_groups(body))[0]
    answer = re.search(rf'name="intruder_{index}" value="([^"]*)"',
                       body).group(1)
    graded = client.post("/games/odd_one_out/play", data=MultiDict([
        (f"answer_{index}", "definitely-not-it"),
        (f"intruder_{index}", answer),
        (f"home_{index}", "Work"), (f"from_{index}", "Law"),
    ])).get_data(as_text=True)
    assert "Score: 0 / 1" in graded
    assert "The stranger was" in graded
    assert answer in graded


def test_the_results_name_the_topic_of_every_word(client, deck):
    """The teaching moment. A word can honestly belong to two topics, so the
    game says what *this deck's* grouping was rather than leaving the learner
    to argue with the page."""
    graded = client.post("/games/odd_one_out/play", data=MultiDict([
        ("answer_1", "verdict"), ("intruder_1", "verdict"),
        ("home_1", "Work"), ("from_1", "Law"),
        ("word_1", "delegate"), ("word_1", "resign"),
        ("word_1", "burnout"), ("word_1", "verdict"),
    ])).get_data(as_text=True)
    assert graded.count("Work") >= 3      # the three home words
    assert "Law" in graded                # and the stranger's topic


# --- the declaration ------------------------------------------------------


def test_the_activity_no_longer_carries_a_ticket():
    assert games.ACTIVITIES["odd_one_out"].ticket == ""


def test_it_still_declares_two_topics():
    assert games.ACTIVITIES["odd_one_out"].min_topics == 2


def test_it_asks_nothing_of_a_card():
    """The one wave-two game with no card-level rule — every card has a word
    and a topic, so #266's shortfall sentence never fires here."""
    assert games.ACTIVITIES["odd_one_out"].needs == ""


def test_the_round_is_registered_rather_than_stubbed(app_module):
    assert app_module.GAME_ROUNDS["odd_one_out"] is not app_module._round_stub
