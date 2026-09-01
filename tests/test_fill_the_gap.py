"""Fill the gap (kuantorflow#235): a word cut out of its own example.

The front of a card is a real dictionary example with the card's word removed;
the flip reveals the word. Two things carry the whole game and both are tested
here rather than assumed:

* **no sentence is ever shown ungapped.** A card that gives away its own answer
  is worse than a card that is missing, so a pair whose word cannot be located
  is skipped in favour of another;
* the word is found by `games.find_word()` — the matcher built for #237 —
  because the example rarely holds the headword verbatim.

The scoring is self-marked and deliberately **written nowhere**, which is the
other property worth pinning: it would be an easy thing to "improve" into a
database write later.
"""

import re

import pytest

import games
import settings_store

PLAY = "/games/fill_the_gap/play"


def card(word, examples, **extra):
    base = {"id": abs(hash(word)) % 10000, "word": word, "pos": "verb",
            "topic": "Work", "examples_en": list(examples),
            "explanation_en": None,
            "translation_ukr": None, "translation_rus": None}
    base.update(extra)
    return base


PLAYABLE = [
    card("resign", ["He resigned from the board."],
         explanation_en="to give up a job"),
    card("apply", ["She applies for every job."], explanation_en="to make a request"),
    card("plan", ["They are planning a protest."], explanation_en="to arrange"),
]


def sentences(body):
    return re.findall(r'<p class="gap-sentence">(.*?)</p>', body, re.S)


def words(body):
    return [w.strip() for w in
            re.findall(r'<div class="deck-word">\s*([^<]+)', body)]


# --- the gap itself ---------------------------------------------------------

def test_the_word_is_cut_out_of_its_own_example(client, stub_deck):
    stub_deck(cards=PLAYABLE)
    body = client.get(PLAY).get_data(as_text=True)
    for sentence in sentences(body):
        assert games.GAP in sentence


def test_an_inflected_word_is_still_found(client, stub_deck):
    """"He resigned from the board" holds no `resign`, which is the whole
    reason this game needed #237's matcher before it could exist."""
    stub_deck(cards=[PLAYABLE[0]])
    body = client.get(PLAY).get_data(as_text=True)
    assert "resigned" not in body.split("flip-front")[1].split("flip-back")[0]
    assert games.GAP in sentences(body)[0]


def test_a_card_whose_example_lacks_its_word_is_skipped(client, stub_deck):
    """Never render an ungapped sentence — play a different card instead."""
    stub_deck(cards=[
        card("ubiquitous", ["Nothing here matches the headword at all."]),
        PLAYABLE[0],
    ])
    body = client.get(PLAY).get_data(as_text=True)
    assert len(sentences(body)) == 1
    assert "ubiquitous" not in body


def test_a_card_with_no_examples_cannot_play(client, stub_deck):
    stub_deck(cards=[card("resign", [])])
    body = client.get(PLAY).get_data(as_text=True)
    assert sentences(body) == []
    assert "example sentence" in body


def test_every_occurrence_goes(client, stub_deck):
    """One gap and one plain copy would print the answer beside its own
    blank — real data does this, and a single stored example can hold two
    sentences using the word twice."""
    stub_deck(cards=[card("curious",
                          ["She was curious. It was a curious little shop."])])
    body = client.get(PLAY).get_data(as_text=True)
    assert "curious" not in sentences(body)[0]
    assert sentences(body)[0].count(games.GAP) == 2


def test_an_expression_is_gapped_whole(client, stub_deck):
    stub_deck(cards=[card("take for granted", ["She takes it for granted."])])
    body = client.get(PLAY).get_data(as_text=True)
    assert sentences(body)[0].count(games.GAP) == 1
    assert "granted" not in sentences(body)[0]


def test_the_gap_does_not_measure_the_answer(client, stub_deck):
    """A gap as wide as the word is a free hint, and the flip is the reveal."""
    stub_deck(cards=[card("resign", ["He resigned from the board."]),
                     card("internationalisation",
                          ["Internationalisation is hard."])])
    body = client.get(PLAY).get_data(as_text=True)
    gaps = {s.count("_") for s in sentences(body)}
    assert len(gaps) == 1


# --- the reveal -------------------------------------------------------------

def test_the_explanation_is_preferred(client, stub_deck):
    stub_deck(cards=[card("resign", ["He resigned."],
                          explanation_en="to give up a job",
                          translation_ukr="zvilnyatysya")])
    body = client.get(PLAY).get_data(as_text=True)
    assert "to give up a job" in body
    assert "zvilnyatysya" not in body


def test_without_one_the_translation_follows_quiz_lang(user_client, stub_deck):
    """#113's setting, not the card deck's Ukrainian-first rule — two rules for
    one question drift apart."""
    stub_deck(cards=[card("resign", ["He resigned."],
                          translation_ukr="ukr-word", translation_rus="rus-word")])
    user_client.post("/settings", json={"quiz_lang": "russian"})
    body = user_client.get(PLAY).get_data(as_text=True)
    assert "rus-word" in body and "ukr-word" not in body


