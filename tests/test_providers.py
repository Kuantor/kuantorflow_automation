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
    """Replace every network-touching backend, recording who was called.

    The dictionary backends are stubbed at the **entry** functions since #225 —
    `_fetch_oxford_entry` and `_merriam_webster_entry` — because those are what
    `_dictionary_backend()` now returns and therefore the only things
    `lookup_word()` calls. Stubbing the definitions-only fetchers underneath them
    would leave the real entry functions in the call path, and the "offline"
    tests would quietly make live requests to Oxford. That happened while #225
    was being written; it is why the seam moved rather than a branch being added.

    `oxford=` and `mw=` still take a plain `{pos: [defs]}` for readability. The
    tuple the entry shape returns is assembled here, with `examples=` for the
    tests that care about the second half.
    """
    calls = []

    def backend(name, result):
        def fetch(*args, **kwargs):
            calls.append(name)
            if isinstance(result, Exception):
                raise result
            return result
        return fetch

    def install(google=GOOGLE, bing=BING, oxford={}, mw={}, reverso={},
                examples={}):
        monkeypatch.setattr(parsers, "_google_dictionary", backend("google", google))
        monkeypatch.setattr(parsers, "_bing_dictionary", backend("bing", bing))
        monkeypatch.setattr(parsers, "_fetch_oxford_entry", backend(
            "oxford", oxford if isinstance(oxford, Exception) else (oxford, examples)))
        monkeypatch.setattr(parsers, "_merriam_webster_entry", backend(
            "mw", mw if isinstance(mw, Exception) else (mw, {})))
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


# --- both of Oxford's sense shapes (#221) --------------------------------
#
# Oxford wraps a sense's definition in a `span.sensetop` whenever that sense
# carries extra furniture at the top of it — always on a single-sense entry, and
# on the *first* sense of many multi-sense ones. The definition is then a
# grandchild of `.sense`, and the `.sense > .def` selector this parser used until
# #221 walked straight past it.
#
# Every Oxford fixture above happens to use the direct-child shape, which is
# exactly why the bug passed the suite for so long. These two are trimmed from
# the real `punctual` and `hedge` pages so that a selector handling one shape and
# not the other cannot pass again.

OXFORD_SINGLE_SENSE_PAGE = """
<html><body>
<div class="webtop"><h1 class="headword">punctual</h1><span class="pos">adjective</span></div>
<ol class="sense_single"><li class="sense"><span class="sensetop">
  <span class="def">happening or doing something at the arranged or correct time; not late</span>
</span></li></ol>
</body></html>
"""

# `hedge`, which has one of each in a single entry — and the *primary* sense is
# the wrapped one, so the old selector returned only the financial meaning.
OXFORD_MIXED_SENSES_PAGE = """
<html><body>
<div class="webtop"><h1 class="headword">hedge</h1><span class="pos">noun</span></div>
<ol class="senses_multiple">
  <li class="sense"><span class="sensetop">
    <span class="def">a row of bushes or small trees planted close together</span>
  </span></li>
  <li class="sense">
    <span class="def">a way of protecting yourself against the loss of something</span>
  </li>
</ol>
</body></html>
"""


def _page(monkeypatch, html):
    monkeypatch.setattr(parsers.requests, "get",
                        lambda url, **kwargs: FakeResponse(html, url=url))


# --- Oxford's example sentences (#225) -----------------------------------
#
# Examples live inside `li.sense`, exactly where definitions do, so they come out
# of the same walk. Two things about the markup earn tests of their own: an
# example may be preceded by a `span.cf` carrying the grammar pattern it
# illustrates, which reads as a broken sentence on a flashcard; and both sense
# shapes from #221 must work here too, since a selector that only handles one is
# precisely the bug that hid for months.

