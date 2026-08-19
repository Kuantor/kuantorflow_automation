"""
Multiple choice — a translation, and four English words (kuantorflow#130/#131).

Two tickets, one game: #131 has no page and no route, it is where three of the
four options come from. So it is tested here, beside the round that consumes
it, rather than in a file of its own.

The rule everything circles: **a wrong answer has to be worth reading.** #130
asked for real card-set words within one or two edits of the answer, and the
deck cannot supply them — of 423 headwords, 49 have one word that close and two
have three. So a question is one keyboard misspelling of the answer plus two
real words from the deck, and the "within two edits" preference is honoured
where it can fire rather than being a requirement that fails silently.

The failure this file is really guarding: **an option that is also correct.**
A typo that lands on a real word (`resign` -> `design`), a duplicate option, or
the answer appearing twice all turn a question into one with two right answers,
and the score stops meaning anything.
"""

import random
import re

import pytest
from werkzeug.datastructures import MultiDict

import games


CARDS = [
    {"id": 1, "word": "delegate", "topic": "Work",
     "translation_ukr": "делегувати", "translation_rus": "делегировать"},
    {"id": 2, "word": "resign", "topic": "Work",
     "translation_ukr": "звільнятися", "translation_rus": "увольняться"},
    {"id": 3, "word": "burnout", "topic": "Work",
     "translation_ukr": "вигорання", "translation_rus": "выгорание"},
    {"id": 4, "word": "commute", "topic": "Work",
     "translation_ukr": "їздити на роботу", "translation_rus": "ездить на работу"},
    {"id": 5, "word": "appraisal", "topic": "Work",
     "translation_ukr": "оцінювання", "translation_rus": "оценка"},
    # No translation in either language, so it can never be asked.
    {"id": 6, "word": "severance", "topic": "Work"},
]


@pytest.fixture()
def deck(stub_deck):
    return stub_deck(cards=CARDS)


def _groups(body):
    """{card id: [the four options shown]}, in the order they were rendered."""
    found = {}
    for name, value in re.findall(r'name="answer_(\d+)"\s+value="([^"]*)"', body):
        found.setdefault(name, []).append(value)
    return found


def _play(client, query="topic=Work&words=20"):
    return client.get(f"/games/multiple_choice/play?{query}").get_data(as_text=True)


# --- the keyboard (#131) -------------------------------------------------


def test_a_key_is_next_to_the_keys_beside_it_in_its_own_row():
    """The neighbours that matter most, and the ones a boundary bug drops:
    two keys in a row are exactly one key width apart."""
    assert "s" in games.KEYBOARD["a"]
    assert "a" in games.KEYBOARD["s"] and "d" in games.KEYBOARD["s"]


def test_a_key_is_next_to_the_staggered_keys_above_and_below():
    """The rows are offset, which is why `a` is under `q`/`w` and not under
    `e` — the whole reason for a geometric model rather than a typed table."""
    assert set(games.KEYBOARD["a"]) == {"q", "w", "s", "z"}
    assert set(games.KEYBOARD["g"]) == {"t", "y", "f", "h", "v", "b"}


def test_a_key_is_not_next_to_the_far_side_of_the_keyboard():
    assert "p" not in games.KEYBOARD["a"]
    assert "q" not in games.KEYBOARD["m"]


def test_adjacency_is_mutual():
    """An asymmetric neighbour table means a typo the model can generate in
    one direction and not the other, which is a bug nobody would ever see."""
    for letter, neighbours in games.KEYBOARD.items():
        for other in neighbours:
            assert letter in games.KEYBOARD[other], (letter, other)


def test_a_typo_is_one_slip_from_its_word():
    """Both slips #131 names are a single *Damerau* edit, which is what makes
    them look like slips rather than like different words.

    Measured here with plain Levenshtein, where a transposition costs two —
    `edit_distance()` does not model transposition, and the two metrics
    disagreeing on exactly this is worth pinning rather than glossing."""
    for candidate in games.typos("resign"):
        assert games.edit_distance("resign", candidate) <= 2, candidate
    substitutions = [c for c in games.typos("resign") if len(c) == len("resign")
                     and sum(a != b for a, b in zip(c, "resign")) == 1]
    assert substitutions, "the adjacent-key half of the model produced nothing"


def test_a_typo_is_never_the_word_itself():
    """The trap `scramble()` guards against: an option identical to the answer
    would be on screen twice, once marked right and once wrong."""
    for word in ("resign", "burnout", "appraisal", "commute", "eerie", "committee"):
        assert word not in games.typos(word), word


