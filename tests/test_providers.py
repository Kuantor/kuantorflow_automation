"""Provider dispatch in parsers.lookup_word and the #21 fetchers (offline).

Network access is stubbed throughout: dispatch tests replace the backend
functions, fetcher tests replace requests.get/post (or the _bing_api seam)
with canned responses captured from the real services.
"""

import pytest
import requests

import parsers


# --- lookup_word dispatch (#20) -----------------------------------------------

GOOGLE = {"noun": ["дім"]}
BING = {"noun": ["будинок"]}


@pytest.fixture()
def backends(monkeypatch):
    """Replace every network-touching backend, recording who was called."""
    calls = []

    def backend(name, result):
        def fetch(*args, **kwargs):
            calls.append(name)
            if isinstance(result, Exception):
                raise result
            return result
        return fetch

    def install(google=GOOGLE, bing=BING, oxford={}, mw={}, reverso={}):
        monkeypatch.setattr(parsers, "_google_dictionary", backend("google", google))
        monkeypatch.setattr(parsers, "_bing_dictionary", backend("bing", bing))
        monkeypatch.setattr(parsers, "_fetch_oxford_definitions", backend("oxford", oxford))
        monkeypatch.setattr(parsers, "_fetch_merriam_webster_definitions", backend("mw", mw))
        monkeypatch.setattr(parsers, "_fetch_definitions", backend("reverso", reverso))
        return calls

    return install


def test_default_lookup_uses_google(backends):
    calls = backends()
    cards = parsers.lookup_word("house")
    assert cards[0]["translation_ukr"] == "дім"
    assert "google" in calls and "bing" not in calls


def test_bing_translator_is_used_when_selected(backends):
    calls = backends()
    cards = parsers.lookup_word("house", translator="bing")
    assert cards[0]["translation_ukr"] == "будинок"
    assert "bing" in calls and "google" not in calls


def test_failing_bing_falls_back_to_google(backends):
    backends(bing=requests.ConnectionError("blocked"))
    cards = parsers.lookup_word("house", translator="bing")
    assert cards[0]["translation_ukr"] == "дім"


def test_empty_bing_falls_back_to_google(backends):
    backends(bing={})
    cards = parsers.lookup_word("house", translator="bing")
    assert cards[0]["translation_ukr"] == "дім"


def test_selected_dictionary_provides_definitions(backends):
    calls = backends(mw={"noun": ["a building for people to live in"]})
    cards = parsers.lookup_word("house", explanatory_dictionary="merriam-webster")
    assert cards[0]["explanation_en"] == "a building for people to live in"
    assert "reverso" not in calls, "no fallback when the choice delivered"


def test_empty_dictionary_falls_back_to_reverso(backends):
    calls = backends(oxford={}, reverso={"noun": ["reverso definition"]})
    cards = parsers.lookup_word("house", explanatory_dictionary="oxford")
    assert cards[0]["explanation_en"] == "reverso definition"
    assert calls.count("oxford") == 1


def test_definition_failures_never_break_the_lookup(backends):
    backends(oxford=requests.ConnectionError("down"),
             reverso=requests.ConnectionError("down"))
    cards = parsers.lookup_word("house")
    assert cards[0]["translation_ukr"] == "дім"
    assert "explanation_en" not in cards[0]


# --- The Bing fetcher (#21) ---------------------------------------------------

BING_LOOKUP = [{"translations": [
    {"posTag": "NOUN", "displayTarget": "будинок"},
    {"posTag": "NOUN", "displayTarget": "дім"},
    {"posTag": "NOUN", "displayTarget": "будинок"},     # duplicate -> dropped
    {"posTag": "VERB", "displayTarget": "розмістити"},
    {"posTag": "WEIRD", "displayTarget": "хата"},       # unknown tag -> other
]}]


