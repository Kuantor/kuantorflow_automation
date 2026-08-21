"""Letters shown beside the gap (kuantorflow#334).

*Fill the gap* can show the first letter of the missing word, or the first and
the last. Three decisions shaped it, and each is a test here:

* **the length is implied, never stated** — the run is about half the letters,
  floored at three and capped at seven, so a long word does not hide behind a
  stub while the exact count stays withheld. This is where #334 parts company
  with #270, which shows one dash per letter *because* the learner has already
  been told the meaning.
* **an expression is masked word by word**, like #270 and unlike the single gap
  this game used before — so the word count shows and the letter count does
  not.
* **`none` is the default**, and reproduces the old behaviour exactly. The game
  existed for months without a hint; falling back to one would change it for
  everyone who never asked.
"""

import re

import pytest

import games


SENTENCE = "He decided to resign from his job."


# --- the mask -------------------------------------------------------------


def test_no_hint_is_the_gap_this_game_always_had():
    assert games.mask_gap("resign", games.HINT_NONE) == games.GAP


def test_the_first_letter_is_shown_with_a_fixed_run():
    assert games.mask_gap("resign", games.HINT_FIRST) == "r___"


def test_the_last_letter_joins_it_in_the_other_mode():
    assert games.mask_gap("resign", games.HINT_FIRST_LAST) == "r___n"


def test_a_longer_word_gets_a_longer_run():
    """A fixed three was tried first and looked absurd behind a long word —
    `n___d` standing in for *neighbourhood*. The run now implies the size."""
    short = games.mask_gap("resign", games.HINT_FIRST_LAST)
    long_ = games.mask_gap("neighbourhood", games.HINT_FIRST_LAST)
    assert short.count("_") < long_.count("_")


def test_the_run_is_never_the_letter_count():
    """Implying the size is not stating it. Halved, the run cannot be read as
    a dash per letter — which is the line between this and #270's mask."""
    for word in ("resign", "curriculum", "neighbourhood", "aesthetic"):
        run = games.mask_gap(word, games.HINT_FIRST).count("_")
        assert run != len(word), word


def test_several_word_lengths_share_a_run():
    """What stops it being a count. In the middle of the range a run covers two
    lengths; at the ends the clamps collapse several together."""
    assert games.gap_run(9) == games.gap_run(10)
    assert games.gap_run(2) == games.gap_run(6)
    assert games.gap_run(13) == games.gap_run(14)


def test_the_run_stays_within_its_bounds():
    """Floored so a two-letter word still reads as a gap, capped so a very long
    one does not stretch the line."""
    for letters in range(1, 40):
        assert games.GAP_RUN_MIN <= len(games.gap_run(letters)) <= games.GAP_RUN_MAX


def test_a_six_letter_word_is_unchanged_from_the_first_cut():
    """`resign` sat at three underscores before the run began to scale, and it
    still does — the change lifts long words rather than moving everything."""
    assert games.mask_gap("resign", games.HINT_FIRST_LAST) == "r___n"


def test_the_run_is_underscores_and_not_dots():
    """Three dots *are* countable and would be read as three letters — the
    worst of both. Underscores also keep the hinted and unhinted modes looking
    like the same game."""
    assert "…" not in games.mask_gap("resign", games.HINT_FIRST)
    assert "..." not in games.mask_gap("resign", games.HINT_FIRST)


# --- expressions ----------------------------------------------------------


def test_an_expression_is_masked_word_by_word():
    """The word count shows; the letter count does not."""
    assert games.mask_gap("take for granted", games.HINT_FIRST_LAST) \
        == "t___e   f___   g____d"


def test_a_short_word_in_an_expression_keeps_its_last_letter_hidden():
    """`for` is three letters, and both ends of a three-letter word is most of
    the word — whether or not the reader knows how short it is."""
    masked = games.mask_gap("take for granted", games.HINT_FIRST_LAST)
    assert "f___" in masked and "f___r" not in masked


def test_an_expression_still_gets_one_plain_gap_with_no_hint():
    """Nothing about the old behaviour changes when no hint is asked for — not
    even for expressions, which the single gap covered whole."""
    assert games.mask_gap("take for granted", games.HINT_NONE) == games.GAP


def test_masking_nothing_is_a_plain_gap_rather_than_an_error():
    for value in ("", "   ", None):
        assert games.mask_gap(value, games.HINT_FIRST) == games.GAP


# --- in a sentence --------------------------------------------------------


def test_the_sentence_keeps_the_plain_gap_by_default():
    assert games.gap_sentence(SENTENCE, "resign") \
        == "He decided to ______ from his job."


def test_the_sentence_carries_the_letters_when_asked():
    assert games.gap_sentence(SENTENCE, "resign", games.HINT_FIRST_LAST) \
        == "He decided to r___n from his job."


