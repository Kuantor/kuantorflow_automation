"""Scraped text keeps its punctuation tight (kuantorflow#359).

Examples arrived reading `Are your grandparents still alive ?`, and it looked
sporadic until you see what decides it. Every extraction reads a node as
`get_text(" ", strip=True)`, and that separator is load-bearing — without it
Oxford's markup glues words together. Its cost is a space wherever an element
ends and punctuation follows, which is exactly what happens when a sentence
ends on the word being looked up. A lookup's own examples are the sentences
most likely to do that: all three for *alive* did.

So the two halves are tested together on purpose. A fix that drops the
separator makes `test_words_are_still_separated` fail, and that test is the
whole reason the tidy-up exists as a second step rather than a simpler one.

Everything is stubbed: no network, no database.
"""

import pytest
import requests

import parsers


class FakeResponse:
    def __init__(self, text="", status_code=200, url=""):
        self.text = text
        self.status_code = status_code
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


# Oxford marks the headword up inside its own examples, which is what puts the
# closing punctuation in a text node of its own.
OXFORD_ALIVE = """
<html><body>
<div class="webtop"><h1 class="headword">alive</h1><span class="pos">adjective</span></div>
<ol><li class="sense">
  <span class="def">living, not dead (<span class="eq">=</span> still breathing)</span>
  <ul class="examples">
    <li><span class="x">Are your grandparents still <span class="cl">alive</span>?</span></li>
    <li><span class="x">Doctors managed to keep the baby <span class="cl">alive</span>.</span></li>
    <li><span class="x">She had to steal food just to stay <span class="cl">alive</span>.</span></li>
  </ul>
</li></ol>
</body></html>
"""

OXFORD_LITERACY = """
<html><body>
<div class="webtop"><h1 class="headword">literacy</h1><span class="pos">noun</span></div>
<ol><li class="sense">
  <span class="def">the ability to read and write</span>
  <ul class="examples">
    <li><span class="x">Most of the students need help with <span class="cl">literacy</span> and numeracy.</span></li>
  </ul>
</li></ol>
</body></html>
"""


@pytest.fixture()
def oxford(monkeypatch):
    """Serve one canned Oxford page for any URL asked for."""
    def serve(page):
        monkeypatch.setattr(parsers.requests, "get",
                            lambda url, **kw: FakeResponse(page, url=url))
    return serve


# --- what the learner reads -------------------------------------------------

def test_a_sentence_ending_on_the_headword_keeps_its_full_stop(oxford):
    oxford(OXFORD_ALIVE)
    _, examples = parsers._fetch_oxford_entry("alive")

    assert examples["adjective"] == [
        "Are your grandparents still alive?",
        "Doctors managed to keep the baby alive.",
        "She had to steal food just to stay alive.",
    ]


def test_words_are_still_separated(oxford):
    """The reason the separator is there, and must stay.

    Dropping it is the obvious way to make the test above pass, and it turns
    `...help with <span>literacy</span> and numeracy.` into
    `help withliteracyand numeracy.` — a worse bug, in more sentences, and one
    nobody would think to look for after a punctuation fix.
    """
    oxford(OXFORD_LITERACY)
    _, examples = parsers._fetch_oxford_entry("literacy")

    assert examples["noun"] == [
        "Most of the students need help with literacy and numeracy."]


def test_a_parenthetical_of_its_own_is_not_padded(oxford):
    """Oxford's glosses are their own element, so they arrived as `( = ... )`.

    The notes half of the parser had carried a private fix for exactly this
    since kuantorflow#134; the dictionaries never got one.
    """
    oxford(OXFORD_ALIVE)
    definitions, _ = parsers._fetch_oxford_entry("alive")

    assert definitions["adjective"] == ["living, not dead (= still breathing)"]


REVERSO_CONTEXT = """
<html><body>
<div id="translations-content"><a class="translation adj"><span class="display-term">живий</span></a></div>
<div class="example">
  <div class="src"><span class="text">He is still <em>alive</em>.</span></div>
  <div class="trg"><span class="text">Він досі <em>живий</em>.</span></div>
</div>
</body></html>
"""