def test_a_hidden_language_falls_back_to_the_visible_one(user_client, stub_deck):
    """#46/#79: a preference for a language hidden in Settings cannot be
    honoured, and the other visible one is the answer."""
    stub_deck(cards=[card("resign", ["He resigned."],
                          translation_ukr="ukr-word", translation_rus="rus-word")])
    user_client.post("/settings", json={"quiz_lang": "russian",
                                        "show_russian": False})
    body = user_client.get(PLAY).get_data(as_text=True)
    assert "ukr-word" in body and "rus-word" not in body


def test_a_card_with_neither_still_plays(client, stub_deck):
    """The word was the answer, so revealing it alone is a valid reveal —
    this must not make the card ineligible."""
    stub_deck(cards=[card("resign", ["He resigned."])])
    body = client.get(PLAY).get_data(as_text=True)
    assert len(sentences(body)) == 1
    assert "resign" in words(body)


# --- round length -----------------------------------------------------------

def test_the_round_length_is_the_setting(user_client, stub_deck):
    """No literal ten anywhere: the number is `gapped_deck_size`."""
    stub_deck(cards=[card(f"word{i}", [f"A word{i} in a sentence."])
                     for i in range(40)])
    user_client.post("/settings", json={"gapped_deck_size": 6})
    assert len(sentences(user_client.get(PLAY).get_data(as_text=True))) == 6


def test_the_default_is_the_stores_default(client, stub_deck):
    stub_deck(cards=[card(f"word{i}", [f"A word{i} in a sentence."])
                     for i in range(40)])
    body = client.get(PLAY).get_data(as_text=True)
    assert len(sentences(body)) == settings_store.DEFAULTS["gapped_deck_size"]


def test_a_short_selection_plays_what_it_has_and_says_so(client, stub_deck):
    """Refusing a round because a topic yields seven usable cards instead of
    ten would be the wrong call."""
    stub_deck(cards=PLAYABLE)
    body = client.get(PLAY).get_data(as_text=True)
    assert len(sentences(body)) == 3
    assert "all we could make" in body


@pytest.mark.parametrize("asked", [1, 999, "abc"])
def test_an_impossible_setting_falls_back(user_client, stub_deck, asked):
    """`sanitize()` guards the store, so the round never has to."""
    stub_deck(cards=[card(f"word{i}", [f"A word{i} in a sentence."])
                     for i in range(40)])
    user_client.post("/settings", json={"gapped_deck_size": asked})
    body = user_client.get(PLAY).get_data(as_text=True)
    assert len(sentences(body)) == settings_store.DEFAULTS["gapped_deck_size"]


# --- scoring, and what is not written down ----------------------------------

def test_the_round_is_self_marked_and_finishable_at_any_point(client, stub_deck):
    stub_deck(cards=PLAYABLE)
    body = client.get(PLAY).get_data(as_text=True)
    assert body.count("gap-remember-box") >= len(sentences(body))
    assert 'id="gap-count"' in body      # the running count
    assert 'id="gap-finish"' in body     # available from the first card


def test_playing_writes_nothing(client, stub_deck, saved, action_logs):
    """#233's rule about a game that records a score does not apply to a game
    that records nothing — and this is what keeps that true."""
    stub_deck(cards=PLAYABLE)
    for _ in range(3):
        client.get(PLAY)
    assert saved == []
    assert not (action_logs / "cards.log").exists()


# --- it is a real game now --------------------------------------------------

def test_the_activity_is_no_longer_a_stub():
    assert games.ACTIVITIES["fill_the_gap"].ticket == ""


def test_a_card_can_grow_to_the_text_on_it(client, stub_deck):
    """kuantorflow#401, and a coupling assertion because pytest cannot see a
    rendered card.

    A long explanation used to be drawn *outside* the card -- half above its
    top edge and half below, since the face centres its content. `min-height`
    would have let the card grow; what stopped it was `position: absolute` on
    the faces, which takes them out of flow so their content cannot size
    anything. The absolute positioning was there to stack the two faces for
    the flip, and a grid cell stacks them just as well while letting the
    taller one set the height.

    Measured on the real deck at 375px before the fix: eight of Sport and
    competition's twenty cards overflowed, `handicap` by 125px. After it,
    none of thirty did, front and back matched on every card, and every card
    at 1280px was 240px exactly as before.

    Both pages share this stylesheet, so both are asserted here -- the game's
    card carries more on its back than the deck's does, which is what made it
    the likelier of the two to overflow.
    """
    stub_deck(cards=PLAYABLE)
    game = client.get(PLAY).get_data(as_text=True)
    deck = client.get("/deck/Work").get_data(as_text=True)

    for page in (game, deck):
        assert "grid-area: 1 / 1" in page, "the faces are no longer stacked"
        assert "position: absolute; inset: 0" not in page, (
            "an absolute face cannot make the card taller, which is the bug")


def test_the_flip_is_the_card_decks_own(client, stub_deck):
    """Shared, not copied (#78/#235): both pages extend deck.html, so the
    animation exists once. Two implementations would diverge the first time
    either was touched."""
    stub_deck(cards=PLAYABLE)
    game = client.get(PLAY).get_data(as_text=True)
    deck = client.get("/deck/Work").get_data(as_text=True)
    for marker in ("flip-card-inner", "rotateY(180deg)", 'id="deck-anim"'):
        assert marker in game, marker
        assert marker in deck, marker
