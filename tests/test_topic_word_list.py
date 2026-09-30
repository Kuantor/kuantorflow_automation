"""A topic's word list, printed or downloaded (kuantorflow#496).

Two routes beside the topic page: `/flashcards/<topic>/word-list`, a
standalone page to print (or save as a PDF from the print dialog), and
`…/word-list.csv`, a file to keep.

What is worth pinning:

* **they read exactly what the topic page reads** -- the same resolution (a
  topic this visitor may not see is a 404) and the same card read with the same
  arguments, so a download can never hold a card the page would not show;
* **the file opens right on a double-click**: UTF-8 *with* a byte-order mark,
  or Excel on Windows turns every Cyrillic letter into mojibake;
* **learners' text cannot become a live formula** in a teacher's spreadsheet;
* **the printout follows the hidden languages, the file keeps everything**;
* **Wiktionary's text carries its credit in both** (#390) -- the condition of
  copying it;
* an `EXPORT` line in `cards.log`.
"""

import csv
import io

import pytest

TOPIC = "City life and housing"
PAGE = "/flashcards/City life and housing"
PRINT = PAGE + "/word-list"
CSV = PAGE + "/word-list.csv"

CARDS = [
    {"id": 1, "word": "lease", "pos": "noun", "topic": TOPIC,
     "explanation_en": "a contract to rent a property",
     "translation_ukr": "оренда", "translation_rus": "аренда",
     "examples_en": ["They signed a two-year lease.", "The lease ends in May."],
     "explanation_source": "wiktionary", "examples_source": "wiktionary"},
    {"id": 2, "word": "tenant", "pos": "noun", "topic": TOPIC,
     "explanation_en": "a person who rents a flat",
     "translation_ukr": "орендар", "translation_rus": "арендатор",
     "examples_en": ["The tenant paid on time."],
     "explanation_source": None, "examples_source": None},
]


@pytest.fixture()
def visible_topic(app_module, monkeypatch):
    """The topic resolves: public, id 11."""
    monkeypatch.setattr(
        "utils.resolve_topic",
        lambda name, topic_id=None, **kw: {
            "id": 11, "name": TOPIC, "is_public": True,
            "created_by_user_id": None, "creator": None},
        raising=False)


@pytest.fixture()
def hidden_topic(app_module, monkeypatch):
    """A topic this visitor may not see: the resolver finds nothing (#382)."""
    monkeypatch.setattr("utils.resolve_topic", lambda *a, **kw: None,
                        raising=False)


def _rows(resp):
    text = resp.get_data().decode("utf-8")
    assert text.startswith("﻿"), "no byte-order mark: Excel shows mojibake"
    return list(csv.reader(io.StringIO(text[1:])))


# --- the file ------------------------------------------------------------------

def test_the_csv_opens_right_in_excel(client, stub_deck, visible_topic):
    stub_deck(cards=CARDS)
    resp = client.get(CSV)
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    rows = _rows(resp)
    assert rows[0] == ["word", "pos", "explanation_en", "translation_ukr",
                       "translation_rus", "examples_en", "explanation_source",
                       "examples_source"]
    assert [r[0] for r in rows[1:]] == ["lease", "tenant"], "one row per card"
    assert rows[1][3] == "оренда" and rows[1][4] == "аренда"
    assert rows[1][5] == "They signed a two-year lease.\nThe lease ends in May.", \
        "every example, one per line"


def test_the_file_is_named_for_the_topic_and_date(client, stub_deck, visible_topic):
    import datetime
    stub_deck(cards=CARDS)
    disposition = client.get(CSV).headers["Content-Disposition"]
    assert disposition.startswith("attachment")
    assert f"KuantorFlow - {TOPIC} - {datetime.date.today():%Y-%m-%d}.csv" in disposition


def test_a_filename_loses_what_windows_refuses(app_module):
    import cards
    name = cards._word_list_filename('Law: "rights" / wrongs?', "csv")
    assert not set('\\/:*?"<>|') & set(name.split(" - ")[1]), name


@pytest.mark.parametrize("dangerous", ["=HYPERLINK(\"http://x\",\"x\")",
                                        "+1+1", "-1+1", "@SUM(A1)"])
def test_a_cell_is_never_a_live_formula(client, stub_deck, visible_topic,
                                        dangerous):
    """Card text is learners' writing and readable by everybody, so it must
    reach a teacher's spreadsheet as text."""
    stub_deck(cards=[dict(CARDS[1], explanation_en=dangerous)])
    (row,) = _rows(client.get(CSV))[1:]
    assert row[2] == "'" + dangerous


def test_the_file_keeps_hidden_languages(user_client, stub_deck, visible_topic):
    """A file is for keeping; a column is easy to delete and impossible to
    get back once it was never written."""
    stub_deck(cards=CARDS)
    user_client.post("/settings", json={"show_russian": False})
    row = _rows(user_client.get(CSV))[1]
    assert row[4] == "аренда"


def test_the_file_carries_the_wiktionary_credit(client, stub_deck, visible_topic):
    stub_deck(cards=CARDS)
    rows = _rows(client.get(CSV))
    assert rows[1][6:] == ["wiktionary", "wiktionary"]
    assert rows[2][6:] == ["", ""]


