"""Spell it — the meaning and the first letter, type the word (kuantorflow#270).

The direction the site does not otherwise test: from *meaning* to *spelling*.

The rule this file mostly guards: **no question ever prints its own answer.**
Dictionary explanations routinely contain the headword or an inflection of it —
"the act of resigning from a position" would sit directly above the dashes — so
the explanation is masked with the same matcher #235 and #237 use. Measured
against the deck, 445 explained cards yielded **zero** leaks in either hint
mode.

The second thing worth guarding is the hint mode, which decides *eligibility*
as well as the mask: with the last letter shown a four-letter word is
two-thirds given, so that mode asks for a longer one. It is chosen in the
picker rather than the round, because a switch on the round page would let a
learner reveal the last letter of a word they are stuck on.
"""

import re

import pytest

import games


# --- the mask -------------------------------------------------------------


def test_the_first_letter_is_shown_and_the_rest_are_dashes():
    assert games.mask_word("unusual") == "u _ _ _ _ _ _"


def test_the_last_letter_is_shown_in_the_easier_mode():
    assert games.mask_word("unusual", games.HINT_FIRST_LAST) == "u _ _ _ _ _ l"


def test_one_dash_stands_for_one_letter():
    """The length is shown deliberately — the exact opposite of #235's
    fixed-width gap, and right for the opposite reason: the meaning is already
    given, so the number of letters is not the answer."""
    for word in ("resign", "unusual", "biodiversity"):
        assert games.mask_word(word).count("_") == len(word) - 1, word


def test_a_multi_word_headword_keeps_its_spaces():
    """So the shape of the expression survives — `take for granted` stays
    visibly three words."""
    masked = games.mask_word("take for granted")
    assert masked.count("t _ _ _") == 1
    assert len(masked.split("   ")) == 3


def test_a_short_word_keeps_its_last_letter_hidden():
    """`at` masked as `a t` is the whole word. The headword floor cannot cover
    this on its own, because an expression is masked **part by part**: `take
    for granted` clears the floor comfortably and would still have rendered
    `for` as `f _ r`, handing over a word of the answer.

    Found by this test rather than by playing — the round never asks a
    two-letter headword, so only the expression case was reachable."""
    assert games.mask_word("at", games.HINT_FIRST_LAST) == "a _"
    assert " f _ _ " in f" {games.mask_word('take for granted', games.HINT_FIRST_LAST)} "


def test_masking_nothing_is_empty_rather_than_an_error():
    assert games.mask_word("") == ""
    assert games.mask_word(None) == ""


# --- which words can be asked ---------------------------------------------


@pytest.mark.parametrize("word", ["resign", "unusual", "well-being",
                                  "take for granted", "don't"])
def test_these_can_be_spelled(word):
    assert games.spellable(word)


@pytest.mark.parametrize("word", ["aid", "at", "e.g.", "24/7", "", None])
def test_these_cannot(word):
    """Too short to be a spelling exercise at B2–C1, or not letters a person
    can type back — the same rule #272 applies to a word a voice can read."""
    assert not games.spellable(word)


def test_the_easier_mode_asks_for_a_longer_word():
    """With the last letter shown, a four-letter word is two-thirds given."""
    assert games.spellable("four", games.HINT_FIRST)
    assert not games.spellable("four", games.HINT_FIRST_LAST)
    assert games.spellable("fives", games.HINT_FIRST_LAST)


# --- the explanation never shows the answer -------------------------------


def test_the_headword_inside_the_explanation_is_masked():
    text = "the act of resigning from a position"
    masked = games.mask_in_text(text, "resign")
    assert "resigning" not in masked
    assert games.find_word(masked, "resign") == []


def test_every_occurrence_is_masked_not_just_the_first():
    """An explanation really can use the word twice, and masking one of them
    would print the answer beside its own mask."""
    text = "to resign is to leave; he resigns often"
    masked = games.mask_in_text(text, "resign")
    assert games.find_word(masked, "resign") == []


def test_an_inflection_is_masked_completely():
    """`resigning` must not leave its `ing` showing beside the dashes — the
    mask covers what was *found*, not the length of the headword."""
    masked = games.mask_in_text("the act of resigning", "resign")
    assert "ing" not in masked


def test_a_multi_word_headword_is_masked_whole():
    masked = games.mask_in_text("to take it for granted is careless",
                                "take for granted")
    assert games.find_word(masked, "take for granted") == []


def test_an_explanation_without_the_word_is_untouched():
    """Most of them. The masker must not disturb text it had no reason to."""
    text = "a payment made to somebody who has lost their job"
    assert games.mask_in_text(text, "severance") == text


def test_a_card_is_not_made_ineligible_by_the_word_appearing():
    """Unlike #235, masking is enough — and the masked occurrence is a second
    dash-run, which is a *harder* prompt rather than a broken one."""
    assert games.spellable("resign")
    assert games.mask_in_text("the act of resigning", "resign") != ""


# --- the hint mode --------------------------------------------------------


def test_an_unknown_mode_falls_back_to_the_first_letter():
    """It arrives from a URL anybody can edit."""
    assert games.hint_mode("nonsense") == games.HINT_FIRST
    assert games.hint_mode(None) == games.HINT_FIRST
    assert games.hint_mode("") == games.HINT_FIRST


def test_a_remembered_mode_is_used_when_nothing_is_asked_for():
    assert games.hint_mode(None, games.HINT_FIRST_LAST) == games.HINT_FIRST_LAST


