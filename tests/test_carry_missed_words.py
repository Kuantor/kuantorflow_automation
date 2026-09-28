"""Fill the gap: the words you missed come back next round (kuantorflow#337).

*Finish* posts the cards turned over (#484); the unticked ones are stored in
the session and dealt first in the next round, up to half of it. Short-term
by design -- the session, for everybody, and no effect on the SM-2 schedule.

The round-level tests count **distinct carried words in the next deal**, on a
60-card deck with five missed words and a round of ten. Without the feature
the chance of all five turning up is about one in 400,000, so a pass means
the feature ran rather than that the dice were kind.

The half of this that lives in the browser -- *Play again* waiting for the
post -- cannot run here. Its hooks are pinned below and its behaviour was
checked in a browser.
"""

import random
import re
import string

import pytest

import games
import recall
import rounds

WORDS = [f"vex{a}{b}" for a in string.ascii_lowercase[:6]
         for b in string.ascii_lowercase[:10]][:60]
DECK = [{"id": n, "word": w, "pos": "noun", "topic": "Work",
         "examples_en": [f"She had to {w} the whole thing before noon."]}
        for n, w in enumerate(WORDS, 1)]
ROUND = "/games/fill_the_gap/play?topic=Work"


def _key(card):
    return recall.word_key(card["word"], card["pos"])


def _dealt(body):
    return {int(n) for n in
            re.findall(r'class="gap-remember-box" data-card-id="(\d+)"', body)}


def _missed(client):
    with client.session_transaction() as sess:
        return sess.get(games.MISSED_KEY)


# --- the store -------------------------------------------------------------------

def test_the_store_is_replaced_not_appended():
    store = {}
    games.remember_missed(store, [("a", "noun"), ("b", "noun")])
    games.remember_missed(store, [("b", "noun")])

    assert games.missed_words(store) == {("b", "noun")}


def test_the_store_holds_each_word_once_and_is_capped():
    store = {}
    keys = [(f"w{n}", "") for n in range(games.MISSED_CAP + 20)]
    games.remember_missed(store, keys + keys[:5])

    assert len(store[games.MISSED_KEY]) == games.MISSED_CAP


def test_a_damaged_store_is_ignored_not_trusted():
    """It came back from a cookie."""
    store = {games.MISSED_KEY: [["ok", "noun"], "junk", ["too", "many", "x"],
                                [1, 2], None]}

    assert games.missed_words(store) == {("ok", "noun")}
    assert games.missed_words({games.MISSED_KEY: "nonsense"}) == set()


# --- the split -------------------------------------------------------------------

def test_the_split_takes_missed_words_up_to_the_limit():
    items = list(range(20))
    carried, rest = games.split_carried(items, {2, 4, 6, 8, 10, 12}, 4,
                                        key=lambda n: n, rng=random.Random(1))

    assert len(carried) == 4 and set(carried) <= {2, 4, 6, 8, 10, 12}
    assert sorted(carried + rest) == items


def test_missed_words_over_the_limit_go_back_into_the_draw():
    """The two not chosen are not thrown away: they stay in `rest` and can
    still be drawn like any other word."""
    carried, rest = games.split_carried(list(range(10)), {0, 1, 2, 3, 4, 5}, 4,
                                        key=lambda n: n, rng=random.Random(2))

    assert len(set(rest) & {0, 1, 2, 3, 4, 5}) == 2


# --- the finish stores what was missed ----------------------------------------------

def test_finishing_stores_the_unticked_words(user_client, stub_deck):
    stub_deck(cards=DECK)
    user_client.post(ROUND, data={"answer_1": rounds.GAP_REMEMBERED,
                                  "answer_2": "", "answer_3": ""})

    assert _missed(user_client) == [list(_key(DECK[1])), list(_key(DECK[2]))]


def test_an_anonymous_learner_gets_it_too(client, stub_deck):
    """The session, not the log: no account needed."""
    stub_deck(cards=DECK)
    client.post(ROUND, data={"answer_5": ""})

    assert _missed(client) == [list(_key(DECK[4]))]


def test_remembering_a_word_takes_it_off_the_list(client, stub_deck):
    stub_deck(cards=DECK)
    client.post(ROUND, data={"answer_5": "", "answer_6": ""})
    client.post(ROUND, data={"answer_5": rounds.GAP_REMEMBERED, "answer_6": ""})

    assert _missed(client) == [list(_key(DECK[5]))]


# --- the next deal -----------------------------------------------------------------

MISSED_FIVE = {"answer_7": "", "answer_17": "", "answer_27": "",
               "answer_37": "", "answer_47": ""}