OXFORD_EXAMPLES_PAGE = """
<html><body>
<div class="webtop"><h1 class="headword">hedge</h1><span class="pos">noun</span></div>
<ol class="senses_multiple">
  <li class="sense"><span class="sensetop">
    <span class="def">a row of bushes</span>
    <ul class="examples">
      <li><span class="x">a privet hedge</span></li>
      <li><span class="x">Trim the hedge.</span></li>
    </ul>
  </span></li>
  <li class="sense">
    <span class="def">a way of protecting yourself</span>
    <ul class="examples">
      <li><span class="cf">be hedged (with something)</span><span class="x">His belief was hedged with doubt.</span></li>
    </ul>
  </li>
</ol>
</body></html>
"""


def test_oxford_takes_example_sentences(monkeypatch):
    _page(monkeypatch, OXFORD_EXAMPLES_PAGE)

    _, examples = parsers._fetch_oxford_entry("hedge")
    assert examples == {"noun": ["a privet hedge", "Trim the hedge.",
                                 "His belief was hedged with doubt."]}


def test_oxford_examples_come_from_both_sense_shapes(monkeypatch):
    """The wrapped sense and the unwrapped one, in one entry — #221's lesson
    applied to a second selector rather than relearned later."""
    _page(monkeypatch, OXFORD_EXAMPLES_PAGE)

    examples = parsers._fetch_oxford_entry("hedge")[1]["noun"]
    assert "a privet hedge" in examples, "the span.sensetop sense"
    assert "His belief was hedged with doubt." in examples, "the direct-child sense"


def test_oxford_drops_the_grammar_pattern_before_the_sentence(monkeypatch):
    """`span.cf` is the pattern the example illustrates — useful beside a
    dictionary heading, a broken sentence on a card:
    'be hedged (with something) His belief was hedged with doubt.'"""
    _page(monkeypatch, OXFORD_EXAMPLES_PAGE)

    examples = parsers._fetch_oxford_entry("hedge")[1]["noun"]
    assert "His belief was hedged with doubt." in examples
    assert not any("be hedged (with something)" in e for e in examples)


def test_oxford_keeps_a_whole_example_when_there_is_no_x_span(monkeypatch):
    """A fallback, not a guess: if Oxford changes how it wraps a sentence, an
    example is still worth having."""
    _page(monkeypatch,
          '<html><body><div class="webtop"><span class="pos">noun</span></div>'
          '<ol><li class="sense"><span class="def">a thing</span>'
          '<ul class="examples"><li>a bare example</li></ul>'
          '</li></ol></body></html>')

    assert parsers._fetch_oxford_entry("bare")[1] == {"noun": ["a bare example"]}


def test_oxford_caps_the_examples_it_keeps(monkeypatch):
    """Oxford gives a popular word dozens — 41 for one of #203's words."""
    items = "".join(f'<li><span class="x">example {n}</span></li>'
                    for n in range(1, 12))
    _page(monkeypatch,
          '<html><body><div class="webtop"><span class="pos">noun</span></div>'
          '<ol><li class="sense"><span class="def">a thing</span>'
          f'<ul class="examples">{items}</ul></li></ol></body></html>')

    examples = parsers._fetch_oxford_entry("many")[1]["noun"]
    assert len(examples) == parsers.MAX_EXAMPLES
    assert examples[0] == "example 1", "Oxford's order is its order of importance"


def test_a_word_with_no_examples_still_returns_its_definitions(monkeypatch):
    """`burnout` is the real case: Oxford defines it and gives no sentences."""
    _page(monkeypatch, OXFORD_SINGLE_SENSE_PAGE)

    definitions, examples = parsers._fetch_oxford_entry("punctual")
    assert definitions and examples == {}


def test_oxford_definitions_alone_still_answer_the_shared_contract(monkeypatch):
    """`_fetch_oxford_definitions()` keeps returning `{pos: [defs]}`. It is the
    shape the other dictionaries return, and `seed_topics.py --check-oxford`
    calls it directly."""
    _page(monkeypatch, OXFORD_EXAMPLES_PAGE)

    assert parsers._fetch_oxford_definitions("hedge") == {
        "noun": ["a row of bushes", "a way of protecting yourself"]}


