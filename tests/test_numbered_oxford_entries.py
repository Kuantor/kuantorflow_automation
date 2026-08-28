"""Oxford entries that are numbered (kuantorflow#231).

A word whose senses differ in pronunciation or origin does not answer on its
bare slug: Oxford numbers those entries and lets `/definition/english/can`
return 404. Measured against the live dictionary on 28 August, **ten of
thirty-eight** common words were affected, not the two the ticket was filed
about — `can`, `lead`, `tear`, `wind`, `row`, `close`, `minute`, `live` and
`content` returned nothing at all, and `do` came back explained as an
abbreviation.

Two mechanisms answer two different failures, and neither covers the other's
case. That is the thing to hold here, because either one alone looks like a
fix:

* **the bare slug 404s** → probe `word_1`, `word_2`, … Link-following cannot
  do this: `can_1`'s own related-entries box is *empty*, so nothing on the page
  leads to `can_2`;
* **the bare slug answers with a minor entry** → `do` is the abbreviation and
  its real entries are linked as `do1_1`, which the old pattern (`{slug}_\\d+`)
  could not match.

The costs are asserted too, because this is the kind of fix that quietly
doubles every lookup: an ordinary word must still be one request.

Everything here is stubbed. The live numbers are in the ticket.
"""

import pytest
import requests

import parsers


BASE = "https://www.oxfordlearnersdictionaries.com/definition/english"


def page(pos, definition):
    return f"""
    <html><body>
      <div class="webtop"><span class="pos">{pos}</span></div>
      <ol><li class="sense"><span class="def">{definition}</span></li></ol>
    </body></html>
    """


def page_with_links(pos, definition, links):
    anchors = "".join(f'<a href="{BASE}/{s}"><span>x</span></a>' for s in links)
    return f"""
    <html><body>
      <div class="webtop"><span class="pos">{pos}</span></div>
      <ol><li class="sense"><span class="def">{definition}</span></li></ol>
      <div id="relatedentries">{anchors}</div>
    </body></html>
    """


class Fake:
    def __init__(self, text="", status_code=200, url=""):
        self.text = text
        self.status_code = status_code
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


@pytest.fixture()
def oxford(monkeypatch):
    """Serve a canned site, recording every slug asked for."""
    asked = []

    def install(pages):
        def fake_get(url, **kwargs):
            slug = url.rsplit("/", 1)[-1]
            asked.append(slug)
            if slug not in pages:
                return Fake(status_code=404, url=url)
            landed, body = pages[slug]
            return Fake(body, url=f"{BASE}/{landed}")

        monkeypatch.setattr(parsers.requests, "get", fake_get)
        return asked

    return install


# --- the bare slug 404s: `can` ---------------------------------------------

CAN = {
    "can_1": ("can1", page("modal verb", "to be able to")),
    "can_2": ("can2_1", page("noun", "a metal container")),
    "can_3": ("can2_2", page("verb", "to put food in a can")),
}


def test_a_numbered_word_is_found_by_probing(oxford):
    asked = oxford(CAN)

    definitions, _examples = parsers._fetch_oxford_entry("can")

    assert sorted(definitions) == ["modal verb", "noun", "verb"]
    assert asked == ["can", "can_1", "can_2", "can_3"]


def test_the_probe_stops_at_the_first_miss(oxford):
    """Numbering is contiguous, so the first 404 is the end of the word —
    otherwise every lookup would pay for the whole cap before giving up."""
    asked = oxford({"can_1": ("can1", page("modal verb", "to be able to"))})

    definitions, _ = parsers._fetch_oxford_entry("can")

    assert list(definitions) == ["modal verb"]
    assert asked == ["can", "can_1", "can_2"], "one miss, then it stops"


def test_an_unknown_word_costs_one_extra_request(oxford):
    """`qwertyzzz_1` 404s and the loop ends. One wasted request is the price
    of the whole fix for a word that is not there."""
    asked = oxford({})

    assert parsers._fetch_oxford_entry("qwertyzzz") == ({}, {})
    assert asked == ["qwertyzzz", "qwertyzzz_1"]


def test_the_same_entry_under_two_names_is_read_once(oxford):
    """`can_2` answers at `can2_1`, and an ordinary word's `_1` redirects back
    to its bare page — so what is de-duplicated is where the request **landed**,
    never what was asked for."""
    asked = oxford({
        "can_1": ("can1", page("modal verb", "to be able to")),
        "can_2": ("can1", page("modal verb", "to be able to")),  # the same page
        "can_3": ("can2_2", page("verb", "to put food in a can")),
    })

    definitions, _ = parsers._fetch_oxford_entry("can")

    assert sorted(definitions) == ["modal verb", "verb"]
    # One slug further than the test above, and that is the point: the cap
    # counts pages **collected**, so a duplicate does not fill a slot and the
    # probe keeps going until a real miss ends it.
    assert asked == ["can", "can_1", "can_2", "can_3", "can_4"]