def test_a_double_letter_is_not_transposed_into_the_same_word():
    """Swapping the two `t`s in `letter` gives `letter` back."""
    assert "letter" not in games.typos("letter")


@pytest.mark.parametrize("word", ["", "at", "aid", "up to now", "take for granted"])
def test_a_word_that_cannot_be_mistyped_yields_nothing(word):
    """Too short to misspell plausibly, or an expression whose spaces are
    never mistyped. [] rather than an error, so the caller falls back."""
    assert games.typos(word) == []


def test_a_typo_that_lands_on_a_real_word_is_rejected():
    """`design` is one slip from `resign`, and offered beside it, it is simply
    a second English word — or worse, a second correct answer."""
    for seed in range(30):
        picked = games.typo("resign", known={"design"}, rng=random.Random(seed))
        assert picked != "design"


def test_a_typo_avoids_what_is_already_on_the_page():
    for seed in range(20):
        picked = games.typo("resign", avoid=["resigb"], rng=random.Random(seed))
        assert picked != "resigb"


def test_a_typo_is_none_when_nothing_survives():
    """None rather than a failure — the caller reads it as 'take another real
    word' and still builds a full question."""
    assert games.typo("aid") is None
    assert games.typo("resign", known=set(games.typos("resign"))) is None


# --- edit distance -------------------------------------------------------


@pytest.mark.parametrize("a,b,expected", [
    ("resign", "resign", 0),
    ("resign", "design", 1),
    ("resign", "resigned", 2),
    ("cat", "cat", 0),
    ("", "abc", 3),
])
def test_edit_distance_counts_edits(a, b, expected):
    assert games.edit_distance(a, b) == expected


def test_edit_distance_ignores_case():
    """The deck stores headwords as the dictionary spelled them, and a capital
    is not an edit a learner would make."""
    assert games.edit_distance("Resign", "resign") == 0


def test_a_capped_distance_stops_counting_rather_than_lying():
    """The cap is an optimisation, so it must never report a distance *below*
    the truth — only refuse to say how far past the cap it went."""
    far = games.edit_distance("delegate", "burnout", cap=2)
    assert far > 2
    assert games.edit_distance("resign", "design", cap=2) == 1


# --- building a question -------------------------------------------------


POOL = ["delegate", "resign", "burnout", "commute", "appraisal", "tenant"]


def test_a_question_has_four_options_and_the_answer_among_them():
    options = games.question_options("resign", POOL, rng=random.Random(4))
    assert len(options) == games.OPTIONS == 4
    assert "resign" in options


def test_no_option_is_repeated():
    """A duplicated option is a question with two identical answers, and the
    learner cannot be marked fairly on it."""
    for seed in range(40):
        options = games.question_options("resign", POOL, rng=random.Random(seed))
        assert len(set(o.casefold() for o in options)) == 4, options


def test_a_question_carries_exactly_one_misspelling():
    """The mix #130 settled on: not three typos, which makes it a spelling
    test and puts three wrong spellings on screen at once."""
    for seed in range(25):
        options = games.question_options("appraisal", POOL, rng=random.Random(seed))
        slips = [o for o in options if o not in POOL]
        assert len(slips) == 1, options


def test_the_misspelling_is_a_slip_of_some_word_on_the_page_or_the_deck():
    """It is derived from one of the four options — which one is drawn at
    random — so it is always one slip from a real word rather than noise."""
    for seed in range(30):
        options = games.question_options("appraisal", POOL, rng=random.Random(seed))
        slip = next(o for o in options if o not in POOL)
        # One Damerau edit; two by plain Levenshtein when it is a swap.
        assert any(games.edit_distance(slip, real, 2) <= 2
                   for real in POOL), (slip, options)


def test_the_word_that_gets_mistyped_is_sometimes_the_answer_and_sometimes_not():
    """The amendment to #130's first cut. Always mistyping the answer made the
    round winnable with no English: a near-identical pair, of which the tidily
    spelled half is always what was asked for. Drawing the source from all four
    means three questions in four have no pair to find, so hunting for one
    stops being a strategy."""
    paired = 0
    for seed in range(60):
        options = games.question_options("appraisal", POOL, rng=random.Random(seed))
        if any(o != "appraisal" and games.edit_distance(o, "appraisal", 1) <= 1
               for o in options):
            paired += 1
    assert 0 < paired < 60, (
        f"the answer supplied the slip in {paired} of 60 rounds — it should be "
        "some of them, not none and not all")


