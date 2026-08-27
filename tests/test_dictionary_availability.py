"""Merriam-Webster is offered only where it can work (kuantorflow#365).

The Settings panel offered it exactly as it offers Oxford, and choosing it on
the deployed site produced cards with **no English explanation** — silently,
because `merriam-webster.com` answers 403 to PythonAnywhere's IPs and a
dictionary that returns nothing is not an error anywhere in `lookup_word()`.
kuantorflow#110 measured that on 17 July 2026 and it has been true since.

So the dictionaries now follow the rule the translators got in
kuantorflow#353: one registry, availability read from the environment at call
time, the panel greying what this deployment has no key for rather than hiding
it (kuantorflow#261), and a stored choice that cannot run falling back instead
of failing.

**The key gates the choice and buys nothing yet.** The backend still scrapes
and still sends no key anywhere; kuantorflow#110 is what makes
`MERRIAM_WEBSTER_API_KEY` mean something. That is why the tests below are
about *availability* and never assert that a request carried it.
"""

import pytest

import parsers


@pytest.fixture()
def no_key(monkeypatch):
    monkeypatch.delenv("MERRIAM_WEBSTER_API_KEY", raising=False)


@pytest.fixture()
def with_key(monkeypatch):
    monkeypatch.setenv("MERRIAM_WEBSTER_API_KEY", "test-key-never-used")


# --- the registry -----------------------------------------------------------

def test_oxford_needs_no_key_and_is_always_available(no_key):
    """Which is why the panel has no "nothing configured" branch on this half,
    unlike the translators, where empty is a real state (#349)."""
    oxford = parsers._dictionary_by_slug("oxford")

    assert oxford.key_env is None
    assert oxford in parsers.available_dictionaries()


def test_merriam_webster_is_absent_until_its_key_is_set(no_key):
    available = parsers.available_dictionaries()

    assert [d.slug for d in available] == ["oxford"]
    assert parsers._dictionary_by_slug("merriam-webster") not in available


def test_the_key_is_read_at_call_time(no_key, monkeypatch):
    """Never captured at import — the rule `available_translators()` follows,
    and what lets a key be added to a deployment without a code change."""
    assert len(parsers.available_dictionaries()) == 1

    monkeypatch.setenv("MERRIAM_WEBSTER_API_KEY", "test-key-never-used")

    assert [d.slug for d in parsers.available_dictionaries()] == [
        "oxford", "merriam-webster"]


def test_the_fetcher_is_held_by_name(with_key):
    """#353's own scar: a registry that stores the function object captures it
    at import, and every test that patches a backend is silently reaching the
    real one."""
    mw = parsers._dictionary_by_slug("merriam-webster")

    assert isinstance(mw.fetch_name, str)
    assert mw.fetch is parsers._merriam_webster_entry


# --- the dispatch -----------------------------------------------------------

def test_an_unavailable_choice_falls_back_to_oxford(no_key):
    assert parsers._dictionary_backend("merriam-webster") \
        is parsers._fetch_oxford_entry


def test_the_choice_is_honoured_once_the_key_is_there(with_key):
    assert parsers._dictionary_backend("merriam-webster") \
        is parsers._merriam_webster_entry


def test_an_unknown_slug_still_falls_back(no_key):
    """Unchanged behaviour, pinned because the dispatch was rewritten around
    it: the old version got this from `dict.get()`'s default."""
    assert parsers._dictionary_backend("nonesuch") is parsers._fetch_oxford_entry


def test_the_stored_setting_is_left_alone(user_client, no_key):
    """Not coerced onto the fallback.

    #352 did coerce an account off a retired provider, and that was right —
    the option was gone. This is different: the option exists and this
    deployment is not set up for it, so an account that asks for
    Merriam-Webster should still be asking for it the day a key appears.
    """
    stored = user_client.post(
        "/settings", json={"explanatory_dictionary": "merriam-webster"}).get_json()

    assert stored["settings"]["explanatory_dictionary"] == "merriam-webster"

    # And still stored on the next page, where the panel shows it chosen —
    # greyed, checked, and waiting for a key rather than quietly moved.
    block = _dictionary_block(user_client.get("/").get_data(as_text=True))
    merriam = block.split('value="merriam-webster"')[1].split(">")[0]
    assert "checked" in merriam and "disabled" in merriam


def test_a_lookup_falls_back_rather_than_losing_the_explanation(
        no_key, monkeypatch, action_logs):
    """The bug this ticket is about, from the learner's end.

    With Merriam-Webster chosen and unreachable the card came back with no
    English explanation at all. Now the lookup quietly uses the dictionary that
    works, which is the same shape as #349: a card with less on it beats a card
    with nothing.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-used")
    monkeypatch.setattr(parsers, "_claude_dictionary",
                        lambda word, code: {"noun": ["дім"]})
    monkeypatch.setattr(parsers, "_fetch_oxford_entry",
                        lambda word: ({"noun": ["a building to live in"]}, {}))
    monkeypatch.setattr(parsers, "_merriam_webster_entry",
                        lambda word: pytest.fail("must not be called"))

    card = parsers.lookup_word("house",
                               explanatory_dictionary="merriam-webster")[0]

    assert card["explanation_en"] == "a building to live in"


# --- the panel --------------------------------------------------------------

def _dictionary_block(body):
    return body.split("Explanatory dictionary")[1].split("</fieldset>")[0]


def test_the_panel_greys_it_and_names_the_variable(user_client, no_key):
    block = _dictionary_block(user_client.get("/").get_data(as_text=True))

    assert "Merriam-Webster" in block, "listed, not hidden (#261)"
    assert "MERRIAM_WEBSTER_API_KEY" in block
    assert "settings-option-off" in block
    assert block.count("disabled") == 1, "Oxford stays choosable"


def test_the_panel_offers_it_once_the_key_is_there(user_client, with_key):
    block = _dictionary_block(user_client.get("/").get_data(as_text=True))

    assert "Merriam-Webster" in block
    assert "MERRIAM_WEBSTER_API_KEY" not in block
    assert "disabled" not in block


def test_the_panel_is_rendered_from_the_registry(user_client, with_key,
                                                 monkeypatch):
    """One declaration, so a third dictionary is one entry and not one entry
    plus this markup — `TRANSLATORS` and `ACTIVITIES` before it."""
    third = parsers.Dictionary("cambridge", "Cambridge Dictionary",
                               "_fetch_oxford_entry", "CAMBRIDGE_API_KEY")
    monkeypatch.setattr(parsers, "DICTIONARIES", parsers.DICTIONARIES + (third,))

    block = _dictionary_block(user_client.get("/").get_data(as_text=True))

    assert "Cambridge Dictionary" in block
    assert "CAMBRIDGE_API_KEY" in block
