"""Vetting the invented words before the round (kuantorflow#389).

`test_real_or_fake.py` covers the four filters that ask what the **deck**
knows. This covers the one that asks what **English** knows, which is the
difference: the deck knows some 2,500 words where English has hundreds of
thousands, so the local filters make a real word rare rather than impossible.

Measured over 60 rounds of the production deck before this shipped: **17 of
269 generated words had an English Wiktionary entry, landing in one round in
three** -- `defence`, `provision`, `edition`, `version` among them, and
`bailment`, which is the word that opened #258. That is what these tests are
protecting, and it is why the numbers are written down here rather than only
in the ticket.

**No test in this file touches the network.** `parsers.wiktionary_pages()` is
stubbed everywhere, because what is being checked is the *round's* behaviour --
what it offers, what it drops, what it does when the lexicon is silent -- and a
test that depended on Wiktionary being up would fail for reasons that are not
about this code. The one request-shaping rule that cannot be checked that way
(50 titles per request) is asserted against a stubbed `requests.get`.
"""

import random

import pytest

import games
import parsers


# A deck big enough for a trigram to invent from — the same reasoning as
# `test_real_or_fake.py`'s sixty words: a small deck hands its own words back.
DECK = [
    "burglary", "evidence", "custody", "sentence", "verdict", "acquittal",
    "testimony", "prosecute", "defendant", "sentencing", "conviction",
    "magistrate", "probation", "surveillance", "trespass", "forgery",
    "embezzle", "restitution", "arraignment", "indictment", "misconduct",
    "negligence", "plaintiff", "subpoena", "warrant", "custodial",
    "adjourned", "appellate", "prosecutor", "detention", "liability",
    "affidavit", "deposition", "extradite", "injunction", "jurisdiction",
    "manslaughter", "perjury", "precedent", "remanded", "sanction",
    "settlement", "solicitor", "statutory", "tribunal", "acquitted",
    "allegation", "barrister", "clemency", "complainant", "contempt",
    "coroner", "counsel", "custodian", "damages", "defence", "detainee",
    "disclosure", "exonerate", "grievance",
]


@pytest.fixture()
def lexicon(monkeypatch, app_module):
    """A stand-in lexicon. `lexicon.has` is what it claims to know; `.asked`
    records every batch it was given, and `.answer` can be set to None to make
    it unreachable."""

    class Stub:
        def __init__(self):
            self.has, self.asked, self.answer = set(), [], "found"

        def __call__(self, words):
            self.asked.append(list(words))
            if self.answer is None:
                return None
            return {w.lower() for w in words if w.lower() in self.has}

    stub = Stub()
    monkeypatch.setattr(app_module.parsers, "wiktionary_pages", stub)
    return stub


# --- what it drops ----------------------------------------------------------

def test_a_word_the_lexicon_has_is_not_offered(lexicon, app_module):
    """The whole feature, in one assertion.

    The first pass is forced to produce a word the lexicon claims, by taking
    whatever the generator returns and declaring one of them English.
    """
    random.seed(7)
    first = games.pseudowords(DECK, 5, rng=random.Random(7))
    assert first, "the generator has to produce something to reject"
    lexicon.has = {first[0].lower()}

    got = app_module._vetted_pseudowords(DECK, 5, set())

    assert first[0].lower() not in {w.lower() for w in got}


def test_the_round_is_topped_up_after_a_rejection(lexicon, app_module):
    """*Dropped and replaced*, not merely dropped. A round that quietly shrank
    every time the vet worked would trade one visible fault for a quieter
    one — the page would have fewer invented words than it asked for."""
    first = games.pseudowords(DECK, 5, rng=random.Random(7))
    lexicon.has = {first[0].lower()}

    got = app_module._vetted_pseudowords(DECK, 5, set())

    assert len(got) == 5
    assert len(lexicon.asked) >= 2, "it went back to the generator"


def test_a_rejected_word_is_not_offered_again(lexicon, app_module):
    """Rejections are fed back as `known`, which `pseudowords()` treats as both
    exact words *and* stems — so a run that offered `defence` does not come
    back with `defencive`."""
    first = games.pseudowords(DECK, 5, rng=random.Random(7))
    lexicon.has = {first[0].lower()}

    app_module._vetted_pseudowords(DECK, 5, set())

    later = [w.lower() for batch in lexicon.asked[1:] for w in batch]
    assert first[0].lower() not in later


# --- what it does when the lexicon is silent --------------------------------