def test_the_answer_survives_even_when_it_is_the_word_mistyped():
    """The slip always lands in a *wrong* slot. Overwriting the answer with a
    misspelling of itself would leave the question with nothing to pick."""
    for seed in range(60):
        options = games.question_options("appraisal", POOL, rng=random.Random(seed))
        assert "appraisal" in options, options


def test_the_other_two_options_are_real_words_from_the_deck():
    for seed in range(25):
        options = games.question_options("resign", POOL, rng=random.Random(seed))
        real = [o for o in options if o != "resign" and o in POOL]
        assert len(real) == 2, options


def test_a_word_too_short_to_mistype_still_gets_a_full_question():
    """The typo is a preference, not a requirement — otherwise `aid` could
    never be asked at all."""
    options = games.question_options("aid", POOL + ["aid"], rng=random.Random(2))
    assert options is not None and len(options) == 4
    assert "aid" in options


def test_a_close_real_word_is_preferred_over_a_distant_one():
    """#130's Levenshtein rule, honoured wherever the deck can supply it."""
    pool = ["resigned", "resigns", "burnout", "delegate", "tenant", "commute"]
    chosen = games.real_distractors("resign", pool, 2, rng=random.Random(1))
    assert set(chosen) == {"resigned", "resigns"}


def test_the_answer_is_never_offered_as_its_own_distractor():
    chosen = games.real_distractors("resign", ["resign", "RESIGN", "tenant"], 2,
                                    rng=random.Random(1))
    assert chosen == ["tenant"]


def test_a_selection_too_thin_to_fill_a_question_borrows_from_the_wider_deck():
    """A four-card topic would otherwise offer the same wrong answers every
    question, which a learner spots in about two of them."""
    options = games.question_options("resign", ["resign"], spare=POOL,
                                     rng=random.Random(3))
    assert options is not None and len(options) == 4


def test_a_question_that_cannot_be_filled_is_none():
    """None is the eligibility rule: a three-option question is an easier game,
    and dealing one silently would make the score mean two things."""
    assert games.question_options("aid", ["aid"], rng=random.Random(1)) is None


def test_a_slip_of_a_distractor_can_never_collide_with_the_answer():
    """Substitution and transposition both preserve length, so a typo of a
    same-length distractor really can land on the answer — `beat` slips to
    `bear` — which would put the correct word on the page twice, once marked
    wrong."""
    for seed in range(60):
        options = games.question_options("bear", ["bear", "beat", "heat", "peat"],
                                         rng=random.Random(seed))
        if options is None:
            continue
        assert len([o for o in options if o.casefold() == "bear"]) == 1, options


# --- the round -----------------------------------------------------------


def test_the_round_asks_only_cards_with_a_translation(client, deck):
    """`severance` has neither, so it can be neither a prompt nor an option —
    it never reaches the pool the distractors are drawn from either."""
    body = _play(client)
    assert "6" not in _groups(body)
    assert "severance" not in body


def test_every_question_offers_four_options(client, deck):
    for card_id, options in _groups(_play(client)).items():
        assert len(options) == 4, (card_id, options)


def test_the_prompt_is_the_translation_and_the_options_are_english(client, deck):
    body = _play(client)
    assert "делегувати" in body
    assert "delegate" in body


def test_the_language_follows_the_picker(client, deck):
    """`picks_language` puts the choice in the picker, and `_quiz_lang()` —
    the quiz's own code — resolves it. Two rules for one question drift."""
    assert "делегувати" in _play(client, "topic=Work&lang=ukr&words=20")
    assert "делегировать" in _play(client, "topic=Work&lang=rus&words=20")


def test_the_round_says_how_many_cards_had_no_translation(client, deck):
    """The picker counts cards, not cards this game can use, so a round
    shorter than the count looks like a bug unless it says otherwise."""
    flat = " ".join(_play(client).split())
    assert "1 card here has no Ukrainian translation" in flat


def test_the_round_length_follows_the_word_count(client, deck):
    assert len(_groups(_play(client, "topic=Work&words=2"))) == 2


def test_a_word_is_never_asked_twice_in_one_round(client, stub_deck):
    """#101 keeps a card per word *and* part of speech, so `work` the noun and
    `work` the verb are two cards — and asking both is a free second mark."""
    stub_deck(cards=[
        {"id": 1, "word": "work", "pos": "noun", "topic": "Work",
         "translation_ukr": "робота"},
        {"id": 2, "word": "work", "pos": "verb", "topic": "Work",
         "translation_ukr": "працювати"},
        {"id": 3, "word": "resign", "topic": "Work", "translation_ukr": "звільнятися"},
        {"id": 4, "word": "burnout", "topic": "Work", "translation_ukr": "вигорання"},
        {"id": 5, "word": "commute", "topic": "Work", "translation_ukr": "їздити"},
    ])
    body = _play(client)
    prompts = re.findall(r'<div class="word">\s*\d+\.\s*([^<]+)', body)
    assert len(prompts) == len(set(p.strip() for p in prompts)), prompts


