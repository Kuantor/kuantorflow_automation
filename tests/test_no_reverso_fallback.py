"""The word lookup never falls back to Reverso's dictionary (kuantorflow#526).

When the chosen dictionary (Oxford or Wiktionary) had no entry, `lookup_word()`
asked Reverso's dictionary (`parsers._fetch_definitions()`,
dictionary.reverso.net) and credited the card `reverso`. PythonAnywhere's IPs
are blocked there, so production never got an answer -- but a developer's
machine did, and a gap the chosen dictionary left was filled locally and
invisible until production (#221). The call is gone: a word the chosen
dictionary cannot explain gets no explanation, everywhere.

What stays, on purpose: the Reverso Context scraper (`parse_reverso_word()`),
which still asks `_fetch_definitions()`, and the `reverso` credit on cards that
already carry it.
"""

import pytest
import requests

import cards
import parsers


@pytest.fixture()
def reverso(monkeypatch):
    """Reverso's dictionary, answering -- as it does from a developer's
    machine. Records every call, so a test can say it was never asked."""
    calls = []

    def fetch(word):
        calls.append(word)
        return {"noun": ["a definition only Reverso had"]}

    monkeypatch.setattr(parsers, "_fetch_definitions", fetch)
    return calls


@pytest.fixture()
def translator(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-used")
    monkeypatch.setattr(parsers, "_claude_dictionary",
                        lambda word, code: {"noun": ["застава"]})


@pytest.mark.parametrize("dictionary, entry", [
    ("oxford", "_fetch_oxford_entry"),
    ("wiktionary", "_wiktionary_entry"),
])
def test_a_word_the_dictionary_cannot_explain_never_asks_reverso(
        dictionary, entry, reverso, translator, action_logs, monkeypatch):
    monkeypatch.setattr(parsers, entry, lambda word: ({}, {}))

    (card,) = parsers.lookup_word("bailment", explanatory_dictionary=dictionary)

    assert reverso == [], "Reverso's dictionary was asked"
    assert card["translation_ukr"] == "застава"
    assert "explanation_en" not in card
    assert card.get("explanation_source") is None


def test_a_dictionary_that_fails_does_not_send_the_lookup_to_reverso(
        reverso, translator, action_logs, monkeypatch):
    monkeypatch.setattr(parsers, "_fetch_oxford_entry",
                        lambda word: (_ for _ in ()).throw(
                            requests.ConnectionError("down")))

    (card,) = parsers.lookup_word("bailment", explanatory_dictionary="oxford")

    assert reverso == []
    assert "explanation_en" not in card


def test_the_log_shows_one_dictionary_and_no_fallback(reverso, translator,
                                                       action_logs, monkeypatch):
    monkeypatch.setattr(parsers, "_fetch_oxford_entry", lambda word: ({}, {}))

    parsers.lookup_word("bailment", explanatory_dictionary="oxford")

    log = (action_logs / "dict.log").read_text(encoding="utf-8")
    define = [l for l in log.splitlines() if " DEFINE " in l]
    assert len(define) == 1 and "provider=oxford" in define[0]
    assert "reverso" not in log


def test_no_translation_and_no_entry_is_still_a_failed_lookup(reverso,
                                                              action_logs,
                                                              monkeypatch):
    """Reverso used to be able to rescue this case with a definition alone
    (#349 builds cards from the dictionary when no translator answers)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-used")
    monkeypatch.setattr(parsers, "_claude_dictionary", lambda word, code: {})
    monkeypatch.setattr(parsers, "_fetch_oxford_entry", lambda word: ({}, {}))

    with pytest.raises(ValueError):
        parsers.lookup_word("bailment", explanatory_dictionary="oxford")
    assert reverso == []


# --- kept on purpose --------------------------------------------------------

def test_the_reverso_context_scraper_still_asks_reverso_for_definitions(
        reverso, monkeypatch):
    monkeypatch.setattr(parsers, "_fetch_reverso",
                        lambda word, lang: ({"noun": ["застава"]}, []))
    monkeypatch.setattr(parsers, "_fill_missing_translation", lambda entry: None)

    (card,) = parsers.parse_reverso_word("bailment")

    assert reverso == ["bailment"]
    assert card["explanation_en"] == "a definition only Reverso had"


def test_cards_already_credited_to_reverso_keep_their_credit():
    assert "reverso" in cards.EXPLANATION_SOURCES
