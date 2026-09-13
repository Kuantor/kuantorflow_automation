"""One place where a graded round is graded (kuantorflow#416).

Six rounds grade an answer server-side against a real card, and until #416 five
of them read back what was asked through ``games.asked()`` while the sixth --
*Multiple choice* -- kept its own inlined copy of that loop. The copies agreed,
so nothing was broken and nothing in this suite would have gone red. What this
file guards is the thing a green suite could not see: that there is **one**
loop, and that the rounds which must never record a result are exactly the
rounds that cannot reach it.

That is what kuantorflow#338 needs. It records per-learner recall from the
rounds that grade an answer against a card row, and with one seam that is one
write. With two, the most-played round in the app is the one that silently does
not write, and every assertion about its results page still passes -- which is
the shape #414 cost us, a rule living in two places so a change reaches one.

The grading itself is tested per game in its own file, and nothing here
re-asserts a score. The translations below are deliberately ASCII: the quiz's
Cyrillic fold is a fact about a stored translation and is tested where that
belongs, in `test_quiz.py`.
"""

import re

import pytest
from werkzeug.datastructures import MultiDict


SENTENCE = "The jury acquitted him of murder"

# One deck every graded round can play: a translation in both languages for the
# quiz and Multiple choice, an explanation for Spell it, letters only so Listen
# and type can speak it, and an example long enough to rebuild.
CARDS = [
    {"id": 1, "word": "delegate", "pos": "verb", "topic": "Work",
     "translation_ukr": "to hand over", "translation_rus": "to hand over",
     "explanation_en": "to give a task to someone else",
     "examples_en": [SENTENCE + "."]},
    {"id": 2, "word": "resign", "pos": "verb", "topic": "Work",
     "translation_ukr": "to quit", "translation_rus": "to quit",
     "explanation_en": "to leave a job by choice",
     "examples_en": ["He resigned after a single year in the post."]},
    {"id": 3, "word": "burnout", "pos": "noun", "topic": "Work",
     "translation_ukr": "exhaustion", "translation_rus": "exhaustion",
     "explanation_en": "exhaustion caused by overwork",
     "examples_en": ["Burnout is common in the first year of teaching."]},
    {"id": 4, "word": "commute", "pos": "verb", "topic": "Work",
     "translation_ukr": "to travel to work", "translation_rus": "to travel",
     "explanation_en": "to travel regularly to and from work",
     "examples_en": ["She commutes across the city twice a day."]},
    {"id": 5, "word": "appraisal", "pos": "noun", "topic": "Work",
     "translation_ukr": "assessment", "translation_rus": "assessment",
     "explanation_en": "a formal judgement of how someone works",
     "examples_en": ["The annual appraisal took less than an hour."]},
    # A second topic, because *Odd one out* needs two before its round runs at
    # all — `min_topics` is checked in the route, above the POST branch.
    {"id": 6, "word": "verdict", "pos": "noun", "topic": "Law",
     "translation_ukr": "decision", "translation_rus": "decision",
     "explanation_en": "a jury's decision",
     "examples_en": ["The verdict came after three days."]},
]


@pytest.fixture()
def deck(stub_deck):
    return stub_deck(cards=CARDS)


# (name, url, the smallest POST that grades one question)
GRADED = [
    ("scrambled", "/games/scrambled/play?topic=Work",
     {"answer_1": "delegate"}),
    ("multiple choice", "/games/multiple_choice/play?topic=Work",
     {"answer_1": "delegate"}),
    ("listen and type", "/games/listen_and_type/play?topic=Work",
     {"answer_1": "delegate"}),
    ("spell it", "/games/spell_it/play?topic=Work",
     {"answer_1": "delegate"}),
    ("rebuild the sentence", "/games/rebuild_the_sentence/play?topic=Work",
     {"answer_1": SENTENCE, "sentence_1": SENTENCE}),
    ("the quiz", "/quiz?topic=Work&lang=ukr",
     {"answer_1": "to hand over"}),
]

# The two rounds that grade and still cannot record one, and why. Both are
# kuantorflow#338's exclusions, and neither is a judgement call: there is
# nothing on the form to attribute a result to.
UNATTRIBUTABLE = [
    ("odd one out", "/games/odd_one_out/play?topic=Work&topic=Law",
     MultiDict([("answer_1", "verdict"), ("intruder_1", "verdict"),
                ("home_1", "Work"), ("from_1", "Law")])),
    ("real or fake", "/games/real_or_fake/play",
     MultiDict([("answer_1", "fake"), ("item_1", "flimp"),
                ("real_1", "0")])),
]