def test_reverso_context_examples_are_tidied_on_both_sides(monkeypatch):
    """Both halves of the pair: the target sentence is a card field too."""
    monkeypatch.setattr(parsers.requests, "get",
                        lambda url, **kw: FakeResponse(REVERSO_CONTEXT, url=url))
    _, examples = parsers._fetch_reverso("alive", "ukrainian")

    assert examples == [("He is still alive.", "Він досі живий.")]


MERRIAM = """
<html><body>
<div id="dictionary-entry-1">
  <div class="parts-of-speech"><a>adjective</a></div>
  <span class="dtText">: having life : not <span class="mw_t_wi">dead</span>.</span>
</div>
</body></html>
"""


def test_merriam_webster_senses_too(monkeypatch):
    """Merriam-Webster separates senses with a spaced colon, and it loses the
    space here — `having life : not dead` becomes `having life: not dead`.

    Deliberate, and the same call the parser already made: it strips the
    leading `:` off every sense, because a card is not a dictionary entry and
    reads as English rather than as notation.
    """
    monkeypatch.setattr(parsers.requests, "get",
                        lambda url, **kw: FakeResponse(MERRIAM, url=url))

    assert parsers._fetch_merriam_webster_definitions("alive") == {
        "adjective": ["having life: not dead."]}


# --- the normaliser itself --------------------------------------------------

@pytest.mark.parametrize("raw,tidy", [
    ("still alive .", "still alive."),
    ("still alive ?", "still alive?"),
    ("one , two ; three : four !", "one, two; three: four!"),
    ("contagious ( = spread quickly ) .", "contagious (= spread quickly)."),
    ("He said [ sic ] .", "He said [sic]."),
    ("a campaign to promote adult literacy", "a campaign to promote adult literacy"),
    ("two  spaces\tand a tab", "two spaces and a tab"),
])
def test_readable_cases(raw, tidy):
    assert parsers._readable(raw) == tidy


def test_an_ellipsis_keeps_its_space():
    """`…` is Oxford's omission marker, not the end of a sentence.

    "It's about time you …" is how Oxford writes it, and closing the space
    would be editing the dictionary rather than repairing our own scraping.
    """
    assert parsers._readable("It's about time you …") == "It's about time you …"


# --- the notes half of the parser -------------------------------------------

REVERSO_MHT_BODY = """<html><body>
<p><span style="font-size:15pt;color:#222C31">inquisitive </span><span style="color:#607D8B">Прилагательное</span></p>
<p style="color:#546D79">1.</p>
<p style="color:#222C31">(<span style="font-style:italic">curious</span>) eager to learn or <span style="font-style:italic">know</span>.</p>
<p style="color:#546D79;font-size:10.5pt">Her inquisitive mind sought new <span style="font-style:italic">information</span>.</p>
<p style="color:#0A6CC2">Её любознательный ум искал информацию</p>
<p style="color:#2E3C43">любознательный</p>
</body></html>"""


def _mht(body):
    return (b"From: <saved>\r\nMIME-Version: 1.0\r\n"
            b'Content-Type: multipart/related; boundary="----=_B"\r\n\r\n'
            b"------=_B\r\n"
            b'Content-Type: text/html; charset="utf-8"\r\n'
            b"Content-Transfer-Encoding: 8bit\r\n\r\n"
            + body.encode("utf-8") + b"\r\n------=_B--\r\n")


def test_an_imported_reverso_page_is_tidied_the_same_way(monkeypatch):
    """A copy-paste carries the same footprints, from the same separator.

    This half of the parser had its own private repair for the padded bracket
    (`_clean_explanation`) and nothing for the punctuation. One repair now
    serves both, which is the point: two spellings of the same fix is how the
    second one gets forgotten again.
    """
    monkeypatch.setattr(parsers, "_split_glued_translations",
                        lambda strings: {s: [s] for s in strings})
    cards, _ = parsers.parse_mht_preview(_mht(REVERSO_MHT_BODY), topic="vocab")

    assert len(cards) == 1
    assert cards[0]["explanation_en"] == "(curious) eager to learn or know."
    assert cards[0]["examples_en"] == [
        "Her inquisitive mind sought new information."]
