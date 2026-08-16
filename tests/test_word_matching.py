"""Finding a card's headword inside real English (kuantorflow#235, #237).

One helper, two callers, and they fail in opposite directions if it is wrong:
#235 gaps the word out of its own example sentence, so a miss shows a learner a
sentence containing its own answer; #237 bolds the words in a generated text and
reports which ones were used, so a miss reports a word as unused while it is on
the screen.

It is a **light stem match, not lemmatisation** — regular inflections only. The
edges are deliberate and are tested as such: irregular forms are missed, and
derivations are not matched at all. Both are choices this file pins down, so
that "improving" the matcher into a stemmer has to argue with a test first.
"""

import pytest

import games


# --- the inflections a headword may be wearing ------------------------------

@pytest.mark.parametrize("sentence, word, found", [
    # The plain case, and the reason `in` is not enough: the dictionary's own
    # example almost never holds the headword verbatim.
    ("He resigned from the board.", "resign", "resigned"),
    ("Resigning was the only option.", "resign", "Resigning"),
    ("Their tactics were obvious.", "tactic", "tactics"),
    # Case-insensitive, because the word may open the sentence.
    ("Tactic one failed.", "tactic", "Tactic"),
    ("LOCAL MAN ACQUITTED", "acquit", "ACQUITTED"),
    # y -> ies / ied
    ("She applies for every job.", "apply", "applies"),
    ("She applied last week.", "apply", "applied"),
    # a dropped e before -ing
    ("We are creating a problem.", "create", "creating"),
    # a doubled final consonant
    ("They are planning a protest.", "plan", "planning"),
    ("He stopped the car.", "stop", "stopped"),
    # `qu` is spelling, not a vowel: without that rule `acquit` does not reach
    # `acquitted`, which is how this was found — a text saying "acquitted"
    # twice with `acquit` reported as unused.
    ("The defendant was acquitted.", "acquit", "acquitted"),
    ("They equipped the team.", "equip", "equipped"),
    # A possessive needs no rule of its own: the apostrophe is a boundary.
    ("The company's policy changed.", "company", "company"),
])
def test_a_regularly_inflected_word_is_found(sentence, word, found):
    spans = games.find_word(sentence, word)
    assert [sentence[a:b] for a, b in spans] == [found]


@pytest.mark.parametrize("sentence, word", [
    # Derivations are a different word, and often a different part of speech.
    # #235 gapping `worker` out of a sentence would be asking for an answer the
    # card does not have.
    ("His resignation surprised everyone.", "resign"),
    ("Prosecutors sought a conviction.", "prosecute"),
    ("He is a hard worker.", "work"),
    # Two words that merely start alike are not the same word.
    ("A basket of apples.", "apply"),
    ("The article was long.", "art"),
    ("The planet is warming.", "plan"),
])
def test_a_different_word_is_not_found(sentence, word):
    """A false match is worse than a miss in both callers, so the endings are a
    closed list rather than "anything after the stem"."""
    assert games.find_word(sentence, word) == []


def test_an_irregular_form_is_missed_and_that_is_the_documented_edge():
    """`took` is not `take` plus an ending, and this is a card game rather than
    a morphological analyser. Pinned so the limit is a decision, not a
    surprise."""
    assert games.find_word("She took nothing for granted.", "take for granted") == []


def test_a_word_that_is_absent_is_absent():
    assert games.find_word("A quiet afternoon.", "resign") == []


def test_nothing_is_not_a_word():
    assert games.find_word("Any sentence at all.", "") == []
    assert games.find_word("Any sentence at all.", None) == []
    assert games.word_pattern("   ") is None


# --- expressions ------------------------------------------------------------

def test_an_expression_is_found_whole():
    """One span across the phrase, not one per word: #235 gaps it as one gap
    and #237 bolds it as one phrase."""
    sentence = "He takes it for granted."
    spans = games.find_word(sentence, "take for granted")
    assert [sentence[a:b] for a, b in spans] == ["takes it for granted"]


def test_an_expression_may_hold_its_object():
    """English puts the object inside the phrase. Demanding the parts be
    adjacent finds almost no real use of a phrasal expression at all."""
    sentence = "They make their minds up quickly."
    assert games.find_word(sentence, "make up")


def test_an_expression_does_not_span_a_full_stop():
    """The window is words, and punctuation closes it — otherwise three
    scattered words half a paragraph apart would match as one phrase."""
    assert games.find_word("I will take one. For granted rights matter.",
                           "take for granted") == []


# --- marking a whole text (#237) --------------------------------------------

TEXT = ("He resigned after the board took it for granted that the tactics "
        "would work. Granted, resigning was dramatic.")


def test_marking_covers_the_text_exactly():
    """The segments are the text, cut up — nothing added, nothing dropped.
    They are rendered run by run, so anything lost here is lost on the page."""
    segments, _, _ = games.mark_words(TEXT, ["resign", "tactic"])
    assert "".join(run for run, _ in segments) == TEXT


def test_marking_reports_what_appeared_and_what_did_not():
    _, used, missing = games.mark_words(
        TEXT, ["resign", "tactic", "negotiate", "acquit"])
    assert used == ["resign", "tactic"]
    assert missing == ["negotiate", "acquit"]


def test_the_supplied_order_is_kept():
    """The page lists them, and a list that re-sorted itself would stop
    matching the order they were asked for."""
    _, used, _ = games.mark_words(TEXT, ["tactic", "resign"])
    assert used == ["tactic", "resign"]


def test_every_occurrence_is_marked():
    segments, _, _ = games.mark_words(TEXT, ["resign"])
    assert [run for run, marked in segments if marked] == ["resigned", "resigning"]


def test_a_longer_expression_wins_an_overlap():
    """"take for granted" and "granted" both match the same ground. One phrase
    in bold reads better than a phrase with a darker tail, and either way the
    text must not be cut twice."""
    text = "The board took it for granted."
    segments, _, _ = games.mark_words(text, ["granted", "take for granted"])
    assert "".join(run for run, _ in segments) == text
    marked = [run for run, is_word in segments if is_word]
    assert marked == ["granted"]        # "took" is irregular, so the phrase misses


def test_a_word_inside_a_longer_match_still_counts_as_used():
    """Used is decided by the match, not by the markup. A word swallowed by an
    overlapping phrase is still a word the model used, and saying otherwise
    would be the unverified claim #237 exists to avoid — in the other
    direction."""
    text = "She takes it for granted."
    _, used, missing = games.mark_words(text, ["take for granted", "granted"])
    assert used == ["take for granted", "granted"]
    assert missing == []


def test_marking_an_empty_text_reports_everything_missing():
    segments, used, missing = games.mark_words("", ["resign"])
    assert segments == []
    assert used == [] and missing == ["resign"]