# --- the bare slug is a minor entry: `do` ----------------------------------

DO = {
    "do": ("do", page_with_links("abbreviation", "ditto",
                                 ["ditto_1", "do1_1", "do1_2", "do1_3",
                                  "do-in", "do-up", "to-do"])),
    "do1_1": ("do1_1", page("verb", "to perform an action")),
    "do1_2": ("do1_2", page("auxiliary verb", "used to form questions")),
    "do1_3": ("do1_3", page("noun", "a party")),
}


def test_a_minor_bare_entry_still_reaches_the_real_ones(oxford):
    """The pattern used to be `{slug}_\\d+`, which matches `run_2` and none of
    `do`'s three, so a lookup of `do` was explained as an abbreviation."""
    oxford(DO)

    definitions, _ = parsers._fetch_oxford_entry("do")

    assert "verb" in definitions
    assert definitions["verb"] == ["to perform an action"]


def test_the_neighbours_are_still_excluded(oxford):
    """`ditto_1`, `do-in`, `do-up` and `to-do` all sit in `do`'s box and none
    of them is the word being looked up. Widening the pattern must not widen
    it to those."""
    asked = oxford(DO)

    parsers._fetch_oxford_entry("do")

    for neighbour in ("ditto_1", "do-in", "do-up", "to-do"):
        assert neighbour not in asked


@pytest.mark.parametrize("href,matches", [
    ("do", True), ("do1_1", True), ("do2", True), ("do_1", True),
    ("ditto_1", False), ("do-in", False), ("to-do", False), ("done", False),
    ("do1_1x", False),
])
def test_which_links_count_as_the_same_word(href, matches):
    pattern = parsers._oxford_entry_href("do")

    assert bool(pattern.search(f"{BASE}/{href}")) is matches


# --- what it costs the words that already worked ---------------------------

def test_an_ordinary_word_is_still_one_request(oxford):
    """The promise that makes this fix free for everything that worked. A
    second request per lookup would be a real cost across a seeded deck."""
    asked = oxford({"resilient": ("resilient",
                                  page("adjective", "able to recover"))})

    definitions, _ = parsers._fetch_oxford_entry("resilient")

    assert list(definitions) == ["adjective"]
    assert asked == ["resilient"]


def test_a_linked_sibling_is_still_followed(oxford):
    """`run` -> `run_2` is the case that worked before any of this, and the
    existing fetch-list test in test_providers.py pins it too."""
    asked = oxford({
        "run": ("run_1", page_with_links("verb", "to move fast",
                                         ["run_2", "run-up", "ladder_1"])),
        "run_2": ("run_2", page("noun", "an act of running")),
    })

    definitions, _ = parsers._fetch_oxford_entry("run")

    assert sorted(definitions) == ["noun", "verb"]
    assert asked == ["run", "run_2"]


def test_the_page_cap_still_holds(oxford):
    """`close` has four entries and the cap is three. Bounding the crawl is
    what keeps a lookup's cost knowable."""
    asked = oxford({f"close_{n}": (f"close{n}", page(f"pos{n}", f"sense {n}"))
                    for n in range(1, 6)})

    definitions, _ = parsers._fetch_oxford_entry("close")

    assert len(definitions) == parsers.OXFORD_MAX_PAGES
    assert len(asked) == parsers.OXFORD_MAX_PAGES + 1, "the bare miss, then the cap"


def test_a_provider_error_keeps_what_was_already_collected(oxford):
    """Unchanged behaviour, restated because the fetch path was rewritten
    around it: a failure part-way leaves the entries already read."""
    def fake_get(url, **kwargs):
        slug = url.rsplit("/", 1)[-1]
        if slug == "can_1":
            return Fake(page("modal verb", "to be able to"), url=f"{BASE}/can1")
        if slug == "can":
            return Fake(status_code=404, url=url)
        raise requests.ConnectionError("dropped")

    import parsers as p
    p.requests.get = fake_get
    try:
        definitions, _ = parsers._fetch_oxford_entry("can")
    finally:
        p.requests.get = requests.get

    assert list(definitions) == ["modal verb"]