# --- the printout --------------------------------------------------------------

def test_the_printout_lists_the_words(client, stub_deck, visible_topic):
    stub_deck(cards=CARDS)
    body = client.get(PRINT).get_data(as_text=True)
    for text in ("lease", "a contract to rent a property", "оренда", "tenant"):
        assert text in body
    assert "window.print()" in body
    assert 'class="site-header' not in body and "mykola-panel" not in body, \
        "a standalone page: the site's chrome must not be on the sheet"


def test_the_printout_follows_hidden_languages(user_client, stub_deck,
                                               visible_topic):
    stub_deck(cards=CARDS)
    user_client.post("/settings", json={"show_russian": False})
    body = user_client.get(PRINT).get_data(as_text=True)
    assert "оренда" in body
    assert "аренда" not in body and "<th>Russian</th>" not in body


def test_examples_are_off_until_asked_and_then_one(client, stub_deck,
                                                   visible_topic):
    stub_deck(cards=CARDS)
    assert "two-year lease" not in client.get(PRINT).get_data(as_text=True)
    body = client.get(PRINT + "?examples=1").get_data(as_text=True)
    assert "They signed a two-year lease." in body
    assert "The lease ends in May." not in body, "one example per word"


def test_the_printout_credits_wiktionary(client, stub_deck, visible_topic):
    stub_deck(cards=CARDS)
    body = client.get(PRINT).get_data(as_text=True)
    assert "&dagger;" in body and "From Wiktionary" in body
    assert "CC BY-SA" in body


def test_no_credit_where_nothing_is_wiktionarys(client, stub_deck, visible_topic):
    stub_deck(cards=[CARDS[1]])
    body = client.get(PRINT).get_data(as_text=True)
    assert "From Wiktionary" not in body


# --- the same read as the page ------------------------------------------------

@pytest.mark.parametrize("url", [PRINT, CSV])
def test_a_topic_you_may_not_see_is_a_404(user_client, hidden_topic, url):
    assert user_client.get(url).status_code == 404


def test_the_exports_read_what_the_page_reads(user_client, app_module,
                                              monkeypatch, visible_topic):
    """The same card read, asked the same way -- viewer, admin and #127's
    owner filter -- so a download can never hold a card the page hides."""
    asked = []

    def record(topic, owner_id=None, **kw):
        asked.append((topic, owner_id, tuple(sorted(kw.items()))))
        return [dict(c) for c in CARDS]

    monkeypatch.setattr("utils.get_flashcards_by_topic", record)
    for url in (PAGE, PRINT, CSV):
        assert user_client.get(url).status_code == 200, url
    assert len(asked) == 3 and asked[0] == asked[1] == asked[2], asked


def test_anonymous_visitors_can_take_a_public_topic(client, stub_deck,
                                                    visible_topic):
    """Reading is open to them already (#125), and a teacher trying the site
    without an account is exactly who this is for."""
    stub_deck(cards=CARDS)
    assert client.get(PRINT).status_code == 200
    assert client.get(CSV).status_code == 200


# --- the topic page offers them -------------------------------------------------

def test_the_topic_page_links_both(client, stub_deck, visible_topic):
    stub_deck(cards=CARDS)
    body = client.get(PAGE).get_data(as_text=True)
    assert "Print word list" in body and "Download (.csv)" in body
    assert "/word-list?t=11" in body and "/word-list.csv?t=11" in body, \
        "the topic id travels, so a shared name stays this topic"


def test_an_empty_topic_offers_nothing_to_take(client, stub_deck, visible_topic):
    stub_deck(cards=[])
    body = client.get(PAGE).get_data(as_text=True)
    assert "Download (.csv)" not in body


# --- logged ----------------------------------------------------------------------

def test_every_export_is_logged(client, stub_deck, visible_topic, action_logs):
    stub_deck(cards=CARDS)
    client.get(CSV)
    client.get(PRINT)
    lines = (action_logs / "cards.log").read_text(encoding="utf-8").splitlines()
    exports = [line for line in lines if " EXPORT " in f" {line} "]
    assert len(exports) == 2, lines
    assert "cards=2" in exports[0] and "format=csv" in exports[0]
    assert "format=print" in exports[1]


def test_a_cyrillic_topic_name_survives_the_download(client, stub_deck,
                                                     monkeypatch):
    """Learners name topics in Ukrainian too. A plain `filename=` header
    cannot carry that, so the name goes as RFC 5987's `filename*`."""
    from urllib.parse import quote
    monkeypatch.setattr(
        "utils.resolve_topic",
        lambda name, topic_id=None, **kw: {"id": 5, "name": "Житло",
                                          "is_public": True,
                                          "created_by_user_id": None},
        raising=False)
    stub_deck(cards=CARDS)
    resp = client.get("/flashcards/Житло/word-list.csv")
    assert resp.status_code == 200
    assert "filename*=UTF-8''" + quote("KuantorFlow - Житло - ") in \
        resp.headers["Content-Disposition"]
    assert resp.headers["Content-Type"] == "text/csv; charset=utf-8", \
        "one charset, not two"