def test_the_missed_words_come_back_in_the_next_round(client, stub_deck):
    stub_deck(cards=DECK)
    client.post(ROUND, data=MISSED_FIVE)

    dealt = _dealt(client.get(ROUND).get_data(as_text=True))

    assert {7, 17, 27, 37, 47} <= dealt
    assert len(dealt) == 10


def test_repeats_are_capped_at_half_the_round(client, stub_deck):
    """Eight missed, a round of ten: five come back for certain, and the round
    is still ten long. The other three are drawn like any word, so across
    twenty rounds at least one must come back with **fewer than all eight** --
    which is what separates a cap from forcing every missed word in. (All
    eight by chance, twenty times running, is about one in 10^40.)"""
    stub_deck(cards=DECK)
    client.post(ROUND, data={f"answer_{n}": "" for n in range(1, 9)})

    counts = []
    for _ in range(20):
        dealt = _dealt(client.get(ROUND).get_data(as_text=True))
        assert len(dealt) == 10
        counts.append(len(dealt & set(range(1, 9))))

    assert min(counts) >= 5
    assert min(counts) < 8, "every missed word was forced in: no cap"


def test_the_repeats_are_mixed_in_not_dealt_first(client, stub_deck):
    """Shuffled with the fresh cards, or every round would open with the five
    words the learner just failed -- a tell, and a discouraging one."""
    stub_deck(cards=DECK)
    client.post(ROUND, data=MISSED_FIVE)

    opened_on_a_repeat = 0
    for _ in range(20):
        body = client.get(ROUND).get_data(as_text=True)
        order = [int(n) for n in
                 re.findall(r'class="gap-remember-box" data-card-id="(\d+)"', body)]
        opened_on_a_repeat += set(order[:5]) == {7, 17, 27, 37, 47}

    assert opened_on_a_repeat < 20


def test_a_missed_word_no_longer_in_the_deck_is_dropped(client, stub_deck):
    """It never matches, so it drops out in silence -- and the round is not
    shorter for it."""
    stub_deck(cards=DECK)
    client.post(ROUND, data=MISSED_FIVE)
    stub_deck(cards=[card for card in DECK if card["id"] != 7])

    dealt = _dealt(client.get(ROUND).get_data(as_text=True))

    assert 7 not in dealt
    assert {17, 27, 37, 47} <= dealt
    assert len(dealt) == 10


def test_a_missed_verb_is_not_swapped_for_its_noun(client, stub_deck):
    """Found by playing it: `one_per_word()` keeps one card per *spelling*,
    and the missed list keys on word and part of speech. With `lease` the
    noun and `lease` the verb both in the deck, a learner who missed the verb
    was dealt the noun about half the time and the repeat was lost. The
    missed variant must be the one that survives, every time."""
    deck = DECK + [
        {"id": 100, "word": "lease", "pos": "noun", "topic": "Work",
         "examples_en": ["They signed a lease on the flat last spring."]},
        {"id": 101, "word": "lease", "pos": "verb", "topic": "Work",
         "examples_en": ["They lease the building from the council."]},
    ]
    stub_deck(cards=deck)
    client.post(ROUND, data={"answer_101": ""})

    for _ in range(20):
        dealt = _dealt(client.get(ROUND).get_data(as_text=True))
        assert 101 in dealt, "the missed verb was not dealt"
        assert 100 not in dealt


def test_no_missed_words_is_the_ordinary_draw(client, stub_deck):
    stub_deck(cards=DECK)

    assert len(_dealt(client.get(ROUND).get_data(as_text=True))) == 10


def test_the_schedule_is_not_involved(user_client, stub_deck, monkeypatch):
    """Short-term only: the carried words are a session list. Recording the
    finish still goes to the log (#484) -- this adds nothing to it."""
    recorded = []
    monkeypatch.setattr("utils.record_answers",
                        lambda user_id, game, answers: recorded.append(len(answers)))
    stub_deck(cards=DECK)
    user_client.post(ROUND, data=MISSED_FIVE)
    user_client.get(ROUND)

    assert recorded == [5]


# --- Play again waits for the post (browser half) -------------------------------------

def test_play_again_carries_the_hook_the_wait_attaches_to(client, stub_deck):
    """The waiting itself runs in the browser and was checked there; what the
    suite can pin is that the link is marked and the script waits on it."""
    stub_deck(cards=DECK)
    body = client.get(ROUND).get_data(as_text=True)

    assert "<a data-replay href=" in body
    assert "waitThenGo(again.querySelector(\"[data-replay]\"), saved)" in body
    assert "var REPLAY_WAIT_MS = 1500;" in body
    assert "Promise.race([saved, timeout])" in body