def test_an_unreachable_lexicon_leaves_the_round_playable(lexicon, app_module):
    """The failure mode that matters more than the feature. A game that will
    not start is worse than one that is occasionally wrong, and #258's dispute
    path is still underneath."""
    lexicon.answer = None

    got = app_module._vetted_pseudowords(DECK, 5, set())

    assert len(got) == 5, "the words are played unvetted"
    assert len(lexicon.asked) == 1, "and it does not retry a dead lexicon"


def test_none_is_not_read_as_nothing_found(lexicon, app_module):
    """The three-state answer, which is the whole reason `wiktionary_pages()`
    returns None rather than an empty set: a request that failed is not a list
    of words that do not exist."""
    lexicon.answer = None
    lexicon.has = {w.lower() for w in DECK}      # would reject everything

    assert len(app_module._vetted_pseudowords(DECK, 5, set())) == 5


# --- bounded ----------------------------------------------------------------

def test_it_gives_up_rather_than_looping(lexicon, app_module):
    """A lexicon that claims *everything* must not spin. `pseudowords()` is
    bounded for the same reason — a deck has only so many words in it, and the
    alternative to a limit is a page that never renders."""
    lexicon.has = {w.lower() for w in DECK} | set()

    class Everything(set):
        def __contains__(self, item):
            return True

    lexicon.has = Everything()

    got = app_module._vetted_pseudowords(DECK, 5, set())

    assert got == []
    assert len(lexicon.asked) <= app_module.VET_ATTEMPTS


def test_the_round_plays_what_it_gets(lexicon, app_module):
    """A short round is allowed; a broken one is not. The caller tops the page
    up with real words, so four invented words means six real ones."""
    first = games.pseudowords(DECK, 5, rng=random.Random(7))
    lexicon.has = {w.lower() for w in first[:3]}

    got = app_module._vetted_pseudowords(DECK, 5, set())

    assert 0 <= len(got) <= 5
    assert all(w.lower() not in lexicon.has for w in got)


# --- where it lives ---------------------------------------------------------

def test_the_generator_itself_stays_offline():
    """`games.pseudowords()` has no network and no database in it, which is why
    it is testable at all and why every filter it holds is a property of the
    deck. This one is a property of English, so it belongs to the route.

    A coupling assertion, and it says so: the day somebody moves the vet into
    `games` for tidiness, the whole module stops being a pure function of a
    word list.
    """
    import inspect

    source = inspect.getsource(games)

    assert "requests" not in source
    assert "wiktionary" not in source.lower()


def test_the_vet_does_not_vouch_for_words_in_confirmed_words(lexicon,
                                                             app_module):
    """#389's one correction to its own ticket.

    `confirmed_words` is rendered back to a learner as "somebody already
    checked, it is real" (#258). The vet tests *existence*, not English, which
    is what makes it one cheap request — and of 26 candidates with a Wiktionary
    page, only 17 were English. Writing existence hits into that table would
    have the app vouching for `concile` on the strength of a Dutch entry.
    """
    first = games.pseudowords(DECK, 5, rng=random.Random(7))
    lexicon.has = {first[0].lower()}
    written = []
    app_module.remember_confirmed_word = lambda word, source: written.append(word)

    app_module._vetted_pseudowords(DECK, 5, set())

    assert written == []


# --- the request itself -----------------------------------------------------

def test_it_asks_fifty_titles_at_a_time(monkeypatch):
    """Wikimedia's limit for an anonymous client, and the reason this is one
    request per round rather than one per word."""
    sent = []

    class Reply:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"query": {"pages": []}}

    def fake_get(url, params=None, headers=None, timeout=None):
        sent.append(params["titles"].split("|"))
        return Reply()

    monkeypatch.setattr(parsers.requests, "get", fake_get)

    parsers.wiktionary_pages(["w%03d" % i for i in range(120)])

    assert len(sent) == 3
    assert all(len(batch) <= 50 for batch in sent)


def test_a_failed_request_answers_none_rather_than_a_partial_set(monkeypatch):
    """One failed chunk poisons the whole answer. A caller told "these three
    exist" from half a list would offer the unchecked half as vetted."""
    def boom(url, params=None, headers=None, timeout=None):
        raise OSError("wikimedia is down")

    monkeypatch.setattr(parsers.requests, "get", boom)

    assert parsers.wiktionary_pages(["alpha", "beta"]) is None


def test_it_asks_nobody_about_an_empty_list(monkeypatch):
    """A round that generated nothing must not make a request to prove it."""
    def boom(*a, **kw):
        raise AssertionError("no request should have been made")

    monkeypatch.setattr(parsers.requests, "get", boom)

    assert parsers.wiktionary_pages([]) == set()
