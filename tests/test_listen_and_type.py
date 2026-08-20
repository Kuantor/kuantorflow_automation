"""Listen and type — the word is spoken, the learner writes it (kuantorflow#272).

**The audio is not tested here and cannot be.** The suite cannot hear anything
and a headless browser generally has no voices at all, so pretending otherwise
would be worse than saying so. The speech path gets a manual browser check,
recorded on the PR.

Everything either side of it is testable offline, and that split is a design
constraint rather than a testing note — it is why grading stays on the server.
A game that decided correctness in JavaScript because the audio was already
there would take the one testable half out of reach too.

What is checked here: which cards can be dictated, that the word never appears
as text before grading, that grading is server-side and follows #267, and that
the page carries the probe and the no-voice message rather than rendering
buttons that do nothing.
"""

import re

import pytest

import games


CARDS = [
    {"id": 1, "word": "delegate", "pos": "verb", "topic": "Work",
     "explanation_en": "to give a task to someone else",
     "translation_ukr": "делегувати"},
    {"id": 2, "word": "take for granted", "topic": "Work",
     "translation_ukr": "сприймати як належне"},
    {"id": 3, "word": "well-being", "topic": "Work",
     "explanation_en": "the state of being comfortable and healthy"},
    # #101 keeps a card per word *and* part of speech, so this is a second
    # `delegate` and must not be dictated twice.
    {"id": 4, "word": "delegate", "pos": "noun", "topic": "Work",
     "translation_ukr": "делегат"},
    # Not a thing to dictate.
    {"id": 5, "word": "e.g.", "topic": "Work", "translation_ukr": "напр."},
]


@pytest.fixture()
def deck(stub_deck):
    return stub_deck(cards=CARDS)


def _play(client, query="topic=Work&words=20"):
    return client.get(f"/games/listen_and_type/play?{query}").get_data(as_text=True)


def _spoken(body):
    return re.findall(r'data-say="([^"]+)"', body)


def _asked(body):
    return re.findall(r'name="answer_(\d+)"', body)


def _visible(body):
    """The text a learner can actually read in the round, tags stripped."""
    round_ = re.search(r'<div id="listen-round">.*?</form>', body, re.S)
    return " ".join(re.sub(r"<[^>]+>", " ", round_.group(0)).split()) if round_ else ""


# --- which words can be dictated -----------------------------------------


@pytest.mark.parametrize("word", [
    "resign", "delegate", "well-being", "don't", "take for granted",
    "o'clock", "state of the art",
])
def test_these_can_be_read_aloud(word):
    assert games.speakable(word), word


@pytest.mark.parametrize("word", [
    "e.g.", "24/7", "(informal) chat", "", "   ", "word2", "a.m.",
])
def test_these_cannot(word):
    """A bracketed note, a digit or an abbreviation's full stops make a poor
    thing to hear and a worse thing to type back."""
    assert not games.speakable(word), word


def test_an_abbreviation_written_in_plain_letters_is_still_accepted():
    """`PhD` has no full stops, so the rule takes it — and deliberately so.

    Excluding it would need a heuristic about capitalisation, which would also
    throw out proper nouns and any headword a learner typed in capitals. The
    rule is about characters a voice can pronounce, not about whether a word is
    a good question; #272 draws the line at punctuation and digits, and this is
    where that line falls."""
    assert games.speakable("PhD")


def test_a_multi_word_expression_is_kept_on_purpose():
    """Arguably the better listening question — the learner has to catch the
    unstressed middle — so the space is allowed rather than being the easy
    thing to exclude."""
    assert games.speakable("take for granted")


def test_speakable_takes_a_word_not_a_card():
    """Pure and about the word, so it needs no database to test."""
    assert games.speakable(None) is False


# --- the round ------------------------------------------------------------


def test_the_word_is_never_written_on_the_page(client, deck):
    """The entire exercise. It rides in `data-say` because the browser is what
    speaks it, but it is never rendered as text."""
    body = _play(client)
    visible = _visible(body)
    for word in _spoken(body):
        assert word not in visible, word


def test_every_question_has_a_play_button_and_a_box(client, deck):
    body = _play(client)
    assert len(_spoken(body)) == len(_asked(body)) > 0


def test_a_word_that_cannot_be_read_aloud_is_not_asked(client, deck):
    body = _play(client)
    assert "e.g." not in _spoken(body)


def test_a_word_is_never_dictated_twice(client, deck):
    """`delegate` is two cards — a noun and a verb — and dictating it twice is
    a free second mark and sounds like a mistake."""
    spoken = [w.casefold() for w in _spoken(_play(client))]
    assert len(spoken) == len(set(spoken)), spoken


def test_the_duplicate_is_not_reported_as_unusable(client, deck):
    """`dropped` is printed beside what the game *needs*, so every card in that
    number must be one the game could not use for the stated reason. A
    duplicate is perfectly usable; it has just already been asked."""
    body = _play(client)
    flat = " ".join(body.split())
    assert "1 card here is not usable" in flat, "only e.g. should be reported"


