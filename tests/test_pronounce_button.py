"""Hear the word: a pronounce button on the card (kuantorflow#283, #268).

The app's first audio. All of it happens in the visitor's browser — no key, no
server round trip, nothing stored — so what can be tested offline is the markup
and the wiring, and the audio itself is checked by hand.

Two rules in `speech.js` come from iOS and are the reason this file asserts on
JavaScript at all. Both are invisible in a screenshot and silent when broken:

* `speak()` must be reachable **synchronously from the press**. iOS grants the
  right to make a sound to the click handler and withdraws it the moment the
  handler awaits anything, so a readiness check between the press and the call
  would be silent on iPhones and perfect everywhere else.
* An **empty** voice list is not the same as **no English voice**. `getVoices()`
  is routinely empty on first call; hiding the buttons on that would hide a
  feature that works.
"""

import pytest


CARDS = [
    {"id": 1, "word": "resign", "pos": "verb", "topic": "Work",
     "explanation_en": "to leave a job"},
    {"id": 2, "word": "take for granted", "topic": "Work"},   # multi-word
]


@pytest.fixture()
def topic_page(client, stub_deck):
    stub_deck(cards=CARDS)
    return client.get("/flashcards/Work").get_data(as_text=True)


@pytest.fixture()
def deck_page(client, stub_deck):
    stub_deck(cards=CARDS)
    return client.get("/deck/Work").get_data(as_text=True)


# --- the helper is loaded, once, for everybody ------------------------------

def test_the_helper_is_loaded_site_wide(client):
    """Loaded from base.html rather than by the two pages that use it today:
    the next caller — the review popup, quiz results, #272's game — should
    need markup and nothing else."""
    body = client.get("/").get_data(as_text=True)
    assert "js/speech.js" in body


def test_no_template_touches_the_speech_api_itself(topic_page, deck_page):
    """Every caller goes through the helper. A template reaching for
    speechSynthesis directly would be a second implementation of the voice
    choice, the cancel-before-speak rule and the iOS gesture rule."""
    for page in (topic_page, deck_page):
        assert "speechSynthesis" not in page


# --- the buttons ------------------------------------------------------------

def test_every_card_on_the_topic_page_offers_one(topic_page, stub_deck):
    assert topic_page.count("data-say=") >= 1
    assert 'aria-label="Pronounce ' in topic_page


def test_the_deck_offers_one_on_the_front_face(deck_page):
    assert "data-say=" in deck_page
    assert "say--deck" in deck_page


def test_the_label_names_the_word(topic_page):
    """Forty identical speaker icons are no help to a screen reader."""
    assert 'aria-label="Pronounce ' in topic_page
    # not a bare "Pronounce" with nothing after it
    assert 'aria-label="Pronounce"' not in topic_page


def test_the_button_carries_the_word_rather_than_an_id(topic_page):
    """`data-say` holds the text to speak, so a new surface needs markup and
    no lookup — and so nothing has to fetch a word in order to say it."""
    assert 'data-say=""' not in topic_page


def test_the_buttons_start_hidden(topic_page, deck_page):
    """Revealed by speech.js once it knows the browser can speak. A speaker
    icon that does nothing reads as a broken page; an absent one reads as a
    site that has no such button (#283)."""
    for page in (topic_page, deck_page):
        chunk = page.split("data-say=", 1)[0][-260:]
        assert "hidden" in chunk


# --- the rules that keep it working on a phone ------------------------------

def read_speech_js():
    from pathlib import Path

    import conftest

    return (Path(conftest.KUANTORFLOW_PATH) / "static" / "js" / "speech.js") \
        .read_text(encoding="utf-8")


def test_the_click_is_handled_in_the_capture_phase():
    """The deck flips the card on click and the button sits on its face, so a
    listener on the way *up* runs after the card has already turned over.
    Capture sees the press first and can stop it reaching anything else —
    found by measuring: the bubbling version flipped the card every time."""
    js = read_speech_js()
    handler = js.split('document.addEventListener("click"', 1)[1][:400]
    assert "true)" in handler, "the click listener is not registered for capture"
    assert "stopPropagation" in handler


def test_speaking_is_reachable_without_awaiting_anything():
    """iOS withdraws permission to make a sound the moment the handler waits.
    `speak()` must therefore not be gated on a promise, a callback or the
    readiness check."""
    js = read_speech_js()
    speak = js.split("function speak(", 1)[1].split("\n    }", 1)[0]
    for forbidden in ("await ", "whenDecided", ".then(", "new Promise"):
        assert forbidden not in speak, f"speak() waits on {forbidden!r}"


def test_an_unknown_voice_list_still_speaks():
    """`getVoices()` empty means 'not yet', not 'never' — most of all on iOS.
    The helper falls back to a language rather than refusing."""
    js = read_speech_js()
    assert 'utterance.lang = "en-GB"' in js


def test_pressing_again_cancels_first():
    """A second press repeats the word rather than queueing behind the first,
    and clears the stuck state iOS can be left in after the screen locks."""
    js = read_speech_js()
    speak = js.split("function speak(", 1)[1].split("\n    }", 1)[0]
    assert "speechSynthesis.cancel()" in speak
    assert speak.index("cancel()") < speak.index("speak(utterance)")


def test_a_local_voice_is_preferred():
    """Some browsers synthesise their nicer voices on the vendor's servers,
    which sends the word off the device. One public headword is a small
    exposure, but the device can usually do it, and preferring that keeps it
    here."""
    js = read_speech_js()
    assert "localService" in js