# --- matching parts of speech across the two providers (#228) ------------
#
# The translator names the parts of speech a card is created for; the dictionary
# names the ones it has text for. They do not always use the same word for the
# same thing, and matching was exact string equality — so text that had already
# been fetched was thrown away. `must` is the case: Google reports an *auxiliary
# verb*, Oxford a *modal verb*.
#
# The synonym table is applied to **both** sides and only for matching. A card
# keeps the label its translator gave it, because that is what the learner sees.

OXFORD_TWO_POS_PAGE = """
<html><body>
<div class="webtop"><h1 class="headword">hello</h1><span class="pos">exclamation, noun</span></div>
<ol><li class="sense"><span class="def">used as a greeting</span>
  <ul class="examples"><li><span class="x">Hello there!</span></li></ul>
</li></ol>
</body></html>
"""


def test_an_oxford_entry_can_head_several_parts_of_speech(monkeypatch):
    """`hello` is headed "exclamation, noun" and `both` "determiner, pronoun".
    The whole string used to be the key, and `exclamation,noun` matches nothing
    any translator reports — so the entry's text was unreachable."""
    _page(monkeypatch, OXFORD_TWO_POS_PAGE)

    definitions, examples = parsers._fetch_oxford_entry("hello")

    assert definitions == {"exclamation": ["used as a greeting"],
                           "noun": ["used as a greeting"]}
    assert examples == {"exclamation": ["Hello there!"],
                        "noun": ["Hello there!"]}


@pytest.mark.parametrize("text,expected", [
    ("noun", ["noun"]),
    ("exclamation,noun", ["exclamation", "noun"]),
    ("determiner,pronoun,adverb", ["determiner", "pronoun", "adverb"]),
    ("modal verb", ["modal verb"]),
    (" , ", ["other"]),
    ("", ["other"]),
])
def test_the_pos_heading_is_split_on_commas(text, expected):
    assert parsers._oxford_poses(text) == expected


def test_the_dictionarys_modal_verb_reaches_googles_auxiliary_verb(backends):
    """The #228 case, and the reason the ticket exists. Same sense, two names —
    so the definition was discarded *and* the card was left blank."""
    backends(google={"auxiliary verb": ["мусити"], "noun": ["необхідність"]},
             oxford={"modal verb": ["used to say that something is necessary"],
                     "noun": ["something you must do"]},
             examples={"modal verb": ["You must be tired."]})

    cards = {c["pos"]: c for c in parsers.lookup_word("must")}

    assert cards["auxiliary verb"]["explanation_en"] ==         "used to say that something is necessary"
    assert cards["auxiliary verb"]["examples_en"] == ["You must be tired."]
    assert cards["noun"]["explanation_en"] == "something you must do"


def test_the_card_keeps_the_label_its_translator_gave_it(backends):
    """Matching is canonical; the card is not. Renaming a learner's card to
    "modal verb" because the dictionary says so would change what they see."""
    backends(google={"auxiliary verb": ["мусити"]},
             oxford={"modal verb": ["necessary"]})

    cards = parsers.lookup_word("must")

    assert [c["pos"] for c in cards] == ["auxiliary verb"]
    assert "modal verb" not in [c["pos"] for c in cards]


def test_googles_interjection_meets_oxfords_exclamation(backends):
    backends(google={"interjection": ["привіт"]},
             oxford={"exclamation": ["used as a greeting"]})

    card = parsers.lookup_word("hello")[0]
    assert card["explanation_en"] == "used as a greeting"


def test_an_exact_match_is_never_displaced_by_a_synonym(backends):
    """When the translator reports both, each keeps its own text — the index is
    first-wins on the card's own label."""
    backends(google={"verb": ["робити"], "auxiliary verb": ["мусити"]},
             oxford={"verb": ["ordinary verb sense"],
                     "modal verb": ["modal sense"]})

    cards = {c["pos"]: c for c in parsers.lookup_word("must")}

    assert cards["verb"]["explanation_en"] == "ordinary verb sense"
    assert cards["auxiliary verb"]["explanation_en"] == "modal sense"


