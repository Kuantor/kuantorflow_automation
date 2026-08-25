"""A card from the dictionary alone, when no translator answers (kuantorflow#349).

Prompted by kuantorflow#348, where both translator backends went down at once
and looking any word up stopped working entirely — while Oxford answered
perfectly throughout. An English explanation and examples are most of a card's
value to a B2–C1 learner, so the lookup now degrades instead of dying.

Two halves are tested here and they guard different things:

* `lookup_word()` builds cards from the *dictionary's* parts of speech when the
  translator gave none — a deliberate inversion of the usual rule, which is why
  the test that the usual rule still applies sits right beside it;
* `fill_missing_fields()` is the exit from the trap that would otherwise create.
  #101 refuses a duplicate `word` + `pos`, so a card saved during an outage
  could never be improved by looking the word up again — which is exactly what
  a learner would try.

Everything is stubbed: no network, no database.
"""

import pytest

import parsers
import utils

from conftest import fake_card_db


DEFS = {"noun": ["a person who studies a subject in detail"]}
EXAMPLES = {"noun": ["a classical scholar", "the most distinguished scholar"]}


@pytest.fixture()
def silent_translators(monkeypatch):
    """Both translator backends refusing, as in #348."""
    monkeypatch.setattr(parsers, "_google_dictionary", lambda word, code: {})
    monkeypatch.setattr(parsers, "_bing_dictionary", lambda word, code: {})


@pytest.fixture()
def oxford(monkeypatch):
    monkeypatch.setattr(parsers, "_fetch_oxford_entry",
                        lambda word: (DEFS, EXAMPLES))


@pytest.fixture()
def silent_dictionaries(monkeypatch):
    monkeypatch.setattr(parsers, "_fetch_oxford_entry", lambda word: ({}, {}))
    monkeypatch.setattr(parsers, "_fetch_definitions", lambda word: {})


# --- the lookup ------------------------------------------------------------

def test_a_card_is_made_from_the_dictionary_when_no_translator_answers(
        action_logs, silent_translators, oxford):
    cards = parsers.lookup_word("scholar", topic="Education")

    assert len(cards) == 1
    card = cards[0]
    assert card["word"] == "scholar"
    assert card["pos"] == "noun", "the part of speech comes from the dictionary"
    assert card["explanation_en"] == DEFS["noun"][0]
    assert card["examples_en"] == EXAMPLES["noun"]
    assert not card.get("translation_ukr")
    assert not card.get("translation_rus")


def test_the_translator_still_decides_the_cards_when_it_answers(
        action_logs, oxford, monkeypatch):
    """The inversion above is the *fallback*, not the new rule.

    Normally a card exists per part of speech the translator found and takes
    its text from the part of speech the dictionary found (#228). Pinned here
    because #349 could easily have replaced that rather than backing it up:
    the dictionary knows only `noun`, and the verb card must survive with its
    translation and no English text.
    """
    monkeypatch.setattr(parsers, "_google_dictionary", lambda word, code: {
        "noun": ["вчений"], "verb": ["вивчати"]})

    cards = {c["pos"]: c for c in parsers.lookup_word("scholar")}

    assert set(cards) == {"noun", "verb"}
    assert cards["noun"]["explanation_en"] == DEFS["noun"][0]
    assert "explanation_en" not in cards["verb"]
    assert cards["verb"]["translation_ukr"]


def test_nothing_from_either_side_is_still_a_failure(
        action_logs, silent_translators, silent_dictionaries):
    with pytest.raises(ValueError) as failure:
        parsers.lookup_word("zzzz")

    message = str(failure.value)
    assert "no translation service answered" in message, (
        "the message has to blame the service, not the word — "
        '"No translations found for X" reads as "that word does not exist" '
        "and sent #348's investigation at the wrong provider")


def test_a_degraded_lookup_says_so_in_the_log(
        action_logs, silent_translators, oxford):
    """Its own action, so the question *how long was this broken, and how many
    cards carry the scar* can be answered later."""
    parsers.lookup_word("scholar")
    line = [ln for ln in (action_logs / "dict.log").read_text(
        encoding="utf-8").splitlines() if "DEGRADED" in ln]
    assert line and "word=scholar" in line[0]


# --- repairing what the outage left behind ---------------------------------

STORED = {
    "id": 4, "explanation_en": "a person who studies a subject in detail",
    "examples_en": "[]", "translation_ukr": None, "examples_ukr": None,
    "translation_rus": "", "examples_rus": None,
}


def test_a_later_lookup_fills_the_empty_columns(monkeypatch):
    cursor, conn = fake_card_db(monkeypatch, duplicate=dict(STORED))

    filled = utils.fill_missing_fields({
        "word": "scholar", "pos": "noun",
        "translation_ukr": "вчений", "translation_rus": "учёный",
    })

    assert sorted(filled) == ["translation_rus", "translation_ukr"]
    update = next(q for q, _ in cursor.queries if q.startswith("UPDATE"))
    assert "translation_ukr = %s" in update and "translation_rus = %s" in update
    assert conn.committed