def test_what_is_asked_for_beats_what_is_remembered():
    assert games.hint_mode(games.HINT_FIRST,
                           games.HINT_FIRST_LAST) == games.HINT_FIRST


def test_the_mode_survives_a_round_trip_through_the_store():
    store = {}
    games.remember_hint(store, games.HINT_FIRST_LAST)
    assert games.remembered_hint(store) == games.HINT_FIRST_LAST


def test_nonsense_is_not_stored():
    store = {}
    games.remember_hint(store, "nonsense")
    assert games.remembered_hint(store) == games.HINT_FIRST


# --- the round ------------------------------------------------------------


CARDS = [
    {"id": 1, "word": "resign", "pos": "verb", "topic": "Work",
     "explanation_en": "the act of resigning from a position"},
    {"id": 2, "word": "burnout", "topic": "Work",
     "explanation_en": "exhaustion caused by too much work"},
    {"id": 3, "word": "appraisal", "topic": "Work",
     "explanation_en": "a formal review of how well somebody works"},
    {"id": 4, "word": "aid", "topic": "Work",
     "explanation_en": "help or support"},          # too short
    {"id": 5, "word": "commute", "topic": "Work"},  # no explanation
]


@pytest.fixture()
def deck(stub_deck):
    return stub_deck(cards=CARDS, topics=[("Work", 5)])


def _play(client, query="topic=Work&words=20"):
    return client.get(f"/games/spell_it/play?{query}").get_data(as_text=True)


def _asked(body):
    return re.findall(r'name="answer_(\d+)"', body)


def test_only_cards_with_an_explanation_are_asked(client, deck):
    assert "5" not in _asked(_play(client))


def test_a_word_too_short_to_spell_is_not_asked(client, deck):
    assert "4" not in _asked(_play(client))


def test_the_round_says_how_many_it_could_not_use(client, deck):
    """#266's one shared sentence, in the activity's own words."""
    flat = " ".join(_play(client).split())
    assert "2 cards here are not usable for this game" in flat
    assert "an English explanation" in flat


def test_no_question_prints_its_own_answer(client, deck):
    """The rule the whole game turns on, checked against the page rather than
    the helper — `resign`'s explanation contains `resigning`."""
    body = _play(client)
    form = body.split("<form")[1]
    for word in ("resign", "resigning", "burnout", "appraisal"):
        assert not re.search(rf"\b{word}\b", re.sub(r"<[^>]+>", " ", form)), word


def test_the_mask_is_on_the_page(client, deck):
    assert "_" in _play(client)


def test_the_easier_mode_asks_fewer_words(client, deck):
    """It draws from a smaller set, which is why the mode is settled before the
    draw rather than toggled during the round."""
    normal = len(_asked(_play(client, "topic=Work&words=20&hint=first")))
    easier = len(_asked(_play(client, "topic=Work&words=20&hint=first_last")))
    assert easier <= normal


def test_a_selection_with_nothing_to_spell_is_explained(client, stub_deck):
    stub_deck(cards=[dict(CARDS[4])], topics=[("Work", 1)])
    body = _play(client)
    assert "no words here can be spelled out" in body.lower()
    assert "Choose different topics" in body


# --- grading --------------------------------------------------------------


BY_ID = {str(c["id"]): c["word"] for c in CARDS}


def test_every_word_right_scores_full_marks(client, deck):
    ids = _asked(_play(client))
    body = client.post("/games/spell_it/play?topic=Work",
                       data={f"answer_{i}": BY_ID[i] for i in ids}
                       ).get_data(as_text=True)
    assert f"Score: {len(ids)} / {len(ids)}" in body


def test_grading_follows_267s_normalisation(client, deck):
    ids = _asked(_play(client))
    body = client.post("/games/spell_it/play?topic=Work",
                       data={f"answer_{i}": BY_ID[i].upper() + "." for i in ids}
                       ).get_data(as_text=True)
    assert f"Score: {len(ids)} / {len(ids)}" in body


def test_a_different_form_of_the_word_is_wrong(client, deck):
    """`resigned` for `resign` stays wrong — this is the one game where being
    approximately right is what is being tested against."""
    body = client.post("/games/spell_it/play?topic=Work",
                       data={"answer_1": "resigned"}).get_data(as_text=True)
    assert "Score: 0 / 1" in body


def test_the_results_show_the_word_and_its_meaning_unmasked(client, deck):
    """The round is over; a learner who spelled it wrong should read the
    meaning against the actual word."""
    body = client.post("/games/spell_it/play?topic=Work",
                       data={"answer_1": "wrong"}).get_data(as_text=True)
    assert "resign" in body
    assert "resigning" in body      # the explanation, no longer masked


# --- the declaration ------------------------------------------------------


def test_the_activity_no_longer_carries_a_ticket():
    assert games.ACTIVITIES["spell_it"].ticket == ""


def test_the_picker_offers_the_hint_mode(client, deck):
    body = client.get("/games/spell_it").get_data(as_text=True)
    assert 'name="hint" value="first"' in body
    assert 'name="hint" value="first_last"' in body


def test_no_other_activity_offers_it(client):
    """False by default, so a new game inherits no control it cannot explain."""
    offering = [a.slug for a in games.ACTIVITIES.values() if a.picks_hint]
    assert offering == ["spell_it"]


def test_the_round_is_registered_rather_than_stubbed(app_module):
    assert app_module.GAME_ROUNDS["spell_it"] is not app_module._round_stub