# --- the `other` bucket -------------------------------------------------


def test_an_other_card_adopts_the_only_entry_the_dictionary_had(backends):
    """`other` is what _google_dictionary() falls back to when Google has no
    dictionary entry, so it is not a part of speech and can never match. One
    unplaced entry is unambiguously its text — `overbook` is the real case."""
    backends(google={"other": ["перебронювати"]},
             oxford={"verb": ["to sell more tickets than there are seats"]},
             examples={"verb": ["The flight was overbooked."]})

    card = parsers.lookup_word("overbook")[0]

    assert card["pos"] == "other", "the label is not invented"
    assert card["explanation_en"] == "to sell more tickets than there are seats"
    assert card["examples_en"] == ["The flight was overbooked."]


def test_an_other_card_takes_nothing_when_the_entry_is_ambiguous(backends):
    """Two unplaced entries and there is no way to tell which belongs to it, so
    it keeps its translations and no English text — a guess would be worse."""
    backends(google={"other": ["щось"]},
             oxford={"noun": ["a thing"], "verb": ["to do a thing"]})

    card = parsers.lookup_word("thing")[0]
    assert "explanation_en" not in card


# --- what must not happen ------------------------------------------------


def test_a_part_of_speech_the_dictionary_cannot_explain_keeps_its_card(backends):
    """The premise of #228 after it was corrected: a translation is enough to
    keep a card. Google over-reports parts of speech — `hedge` as an adjective —
    and those cards stay, with their translations and no English text."""
    backends(google={"noun": ["живопліт"], "verb": ["ухилятися"],
                     "adjective": ["живоплітний"]},
             oxford={"noun": ["a row of bushes"], "verb": ["to avoid answering"]})

    cards = {c["pos"]: c for c in parsers.lookup_word("hedge")}

    assert set(cards) == {"noun", "verb", "adjective"}, "no card was removed"
    assert cards["adjective"]["translation_ukr"] == "живоплітний"
    assert "explanation_en" not in cards["adjective"]


def test_an_unmatched_definition_is_discarded_rather_than_misplaced(backends):
    """Decided deliberately (#228): a definition whose part of speech has no card
    is dropped. Attaching it to a different sense would be a confidently wrong
    card, which is the #221 lesson, and creating one would mean a card with an
    explanation and no translation in a bilingual app."""
    backends(google={"noun": ["криниця"]},
             oxford={"noun": ["a hole for water"],
                     "determiner": ["nothing should receive this"]})

    cards = parsers.lookup_word("well")

    assert len(cards) == 1 and cards[0]["pos"] == "noun"
    assert cards[0]["explanation_en"] == "a hole for water"


# --- the examples reaching the card -------------------------------------


def test_a_lookup_puts_the_examples_on_the_matching_card(backends):
    """Grouped by part of speech, like the definition — so a card can have a
    translation and neither, which is what happens when the translator finds a
    part of speech the dictionary does not list."""
    backends(google={"noun": ["дім"], "verb": ["розмістити"]},
             oxford={"noun": ["a building"]},
             examples={"noun": ["We live in a big house."]})

    cards = {c["pos"]: c for c in parsers.lookup_word("house")}

    assert cards["noun"]["examples_en"] == ["We live in a big house."]
    assert "examples_en" not in cards["verb"], "no examples for that sense"


def test_examples_reach_the_card_as_a_list(backends):
    """`examples_en` is one of `utils.LIST_FIELDS` and stored as JSON, so the
    card page can show them as separate sentences rather than one run-on."""
    backends(oxford={"noun": ["a building"]},
             examples={"noun": ["One.", "Two."]})

    card = parsers.lookup_word("house")[0]
    assert card["examples_en"] == ["One.", "Two."]