@pytest.fixture()
def seam(app_module, monkeypatch):
    """Records every call to the one helper, and passes them through."""
    calls = []
    original = app_module._graded_answers

    def recording(cards, judge):
        graded = original(cards, judge)
        calls.append(graded)
        return graded

    monkeypatch.setattr(app_module, "_graded_answers", recording)
    return calls


@pytest.mark.parametrize("name,url,data", GRADED, ids=[r[0] for r in GRADED])
def test_every_graded_round_grades_through_the_one_helper(
        client, deck, seam, name, url, data):
    """The assertion the app could not satisfy before #416: *Multiple choice*
    had its own copy of this loop, so a write placed in the shared one would
    have skipped it and no results-page test would have noticed."""
    client.post(url, data=data)
    assert seam, f"{name} graded its round somewhere else"
    assert [card["id"] for card, _given, _ok in seam[0]] == [1]


@pytest.mark.parametrize("name,url,data", UNATTRIBUTABLE,
                         ids=[r[0] for r in UNATTRIBUTABLE])
def test_a_round_with_no_card_behind_it_cannot_reach_the_helper(
        client, deck, seam, name, url, data):
    """*Odd one out* posts by question index rather than by card id, and *Real
    or fake* asks about invented words with no row at all. #338 excludes both,
    and this is why that exclusion needs no discipline to hold: with no card id
    on the form, neither round can call the helper even by accident.

    The score is asserted first so this cannot pass by not playing: a typo in
    the URL or the field names would grade nothing, and "nothing called the
    helper" would be true for the wrong reason."""
    body = client.post(url, data=data).get_data(as_text=True)
    assert "Score: 1 / 1" in body, f"{name} did not actually grade a round"
    assert seam == [], f"{name} has no card id to record a result against"


# --- what the helper itself promises --------------------------------------


def _graded(app_module, cards, judge, data):
    with app_module.app.test_request_context(
            "/", method="POST", data=MultiDict(data)):
        return app_module._graded_answers(cards, judge)


def _always(card, given):
    return True


def test_the_questions_come_back_in_submission_order(app_module):
    """The results list is numbered, and a learner reading "3. wrong" has to
    find the third question they answered."""
    graded = _graded(app_module, CARDS, _always,
                     [("answer_3", "a"), ("answer_1", "b"), ("answer_2", "c")])
    assert [card["id"] for card, _given, _ok in graded] == [3, 1, 2]


def test_a_repeated_field_is_graded_once(app_module):
    """A doubled submit or a hand-built POST would otherwise score the same
    question twice. This is the rule *Multiple choice* used to keep its own
    copy of."""
    graded = _graded(app_module, CARDS, _always,
                     [("answer_1", "a"), ("answer_1", "a")])
    assert len(graded) == 1


def test_an_id_that_was_never_asked_is_ignored(app_module):
    """The submitted names are read back against the cards the round could have
    drawn, so a POST naming anything else grades nothing."""
    assert _graded(app_module, CARDS, _always, [("answer_999", "a")]) == []


def test_the_answer_is_trimmed_before_the_judge_sees_it(app_module):
    seen = []
    _graded(app_module, CARDS, lambda card, given: seen.append(given),
            [("answer_1", "  delegate  ")])
    assert seen == ["delegate"]


def test_the_judge_decides_and_its_answer_is_a_boolean(app_module):
    """Every round builds `"correct": correct` straight into its results, and a
    truthy non-boolean there would reach a template that prints it."""
    graded = _graded(app_module, CARDS, lambda card, given: "yes",
                     [("answer_1", "delegate")])
    assert graded[0][2] is True


# --- the one comparison that must not be tidied into the shared rule -------


def test_multiple_choice_does_not_forgive_a_hyphen(client, stub_deck):
    """#267's normalisation folds a hyphen to a space, and #131's distractors
    are slips on the answer -- so under `same_answer()` an option generated
    from `well-being` could normalise back onto the answer and be marked right.

    Nothing a learner types reaches this round: a radio submits one of the
    strings the round itself put on the page. The forgiveness therefore has
    nothing to forgive here, and adopting it could only turn a wrong option
    right.
    """
    stub_deck(cards=[dict(CARDS[0], word="well-being")])
    body = client.post("/games/multiple_choice/play?topic=Work",
                       data={"answer_1": "well being"}).get_data(as_text=True)
    # The score is read out rather than searched for, so a round that scored
    # it 1 / 1 says so in the failure instead of reporting an absent string.
    assert re.findall(r"Score: \d+ / \d+", body) == ["Score: 0 / 1"]