def test_bing_dictionary_groups_by_pos(monkeypatch):
    monkeypatch.setattr(parsers, "_bing_api", lambda path, word, target: BING_LOOKUP)
    result = parsers._bing_dictionary("house", "uk")
    assert result == {"noun": ["будинок", "дім"],
                      "verb": ["розмістити"],
                      "other": ["хата"]}


def test_bing_dictionary_plain_translation_fallback(monkeypatch):
    responses = {
        "dictionary/lookup": [{"translations": []}],
        "translate": [{"translations": [{"text": "Тримайте зв'язок"}]}],
    }
    monkeypatch.setattr(parsers, "_bing_api",
                        lambda path, word, target: responses[path])
    result = parsers._bing_dictionary("keep in touch", "uk")
    assert result == {"other": ["Тримайте зв'язок"]}


# --- The scraping fetchers (#21) ----------------------------------------------

class FakeResponse:
    def __init__(self, text="", status_code=200, url=""):
        self.text = text
        self.status_code = status_code
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


OXFORD_BASE = "https://www.oxfordlearnersdictionaries.com/definition/english"

OXFORD_VERB_PAGE = f"""
<html><body>
<div class="webtop"><h1 class="headword">run</h1><span class="pos">verb</span></div>
<ol><li class="sense"><span class="def">to move using your legs, going faster than when you walk</span></li></ol>
<div id="relatedentries">
  <a href="{OXFORD_BASE}/run_2"><span>run</span> noun</a>
  <a href="{OXFORD_BASE}/run-up_1"><span>run-up</span> noun</a>
  <a href="{OXFORD_BASE}/ladder_1"><span>ladder</span> noun</a>
</div>
</body></html>
"""

OXFORD_NOUN_PAGE = f"""
<html><body>
<div class="webtop"><h1 class="headword">run</h1><span class="pos">noun</span></div>
<ol><li class="sense"><span class="def">an act of running</span></li></ol>
</body></html>
"""


def test_oxford_follows_sibling_entries_only(monkeypatch):
    fetched = []

    def fake_get(url, **kwargs):
        fetched.append(url)
        if url.endswith("/run"):
            return FakeResponse(OXFORD_VERB_PAGE, url=f"{OXFORD_BASE}/run_1")
        return FakeResponse(OXFORD_NOUN_PAGE, url=url)

    monkeypatch.setattr(parsers.requests, "get", fake_get)
    result = parsers._fetch_oxford_definitions("run")
    assert result == {
        "verb": ["to move using your legs, going faster than when you walk"],
        "noun": ["an act of running"],
    }
    # run_2 is a sibling entry of the same headword; run-up and ladder are not
    assert fetched == [f"{OXFORD_BASE}/run", f"{OXFORD_BASE}/run_2"]


def test_oxford_unknown_word_returns_empty(monkeypatch):
    monkeypatch.setattr(parsers.requests, "get",
                        lambda url, **kwargs: FakeResponse(status_code=404))
    assert parsers._fetch_oxford_definitions("qwertyzzz") == {}


MW_PAGE = """
<html><body>
<div id="dictionary-entry-1">
  <div class="parts-of-speech"><a>verb</a></div>
  <span class="dtText">: to go faster than a walk</span>
  <span class="dtText">: to go faster than a walk</span>
</div>
<div id="dictionary-entry-2">
  <div class="parts-of-speech"><a>noun</a></div>
  <span class="dtText">: an act or the action of running</span>
</div>
</body></html>
"""


def test_merriam_webster_parses_entries(monkeypatch):
    monkeypatch.setattr(parsers.requests, "get",
                        lambda url, **kwargs: FakeResponse(MW_PAGE))
    result = parsers._fetch_merriam_webster_definitions("run")
    assert result == {"verb": ["to go faster than a walk"],
                      "noun": ["an act or the action of running"]}


def test_merriam_webster_unknown_word_returns_empty(monkeypatch):
    monkeypatch.setattr(parsers.requests, "get",
                        lambda url, **kwargs: FakeResponse(status_code=404))
    assert parsers._fetch_merriam_webster_definitions("qwertyzzz") == {}