def test_the_page_carries_the_probe_and_the_no_voice_message(client, deck):
    """Whether a voice exists is a browser fact the server cannot know — the
    one deliberate exception to #233's rule (#268). So both answers are on the
    page and the probe chooses between them."""
    body = _play(client)
    assert 'id="no-voice"' in body
    assert "whenDecided" in body
    assert "no English voice" in body


def test_the_game_owns_no_speech_code_of_its_own(client, deck):
    """#268 owns `speechSynthesis`; nothing else may touch it, or the awkward
    availability rules get a second implementation that goes stale."""
    body = _play(client)
    assert "speechSynthesis" not in body.split("speech.js")[0]


def test_the_probe_waits_for_the_deferred_module_to_load(client, deck):
    """The bug this game shipped with, caught in a browser and not by a test.

    `speech.js` is loaded with `defer`, so it runs *after* the document is
    parsed — while an inline script in the body runs *during* parsing. Reading
    `window.kfSpeech` there finds nothing, and the page announced "no English
    voice" on browsers with plenty of them. Verified against the real origin:
    at parse time `typeof window.kfSpeech` is `"undefined"`, and at
    DOMContentLoaded it is `"object"`.

    The ordering itself is a browser fact and cannot be asserted from here.
    What can be asserted is that the page does not read `kfSpeech` at the
    moment that was wrong — the check has to be inside a DOMContentLoaded
    guard, or behind a readyState test that falls back to one."""
    body = _play(client)
    # base.html carries inline scripts of its own after the content block, so
    # the probe is found by what it contains rather than by position.
    script = next(block for block in re.findall(r"<script>(.*?)</script>",
                                                body, re.S)
                  if "whenDecided" in block)
    assert "DOMContentLoaded" in script
    assert "readyState" in script
    # The guard has to be set up before kfSpeech is read -- that ordering in
    # the source is the thing that broke.
    assert script.index("DOMContentLoaded") < script.rindex("kfSpeech")


def test_nothing_speaks_without_a_press(client, deck):
    """Browsers block audio without a user gesture and iOS Safari is strict, so
    the round must not call speak() on load."""
    body = _play(client)
    assert "kfSpeech.speak" not in body


def test_a_selection_with_nothing_to_say_is_explained(client, stub_deck):
    stub_deck(cards=[dict(CARDS[4])])
    body = _play(client)
    assert "no words here that can be read aloud" in body.lower()
    assert "Choose different topics" in body


# --- grading, which stays on the server -----------------------------------


BY_ID = {str(c["id"]): c["word"] for c in CARDS}


def test_every_word_right_scores_full_marks(client, deck):
    ids = _asked(_play(client))
    body = client.post("/games/listen_and_type/play?topic=Work",
                       data={f"answer_{i}": BY_ID[i] for i in ids}
                       ).get_data(as_text=True)
    assert f"Score: {len(ids)} / {len(ids)}" in body


def test_grading_follows_267s_normalisation(client, deck):
    """Capitals, a trailing full stop and a hyphen typed as a space are all
    forgiven — none of them is a mishearing."""
    ids = _asked(_play(client))
    sloppy = {f"answer_{i}": BY_ID[i].upper().replace("-", " ") + "."
              for i in ids}
    body = client.post("/games/listen_and_type/play?topic=Work",
                       data=sloppy).get_data(as_text=True)
    assert f"Score: {len(ids)} / {len(ids)}" in body


def test_a_different_word_is_wrong_and_the_answer_is_shown(client, deck):
    ids = _asked(_play(client))
    data = {f"answer_{i}": BY_ID[i] for i in ids}
    data[f"answer_{ids[0]}"] = "somethingelse"
    body = client.post("/games/listen_and_type/play?topic=Work",
                       data=data).get_data(as_text=True)
    assert f"Score: {len(ids) - 1} / {len(ids)}" in body
    assert BY_ID[ids[0]] in body


def test_the_results_teach_the_word_as_well_as_marking_it(client, deck):
    """A word that was misheard should also be learned — the explanation where
    the card has one, the quiz_lang translation where it does not."""
    body = client.post("/games/listen_and_type/play?topic=Work",
                       data={"answer_1": "wrong", "answer_2": "wrong"}
                       ).get_data(as_text=True)
    assert "to give a task to someone else" in body      # id 1 has one
    assert "сприймати як належне" in body                # id 2 does not


def test_grading_marks_what_was_asked_rather_than_a_fresh_draw(client, deck):
    body = client.post("/games/listen_and_type/play?topic=Work&words=20",
                       data={"answer_1": "delegate"}).get_data(as_text=True)
    assert "Score: 1 / 1" in body


def test_an_unknown_id_is_ignored_rather_than_graded(client, deck):
    body = client.post("/games/listen_and_type/play?topic=Work&words=20",
                       data={"answer_1": "delegate", "answer_9999": "x"}
                       ).get_data(as_text=True)
    assert "Score: 1 / 1" in body


# --- the declaration ------------------------------------------------------


def test_the_activity_no_longer_carries_a_ticket():
    assert games.ACTIVITIES["listen_and_type"].ticket == ""


def test_the_round_is_registered_rather_than_stubbed(app_module):
    assert (app_module.GAME_ROUNDS["listen_and_type"]
            is not app_module._round_stub)