def test_a_deck_too_small_to_fill_a_question_says_so(client, stub_deck):
    """One card cannot furnish four different answers, and #130's rule is that
    a three-option question is not dealt at all — so the page explains itself
    rather than showing an empty form."""
    stub_deck(cards=[dict(CARDS[0])])
    body = _play(client)
    assert "aren&rsquo;t enough words here" in body
    assert _groups(body) == {}


def test_both_languages_hidden_is_a_dead_end_with_a_reason(
        client, deck, app_module, monkeypatch):
    """The same dead end the quiz reaches (#46/#79/#111) — the question *is* a
    translation, so with neither language on screen there is nothing to ask.

    Patched at `_visible_quiz_langs`, which is the function whose empty return
    *is* the condition, rather than at the settings underneath it."""
    monkeypatch.setattr(app_module, "_visible_quiz_langs", lambda prefs: {})
    body = _play(client)
    assert "no language to be tested in" in body.lower()
    assert _groups(body) == {}


# --- grading -------------------------------------------------------------


def test_every_answer_right_scores_full_marks(client, deck):
    groups = _groups(_play(client))
    by_id = {str(c["id"]): c["word"] for c in CARDS}
    body = client.post("/games/multiple_choice/play?topic=Work",
                       data={f"answer_{i}": by_id[i] for i in groups}
                       ).get_data(as_text=True)
    assert f"Score: {len(groups)} / {len(groups)}" in body


def test_a_wrong_answer_costs_a_mark_and_reveals_the_right_one(client, deck):
    groups = _groups(_play(client))
    by_id = {str(c["id"]): c["word"] for c in CARDS}
    ids = sorted(groups)
    data = {f"answer_{i}": by_id[i] for i in ids}
    data[f"answer_{ids[0]}"] = "definitely-not-a-word"
    body = client.post("/games/multiple_choice/play?topic=Work",
                       data=data).get_data(as_text=True)
    assert f"Score: {len(ids) - 1} / {len(ids)}" in body
    assert by_id[ids[0]] in body


def test_grading_ignores_case(client, deck):
    groups = _groups(_play(client))
    by_id = {str(c["id"]): c["word"] for c in CARDS}
    body = client.post("/games/multiple_choice/play?topic=Work",
                       data={f"answer_{i}": by_id[i].upper() for i in groups}
                       ).get_data(as_text=True)
    assert f"Score: {len(groups)} / {len(groups)}" in body


def test_grading_marks_what_was_asked_rather_than_a_fresh_draw(client, deck):
    """The draw is random and the distractors are generated per round, so a
    re-draw on POST would mark answers against options nobody saw."""
    body = client.post("/games/multiple_choice/play?topic=Work&words=20",
                       data={"answer_2": "resign"}).get_data(as_text=True)
    assert "Score: 1 / 1" in body


def test_an_unknown_card_id_is_ignored_rather_than_graded(client, deck):
    """Submitted field names are the only record of what was asked, and they
    arrive from a browser — one naming a card outside the selection is not a
    question this round asked."""
    body = client.post("/games/multiple_choice/play?topic=Work&words=20",
                       data={"answer_2": "resign", "answer_9999": "whatever"}
                       ).get_data(as_text=True)
    assert "Score: 1 / 1" in body


def test_a_repeated_field_cannot_ask_the_same_question_twice(client, deck):
    body = client.post("/games/multiple_choice/play?topic=Work&words=20",
                       data=MultiDict([("answer_2", "resign"),
                                       ("answer_2", "resign")])
                       ).get_data(as_text=True)
    assert "Score: 1 / 1" in body


# --- the activity declaration --------------------------------------------


def test_the_activity_no_longer_carries_a_ticket():
    """`ticket` is present exactly while an activity is a stub (#253), and
    dropping it is the one edit that un-greys the tile, the topic-page row and
    the front-page panel."""
    assert games.ACTIVITIES["multiple_choice"].ticket == ""


def test_the_activity_asks_for_a_language():
    """The prompt is a translation, so which language it is in is a choice
    made before the words are drawn — the quiz's question (#113)."""
    assert games.ACTIVITIES["multiple_choice"].picks_language is True


def test_the_round_is_registered_rather_than_stubbed(app_module):
    assert app_module.GAME_ROUNDS["multiple_choice"] is not app_module._round_stub
