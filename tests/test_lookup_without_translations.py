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
#
# **Where** matters as much as whether. A page-level banner is unreadable
# behind the review popup: `.modal-overlay` is `position: fixed; inset: 0`,
# 75% opaque and blurred, and that popup is the default path. The first
# version of this notice was a banner only, so most learners never saw it --
# and the test that covered it passed, because it asked whether the words
# were in the document rather than whether they were in the dialog.
#
# So these assert on the **dialog**, and the banner is checked only where
# there is no dialog to be behind.


def _dialog(body):
    """The review popup's markup with its whitespace collapsed, or "".

    Collapsed because the prose in it wraps across template lines, so a phrase
    is not contiguous in the HTML — an assertion on the raw markup fails
    against a page that is perfectly correct. That has now caught me three
    times in this suite.
    """
    import re
    found = re.search(r'<div class="modal modal-dialog proposal-dialog.*', body, re.S)
    return " ".join(found.group(0).split()) if found else ""


def _banners(body):
    import re
    return " ".join(" ".join(b.split()) for b in re.findall(
        r'<div class="banner confirmation">\s*(.*?)\s*(?:<a |</div>)', body, re.S))


def _look_up(client, word="perspicacious"):
    return client.post("/", data={"action": "parse_word", "word": word,
                                  "topic": "Education"},
                       follow_redirects=True).get_data(as_text=True)


@pytest.fixture()
def automatically():
    """Turn *Add cards automatically* on — the one path with no popup.

    Written through `settings_store` for the signed-in test identity, the way
    the Settings popup writes it, rather than by patching `current_settings()`
    — that reads the session and cannot be called outside a request.
    `settings_dir` (autouse) already points the store at a temp directory.
    """
    import settings_store

    from conftest import TEST_USER_EMAIL, TEST_USER_ID

    def on(value=True):
        prefs = settings_store.load(TEST_USER_ID, TEST_USER_EMAIL)
        prefs["cards_automatically"] = value
        settings_store.save(prefs, TEST_USER_ID, TEST_USER_EMAIL)
    return on


def test_the_popup_carries_the_notice_where_the_learner_is_looking(
        user_client, saved, action_logs, silent_translators, oxford):
    """**Inside the dialog**, which is the assertion that would have caught the
    first version: a banner behind a fixed, opaque overlay is in the document
    and invisible."""
    body = _look_up(user_client)

    assert "proposal-degraded" in _dialog(body),         "the notice has to be inside the popup, not behind it"
    assert "No translation service is answering" in _dialog(body)
    assert "Type them in yourself" in _dialog(body),         "and it should offer the choice, not only report the fault"


def test_the_banner_covers_the_path_that_has_no_popup(
        user_client, saved, action_logs, silent_translators, oxford,
        automatically):
    """With *Add cards automatically* on there is no dialog at all, so the
    page-level banner is the only place left to say it."""
    automatically()
    body = _look_up(user_client)

    assert "No translation service is answering" in _banners(body)


def test_neither_is_shown_when_translations_arrived(
        user_client, saved, action_logs, oxford, monkeypatch):
    """The half that rots quietly. A notice on every lookup is worse than
    none, and only the tests above would never catch that."""
    monkeypatch.setattr(parsers, "_google_dictionary",
                        lambda word, code: {"noun": ["вчений"]})
    body = _look_up(user_client)

    assert "proposal-degraded" not in body
    assert "No translation service is answering" not in _banners(body)


# --- and it must not break the popup it lives in ---------------------------

def test_the_notice_is_inside_the_scrolling_pane(
        user_client, saved, action_logs, silent_translators, oxford):
    """Above the pane it added its own height to a dialog whose scroll region
    was capped at a fixed 65vh, and the cards ran out past the popup's bottom
    edge. Inside it, it costs the layout nothing and scrolls with the cards.
    """
    body = _look_up(user_client)
    pane_opens = body.index('class="modal-scroll proposal-cards-pane"')
    first_card = body.index('class="proposal-card"', pane_opens)
    notice = body.index('class="proposal-degraded"')

    # Position rather than a regex over the pane's extent: what matters is that
    # the notice is inside the scrolling region and above the cards, and that
    # does not depend on which tag happens to close the pane.
    assert pane_opens < notice < first_card


@pytest.mark.parametrize("selector,declaration", [
    (".proposal-dialog", "flex-direction: column"),
    (".proposal-dialog .proposal-body", "min-height: 0"),
    (".proposal-dialog .proposal-cards-pane", "min-height: 0"),
    (".proposal-dialog .proposal-cards-pane", "max-height: none"),
    (".proposal-dialog--source .proposal-body", "flex-direction: row"),
])
def test_the_dialog_contains_its_own_content(client, selector, declaration):
    """The four declarations that keep the popup's content inside it, pinned
    the way #298 pinned its three.

    `min-height: 0` is the load-bearing pair: a flex item defaults to
    `min-height: auto` and refuses to shrink below its content, which is
    exactly how a child escapes its container. And the row direction is
    restated for the upload variant because the column rule above it would
    otherwise silently turn two panes into one.

    Measured in a browser at 1280x720, 375x560 and 360x380: the dialog stays
    inside the viewport, the pane inside the dialog, and no card is painted
    below the dialog's edge.
    """
    import re
    css = client.get("/static/css/style.css").get_data(as_text=True)
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for match in re.finditer(r"([^{}@]+?)\{([^{}]*?)\}", stripped, re.S):
        if selector in [n.strip() for n in match.group(1).split(",")]:
            if declaration in " ".join(match.group(2).split()):
                return
    raise AssertionError(f"{selector} no longer sets {declaration}")