def test_a_column_that_holds_something_is_never_overwritten(monkeypatch):
    """The rule that makes this safe to run on every skipped duplicate rather
    than only where somebody has looked. It repairs gaps; it cannot edit."""
    cursor, _ = fake_card_db(monkeypatch, duplicate=dict(STORED))

    filled = utils.fill_missing_fields({
        "word": "scholar", "pos": "noun",
        "explanation_en": "something completely different",
    })

    assert filled == []
    assert not [q for q, _ in cursor.queries if q.startswith("UPDATE")]


def test_an_empty_json_list_counts_as_empty(monkeypatch):
    """`examples_en` is stored as JSON, so a card that never had examples holds
    the two-character string `[]` rather than NULL — and looks full to a plain
    IS NULL test."""
    cursor, _ = fake_card_db(monkeypatch, duplicate=dict(STORED))

    filled = utils.fill_missing_fields({
        "word": "scholar", "pos": "noun", "examples_en": ["a classical scholar"],
    })

    assert filled == ["examples_en"]


def test_an_empty_value_in_the_new_entry_is_not_offered(monkeypatch):
    """A failed lookup carries plenty of empty keys; none of them is an
    instruction to blank a column."""
    cursor, _ = fake_card_db(monkeypatch, duplicate=dict(STORED))

    assert utils.fill_missing_fields({
        "word": "scholar", "pos": "noun",
        "translation_ukr": "", "examples_ukr": [],
    }) == []
    assert not [q for q, _ in cursor.queries if q.startswith("UPDATE")]


def test_no_such_card_fills_nothing(monkeypatch):
    cursor, _ = fake_card_db(monkeypatch, duplicate=None)

    assert utils.fill_missing_fields({
        "word": "scholar", "pos": "noun", "translation_ukr": "вчений"}) == []
    assert not [q for q, _ in cursor.queries if q.startswith("UPDATE")]


# --- and what the save path does with it -----------------------------------

def test_a_filled_duplicate_is_still_not_a_save(
        client, app_module, monkeypatch, action_logs):
    """**A fill is not a save.** Returning True here would put the app back
    where #308 was, with Mykola confirming a card that was never written.
    """
    monkeypatch.setattr(app_module, "save_flashcard",
                        lambda entry, added_by_user_id=None: None)
    monkeypatch.setattr(app_module, "fill_missing_fields",
                        lambda entry: ["translation_ukr"])

    # A session with an identity: `_save_and_log()` refuses an anonymous
    # writer outright (#125), so without one this never reaches the fill.
    with app_module.app.test_request_context("/"):
        from flask import session
        session["user"] = {"id": 7, "name": "Test User",
                           "email": "test.user@gmail.com"}
        assert app_module._save_and_log(
            {"word": "scholar", "pos": "noun"}, source="test") is False

    log = (action_logs / "cards.log").read_text(encoding="utf-8")
    assert "FILL" in log and "fields=translation_ukr" in log
    assert "SKIP" not in log, "a duplicate that gained something is not a skip"


# --- and what the learner is told ------------------------------------------

def _banners(body):
    import re
    return [" ".join(b.split()) for b in re.findall(
        r'<div class="banner confirmation">\s*(.*?)\s*(?:<a |</div>)', body, re.S)]


@pytest.fixture()
def degraded(monkeypatch, silent_translators, oxford):
    """A lookup that can only reach the dictionary, as in #348."""


@pytest.mark.parametrize("automatically", [False, True])
def test_the_learner_is_told_no_translation_service_answered(
        user_client, saved, action_logs, degraded, app_module, monkeypatch,
        automatically):
    """Said once, at lookup, because it is true of the review popup and the
    automatic save alike — and a banner that quietly stops rendering is the
    kind of thing only a test notices.
    """
    import settings_store
    prefs = settings_store.load(7, "test.user@gmail.com")
    prefs["cards_automatically"] = automatically
    settings_store.save(7, "test.user@gmail.com", prefs)

    body = user_client.post(
        "/", data={"action": "parse_word", "word": "scholar",
                   "topic": "Education"}, follow_redirects=True
    ).get_data(as_text=True)

    said = " ".join(_banners(body))
    assert "No translation service is answering" in said
    assert "will be filled in" in said, "and that it is worth trying again"


def test_the_notice_is_not_shown_when_translations_arrived(
        user_client, saved, action_logs, oxford, monkeypatch):
    """The other half, and the one that would rot silently: a notice shown on
    every lookup is worse than none."""
    monkeypatch.setattr(parsers, "_google_dictionary",
                        lambda word, code: {"noun": ["вчений"]})

    body = user_client.post(
        "/", data={"action": "parse_word", "word": "scholar",
                   "topic": "Education"}, follow_redirects=True
    ).get_data(as_text=True)

    assert "No translation service is answering" not in " ".join(_banners(body))