def test_the_reverso_fallback_supplies_no_examples(backends):
    """It answers with definitions only, and Reverso Context — where examples
    would come from — is IP-blocked from PythonAnywhere anyway."""
    backends(oxford={}, reverso={"noun": ["reverso definition"]})

    card = parsers.lookup_word("house", explanatory_dictionary="oxford")[0]
    assert card["explanation_en"] == "reverso definition"
    assert "examples_en" not in card


def test_merriam_webster_supplies_no_examples(backends):
    """It has them on the page; extracting them is not #225, and it is
    unreachable from PythonAnywhere."""
    backends(mw={"noun": ["a building for people to live in"]})

    card = parsers.lookup_word("house", explanatory_dictionary="merriam-webster")[0]
    assert card["explanation_en"] == "a building for people to live in"
    assert "examples_en" not in card


def test_a_dictionary_that_fails_costs_the_examples_and_nothing_else(backends):
    backends(oxford=requests.ConnectionError("down"),
             reverso=requests.ConnectionError("down"))

    card = parsers.lookup_word("house")[0]
    assert card["translation_ukr"] == "дім"
    assert "explanation_en" not in card and "examples_en" not in card


def test_oxford_reads_a_single_sense_entry(monkeypatch):
    """The #221 bug itself. A single-sense entry is the common shape for precise
    vocabulary, and it returned nothing at all — 143 of the 360 words in #203's
    list, including `punctual`, `resign` and `algorithm`."""
    _page(monkeypatch, OXFORD_SINGLE_SENSE_PAGE)

    assert parsers._fetch_oxford_definitions("punctual") == {
        "adjective": ["happening or doing something at the arranged or correct "
                      "time; not late"]}


def test_oxford_keeps_the_primary_sense_of_a_mixed_entry(monkeypatch):
    """The worse half of #221: when one entry holds both shapes, the wrapped
    sense is usually the *first* one. The old selector dropped it and kept a
    later one, so `hedge` was defined only as a financial instrument — a
    confidently wrong card rather than an empty one."""
    _page(monkeypatch, OXFORD_MIXED_SENSES_PAGE)

    assert parsers._fetch_oxford_definitions("hedge") == {
        "noun": ["a row of bushes or small trees planted close together",
                 "a way of protecting yourself against the loss of something"]}


def test_oxford_keeps_the_senses_in_the_page_order(monkeypatch):
    """Which is Oxford's order of importance, and what makes the first
    definition on a card the one a learner most likely wants."""
    _page(monkeypatch, OXFORD_MIXED_SENSES_PAGE)

    defs = parsers._fetch_oxford_definitions("hedge")["noun"]
    assert defs[0].startswith("a row of bushes")


def test_oxford_still_caps_the_definitions_it_keeps(monkeypatch):
    """A descendant selector reaches more nodes, so the cap earns a test: an
    entry with many senses must not put ten definitions on one card."""
    senses = "".join(
        f'<li class="sense"><span class="sensetop"><span class="def">'
        f'sense number {n}</span></span></li>' for n in range(1, 9))
    _page(monkeypatch,
          '<html><body><div class="webtop"><span class="pos">noun</span></div>'
          f'<ol class="senses_multiple">{senses}</ol></body></html>')

    defs = parsers._fetch_oxford_definitions("many")["noun"]
    assert len(defs) == parsers.MAX_DEFINITIONS
    assert defs[0] == "sense number 1"


def test_oxford_does_not_repeat_a_definition_it_has_already_taken(monkeypatch):
    """The de-duplication predates #221 and matters more now: the wrapped and
    unwrapped shapes both being reachable makes a repeat easier to hit."""
    _page(monkeypatch,
          '<html><body><div class="webtop"><span class="pos">noun</span></div>'
          '<ol><li class="sense"><span class="sensetop">'
          '<span class="def">the same words</span></span></li>'
          '<li class="sense"><span class="def">the same words</span></li>'
          '</ol></body></html>')

    assert parsers._fetch_oxford_definitions("dup") == {"noun": ["the same words"]}


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
