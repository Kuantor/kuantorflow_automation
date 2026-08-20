"""One typed-answer path (kuantorflow#267).

Four rounds take a typed answer — the quiz, scrambled, and wave two's spell it
and listen and type — and before this there were two copies of "read back what
was asked" and two different ideas of what counts as the same answer.

Both new functions are pure and take plain data, so everything interesting is
testable with no request context and no database. That is the point of the
shape: the cases that decide this are all things a learner actually types, and
none of them were covered while the logic lived inside two route handlers.
"""

import pytest

import games


# --- what counts as the same answer --------------------------------------


@pytest.mark.parametrize("typed,expected", [
    ("resign", "resign"),
    ("Resign", "resign"),                  # a capital is not a spelling
    ("resign ", "resign"),                 # trailing space
    ("  resign", "resign"),                # leading space
    ("RESIGN", "resign"),
    ("resign.", "resign"),                 # a habit, not a mistake
    ("resign,", "resign"),
    ('"resign"', "resign"),                # pasted with quotes
    ("take  for granted", "take for granted"),   # doubled inner space
    ("take for granted ", "take for granted"),
    ("well being", "well-being"),          # hyphen typed as a space
    ("well-being", "well being"),          # and the other way round
    ("WELL-BEING", "well  being"),         # every rule at once
])
def test_these_are_the_same_answer(typed, expected):
    assert games.same_answer(typed, expected), (typed, expected)


@pytest.mark.parametrize("typed,expected", [
    ("resigned", "resign"),                # a different word, and stays wrong
    ("resign", "resigned"),
    ("resin", "resign"),                   # a real misspelling
    ("burnout", "resign"),
    ("", "resign"),
    ("   ", "resign"),
    (".", "resign"),
])
def test_these_are_not(typed, expected):
    assert not games.same_answer(typed, expected), (typed, expected)


def test_nothing_inside_a_word_is_touched():
    """The line this draws is between how a phrase was *typed* and how it was
    *spelled*, and only the first is forgiven. A stemmer here would mark
    `resigned` correct for `resign`, which is the opposite of a spelling game."""
    assert games.normalise_answer("resigned") == "resigned"
    assert games.normalise_answer("don't") == "don't"
    assert games.normalise_answer("o'clock") == "o'clock"


def test_an_apostrophe_inside_a_word_survives_but_one_around_it_does_not():
    assert games.normalise_answer("'don't'") == "don't"


def test_it_copes_with_nothing_at_all():
    """Called on whatever a form hands over, which can be an absent field."""
    assert games.normalise_answer(None) == ""
    assert games.normalise_answer("") == ""
    assert games.normalise_answer("   ") == ""


def test_it_is_not_language_specific():
    """The quiz's Cyrillic ё/е fold belongs to a stored *translation* and stays
    on the quiz's own path. An English headword has no ё in it, and a rule that
    fires for one caller does not belong in the shared one."""
    assert games.normalise_answer("жильё") != games.normalise_answer("жилье")


# --- which questions were asked -------------------------------------------


BY_ID = {"1": "one", "2": "two", "3": "three"}


def test_it_returns_the_items_whose_fields_were_submitted():
    assert games.asked(["answer_1", "answer_3"], BY_ID) == ["one", "three"]


def test_it_returns_them_in_the_order_the_fields_arrived():
    """The results list is numbered, and a learner reading "3. wrong" has to
    find the third question they answered — not the third alphabetically, and
    not the third the database returned."""
    assert games.asked(["answer_3", "answer_1"], BY_ID) == ["three", "one"]


def test_a_repeated_field_cannot_ask_the_same_question_twice():
    """Popped, not fetched. A doubled submit or a hand-built POST would
    otherwise be scored twice."""
    assert games.asked(["answer_2", "answer_2"], BY_ID) == ["two"]


def test_fields_that_are_not_answers_are_ignored():
    """A round posts more than answers — scrambled sends the puzzle it showed,
    real-or-fake sends what each item really was."""
    assert games.asked(["scrambled_1", "answer_1", "csrf"], BY_ID) == ["one"]


def test_an_unknown_id_is_ignored_rather_than_graded():
    """Field names arrive from a browser. One naming a card outside the
    selection is not a question this round asked."""
    assert games.asked(["answer_1", "answer_999"], BY_ID) == ["one"]


def test_nothing_submitted_is_an_empty_round_not_an_error():
    assert games.asked([], BY_ID) == []
    assert games.asked(["csrf"], BY_ID) == []


def test_it_does_not_consume_the_mapping_it_was_given():
    """Popping is what stops a repeat inside one call; doing it to the caller's
    dict would make a second call see a different round."""
    by_id = dict(BY_ID)
    games.asked(["answer_1"], by_id)
    assert by_id == BY_ID


def test_the_prefix_can_change_for_a_round_that_names_its_fields_differently():
    assert games.asked(["pick_1"], BY_ID, prefix="pick_") == ["one"]


# --- the rounds still grade the way they did ------------------------------


CARDS = [
    {"id": 1, "word": "delegate", "topic": "Work"},
    {"id": 2, "word": "well-being", "topic": "Work"},
    {"id": 3, "word": "take for granted", "topic": "Work"},
]


@pytest.fixture()
def deck(stub_deck):
    return stub_deck(cards=CARDS)


def test_scrambled_now_forgives_a_hyphen_typed_as_a_space(client, deck):
    """The one behaviour #267 changes, and it changes for the better: marking
    `well being` wrong for `well-being` taught a learner nothing about
    English."""
    body = client.post("/games/scrambled/play?topic=Work",
                       data={"answer_2": "well being"}).get_data(as_text=True)
    assert "Score: 1 / 1" in body


def test_scrambled_forgives_a_trailing_full_stop(client, deck):
    body = client.post("/games/scrambled/play?topic=Work",
                       data={"answer_1": "delegate."}).get_data(as_text=True)
    assert "Score: 1 / 1" in body


def test_scrambled_still_marks_a_different_word_wrong(client, deck):
    body = client.post("/games/scrambled/play?topic=Work",
                       data={"answer_1": "delegated"}).get_data(as_text=True)
    assert "Score: 0 / 1" in body


def test_scrambled_still_grades_only_what_was_asked(client, deck):
    body = client.post("/games/scrambled/play?topic=Work",
                       data={"answer_1": "delegate"}).get_data(as_text=True)
    assert "Score: 1 / 1" in body