def test_the_letters_come_from_what_was_matched_not_the_headword():
    """The span may be an inflection, and the mask covers what was cut out —
    so `resigned` gives `r____d`, not `r___n`. Note the run is a letter longer
    too: it scales with what was matched, which is eight letters rather than
    six."""
    assert games.gap_sentence("He resigned last year.", "resign",
                              games.HINT_FIRST_LAST) == "He r____d last year."


def test_an_expression_with_an_object_shows_its_shape():
    """`find_word()` matches an expression whole, object included, so per-word
    masking reveals that something sits inside it. More structure than the
    headword implies, and the honest rendering of what was cut out."""
    gapped = games.gap_sentence("He takes it for granted.", "take for granted",
                                games.HINT_FIRST)
    assert "t___" in gapped and "i___" in gapped and "g___" in gapped


def test_every_occurrence_is_hinted_the_same_way():
    """#235's rule survives: a sentence using the word twice must not print the
    answer beside its own gap, and both gaps get the same treatment."""
    gapped = games.gap_sentence("To resign is to resign yourself.", "resign",
                                games.HINT_FIRST)
    assert gapped.count("r___") == 2
    assert games.find_word(gapped, "resign") == []


# --- choosing the mode ----------------------------------------------------


def test_the_gap_defaults_to_no_hint():
    """The game existed for months without one. Falling back to a hint would
    change it for everyone who never asked."""
    assert games.hint_mode(None, allowed=games.GAP_HINTS,
                           default=games.HINT_NONE) == games.HINT_NONE


def test_spell_it_still_defaults_to_the_first_letter():
    """The other game's fallback must not have moved."""
    assert games.hint_mode(None) == games.HINT_FIRST


def test_spell_it_will_not_accept_no_hint():
    """It has no such mode — a bare "type the word for this meaning" is a
    different exercise."""
    assert games.hint_mode(games.HINT_NONE) == games.HINT_FIRST


def test_nonsense_from_a_url_falls_back():
    assert games.hint_mode("sneaky", allowed=games.GAP_HINTS,
                           default=games.HINT_NONE) == games.HINT_NONE


def test_the_two_games_remember_separately():
    """Sharing one key was considered and refused: asking for the last letter
    in *Spell it* would silently soften *Fill the gap*, a different game the
    learner did not touch."""
    store = {}
    games.remember_hint(store, games.HINT_FIRST_LAST)
    games.remember_hint(store, games.HINT_NONE, games.GAP_HINT_KEY,
                        games.GAP_HINTS, games.HINT_NONE)
    assert games.remembered_hint(store) == games.HINT_FIRST_LAST
    assert games.remembered_hint(store, games.GAP_HINT_KEY, games.GAP_HINTS,
                                 games.HINT_NONE) == games.HINT_NONE


# --- the round and the picker ---------------------------------------------


CARDS = [
    {"id": 1, "word": "resign", "topic": "Work",
     "examples_en": ["He decided to resign from his job."]},
    {"id": 2, "word": "burnout", "topic": "Work",
     "examples_en": ["Burnout is common among junior doctors."]},
]


@pytest.fixture()
def deck(stub_deck):
    return stub_deck(cards=CARDS, topics=[("Work", 2)])


def _play(client, query="topic=Work"):
    return client.get(f"/games/fill_the_gap/play?{query}").get_data(as_text=True)


def test_the_round_is_unchanged_by_default(client, deck):
    body = _play(client)
    assert games.GAP in body
    assert "r___" not in body


def test_the_round_shows_the_letters_when_asked(client, deck):
    body = _play(client, "topic=Work&hint=first_last")
    assert "r___n" in body


def test_the_gapped_sentence_never_shows_the_word_itself(client, deck):
    """Whatever the mode. The one thing this game must never do.

    Asserted against **the sentence**, not the page: this is a flip deck and
    the back of the card is *supposed* to show the word — that is the reveal.
    A page-wide search would fail on the game working correctly."""
    for mode in games.GAP_HINTS:
        body = _play(client, f"topic=Work&hint={mode}")
        shown = re.findall(r'<p class="gap-sentence">(.*?)</p>', body, re.S)
        assert shown, mode
        for sentence in shown:
            assert games.find_word(sentence, "resign") == [], (mode, sentence)
            assert games.find_word(sentence, "burnout") == [], (mode, sentence)


def test_the_picker_offers_all_three_modes(client, deck):
    body = client.get("/games/fill_the_gap").get_data(as_text=True)
    assert re.findall(r'name="hint" value="(\w+)"', body) == list(games.GAP_HINTS)


def test_the_picker_names_them(client, deck):
    body = client.get("/games/fill_the_gap").get_data(as_text=True)
    for label in games.HINT_LABELS.values():
        assert label in body


def test_spell_its_picker_does_not_offer_no_hint(client, deck):
    body = client.get("/games/spell_it").get_data(as_text=True)
    assert re.findall(r'name="hint" value="(\w+)"', body) == list(games.HINTS)
