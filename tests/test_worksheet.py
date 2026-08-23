"""A printable gap-fill worksheet from a generated text (kuantorflow#340).

The sheet is a *view* of the passage already held in the session, so the two
things worth pinning hardest are the ones that would make it something else:
that it never calls the model, and that it can never disagree with the reader
page about which words were used.

The model call is not merely stubbed here — it is replaced with something that
raises. A worksheet that generates is a bug with a bill attached, and a stub
that quietly returns a passage would let that bug pass.
"""

import html
import pathlib
import re

import pytest

import conftest
import games


CARDS = [
    {"id": 1, "word": "resign", "pos": "verb", "topic": "Work",
     "explanation_en": "to give up a job or position",
     "examples_en": ["He resigned from the board."]},
    {"id": 2, "word": "jury", "pos": "noun", "topic": "Work",
     "explanation_en": "a group who decide a verdict"},
    {"id": 3, "word": "take for granted", "pos": "phrase", "topic": "Work",
     "explanation_en": "to assume something is true"},
]

PASSAGE = ("The jury met on Monday. He resigned the next morning, and the "
           "committee takes it for granted that a successor will be found.")
WORDS = ["jury", "resign", "take for granted", "castigate"]

WORKSHEET = "/games/read_a_text/worksheet"
PLAY = "/games/read_a_text/play"


@pytest.fixture()
def deck(stub_deck):
    return stub_deck(cards=CARDS)


@pytest.fixture(autouse=True)
def has_key(monkeypatch):
    """The activity is unreachable with no key at all (#237), so every test
    here needs one present. Never used — nothing may call out."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-used")


@pytest.fixture(autouse=True)
def generations(monkeypatch):
    """Records any attempt to generate, and returns the record.

    **Raising is not enough here, and that was proved rather than assumed.**
    `textgen.generate()` catches every exception and reports it as a sentence
    on the page (`# noqa: BLE001 - reported, never raised`), so a stub that
    raised was swallowed and a route calling it still answered 200 — the first
    version of this fixture let the worksheet generate and every test passed.
    Recording the call is the assertion that cannot be swallowed.
    """
    import textgen
    calls = []

    def record(words, instruction, length):                 # pragma: no cover
        calls.append((list(words), instruction, length))
        return {"title": "", "text": "", "words": list(words),
                "segments": [], "title_segments": [], "used": [], "missing": [],
                "error": None}

    def explode(*a, **k):                                   # pragma: no cover
        raise AssertionError("the worksheet reached the network")

    monkeypatch.setattr(textgen, "generate", record)
    monkeypatch.setattr(textgen, "_ask_claude", explode)
    return calls


def _held(client, app_module, title="A quiet week", text=PASSAGE, words=WORDS):
    with client.session_transaction() as s:
        s[app_module.GENERATED_TEXT_KEY] = {
            "title": title, "text": text, "words": list(words),
            "topics": ["Work"], "length": 60, "instruction": "", "error": None,
        }


def _blanks(body):
    """`(number, blank)` for every gap on the sheet, in document order."""
    return re.findall(r'<span class="ws-num">(\d+)</span>([^<]*)</span>', body)


def _key(body):
    return re.findall(r'<li value="(\d+)">([^<]+)</li>', body)


# --- the pure rule ----------------------------------------------------------

def test_blanks_are_numbered_in_document_order():
    segments = [("A ", False), ("jury", True), (" and a ", False),
                ("verdict", True), (".", False)]
    items, answers = games.worksheet_blanks(segments)
    assert [n for _, n in items if n] == [1, 2]
    assert answers == [(1, "jury"), (2, "verdict")]


def test_prose_runs_pass_through_untouched():
    items, _ = games.worksheet_blanks([("kept as it is", False)])
    assert items == [("kept as it is", None)]


def test_start_continues_one_sequence():
    """The title numbers first and the body carries on: a sheet with two
    blanks called 1 has a key that cannot say which is which."""
    _, answers = games.worksheet_blanks([("x", True)], start=3)
    assert answers == [(4, "x")]


def test_the_key_records_what_was_matched_not_the_headword():
    """`resign` matched as *resigned* is answered *resigned*.

    Keying the headword would mark a student wrong for reading correctly, and
    it is the same argument `mask_gap()` makes at the other end of the sheet.
    """
    _, answers = games.worksheet_blanks([("resigned", True)])
    assert answers == [(1, "resigned")]


@pytest.mark.parametrize("hint,expected", [
    (games.HINT_NONE, "______"),
    (games.HINT_FIRST, "r____"),
    (games.HINT_FIRST_LAST, "r____d"),
])
def test_the_hint_changes_the_blank_and_never_the_answer(hint, expected):
    items, answers = games.worksheet_blanks([("resigned", True)], hint)
    assert items[0][0] == expected
    assert answers == [(1, "resigned")]


# --- the sheet --------------------------------------------------------------

def test_a_blank_for_every_answer(client, app_module, deck):
    _held(client, app_module)
    body = client.get(WORKSHEET).get_data(as_text=True)
    blanks, key = _blanks(body), _key(body)
    assert blanks and len(blanks) == len(key)
    assert [n for n, _ in blanks] == [n for n, _ in key]


def test_an_expression_gaps_whole_and_keeps_its_object(client, app_module, deck):
    """"takes it for granted" is one blank, not a blank with a stray word in
    the middle — `mask_gap()` masks what was matched (#334)."""
    _held(client, app_module)
    key = dict(_key(client.get(WORKSHEET).get_data(as_text=True)))
    assert "takes it for granted" in key.values()


def test_a_word_in_the_title_is_gapped_and_numbers_first(client, app_module, deck):
    """`textgen.mark()` counts the title (#315), so leaving it intact would
    print an answer two lines above its own blank."""
    # The body must not *begin* with the title's word, or blank 1 reads the
    # same either way and this test cannot fail. It could not, at first.
    _held(client, app_module, title="The jury decides",
          text="He resigned on Monday, everyone agreed.", words=WORDS)
    body = client.get(WORKSHEET).get_data(as_text=True)
    assert _key(body)[0] == ("1", "jury")
    assert _key(body)[1] == ("2", "resigned")


def test_every_occurrence_becomes_its_own_blank(client, app_module, deck):
    _held(client, app_module, title="One", text="A jury replaced a jury.",
          words=["jury"])
    assert len(_key(client.get(WORKSHEET).get_data(as_text=True))) == 2


def test_words_the_passage_never_used_are_named_not_dropped(client, app_module, deck):
    _held(client, app_module)
    body = client.get(WORKSHEET).get_data(as_text=True)
    assert "Not used in this text" in body and "castigate" in body


# --- what it must never become ---------------------------------------------

def test_the_sheet_never_calls_the_model(client, app_module, deck, generations):
    """The assertion this whole route exists to keep true: a printable page
    that can spend is not a printable page."""
    _held(client, app_module)
    assert client.get(WORKSHEET).status_code == 200
    assert generations == []


def test_the_sheet_refuses_a_post(client, app_module, deck):
    """GET only. A POST route here would be a second way to generate."""
    _held(client, app_module)
    assert client.post(WORKSHEET).status_code == 405


def test_no_held_text_explains_itself_and_generates_nothing(client, deck):
    body = client.get(WORKSHEET).get_data(as_text=True)
    assert "no text to make a worksheet from" in body
    assert not _blanks(body)


def test_it_is_not_a_round(client, deck):
    """Outside `GAME_ROUNDS` on purpose: registering it as one would put a
    worksheet in the picker and on the front-page tile."""
    assert "worksheet" not in app_rounds()


def app_rounds():
    import app
    return set(app.GAME_ROUNDS)


# --- the way in -------------------------------------------------------------

def test_the_link_is_a_button_on_the_reader_page(client, app_module, deck):
    """It has to be *seen*, so it carries the same class the blue submit
    buttons use rather than looking like body text."""
    _held(client, app_module)
    body = client.get(f"{PLAY}?topic=Work&words=60").get_data(as_text=True)
    assert '<a class="button-link" href="/games/read_a_text/worksheet"' in body


def test_the_button_link_shares_the_button_rule_rather_than_copying_it():
    """`a.button-link` sits in the same selector list as `button`, not in a
    second set of declarations that happens to say the same thing today.

    Pinned because copies drift silently. The whole point of the class is that
    the link and the button beside it cannot come apart, and a test that only
    checked the rendered colours would pass right up until one of the two
    copies was edited -- which is the failure it exists to prevent.
    """
    css = (pathlib.Path(conftest.KUANTORFLOW_PATH)
           / "static" / "css" / "style.css").read_text(encoding="utf-8")
    rule = re.search(r"\nbutton,\na\.button-link \{(.*?)\}", css, re.S)
    assert rule, "button and a.button-link are no longer one rule"
    body = rule.group(1)
    for prop in ("background: var(--blue)", "color: #fff", "border-radius"):
        assert prop in body, prop


# --- the way back ------------------------------------------------------------

def test_back_from_the_sheet_returns_to_the_same_text(client, app_module, deck):
    """Following the link back shows the passage again, not the write form.

    The round only renders a held text when the request asks for the topics,
    length and instruction that produced it, so a bare link resolves to the
    whole visible deck at the default length and drops the learner on the
    write form as though their text had gone. Reported from the browser.
    """
    _held(client, app_module)
    sheet = client.get(WORKSHEET).get_data(as_text=True)
    back = html.unescape(re.search(
        r'<a href="([^"]+)">&larr; Back to the text</a>', sheet).group(1))

    page = client.get(back).get_data(as_text=True)
    assert '<div class="panel reader-text">' in page, "landed on the write form"
    assert "/games/read_a_text/worksheet" in page


def test_the_back_link_carries_what_produced_the_text(client, app_module, deck):
    """Topics, length and instruction all travel, because `_held_for()`
    compares all three."""
    with client.session_transaction() as sess:
        sess[app_module.GENERATED_TEXT_KEY] = {
            "title": "T", "text": PASSAGE, "words": list(WORDS),
            "topics": ["Work"], "length": 150,
            "instruction": "a letter of complaint", "error": None}
    sheet = client.get(WORKSHEET).get_data(as_text=True)
    back = html.unescape(re.search(
        r'<a href="([^"]+)">&larr; Back to the text</a>', sheet).group(1))
    assert "topic=Work" in back
    assert "words=150" in back
    assert "about=a+letter+of+complaint" in back


def test_the_back_link_is_white_on_blue(client, app_module, deck):
    """`crumbs` on the wrapper, never on the anchor.

    The class carries the blue background and `.crumbs a` carries the white
    text, so an anchor wearing it directly comes out blue on blue — which is
    exactly how it shipped first time.
    """
    _held(client, app_module)
    sheet = client.get(WORKSHEET).get_data(as_text=True)
    assert '<a class="crumbs"' not in sheet
    assert re.search(r'<p class="crumbs">.*?<a href=', sheet, re.S)


# --- it cannot disagree with the page it was made from ----------------------

def test_the_sheet_and_the_reader_agree_on_which_words_were_used(
        client, app_module, deck):
    """The regression that catches somebody reaching for `games.mark_words()`
    instead of `textgen.mark()`: the title counts towards a word being used,
    and the two functions answer differently when it does.
    """
    _held(client, app_module, title="The jury decides")
    # `words=60` matches what `_held(...)` stored: the round only shows a held
    # text when the request asks for the same topics, length and instruction
    # that produced it, so a bare URL would render the write form instead.
    reader = client.get(f"{PLAY}?topic=Work&words=60").get_data(as_text=True)
    used = re.findall(r'<span class="reader-word-used">(.*?)</span>', reader)

    sheet = client.get(WORKSHEET).get_data(as_text=True)
    missing = re.search(r"Not used in this text:\s*([^.<]+)", sheet)
    unused = [w.strip() for w in missing.group(1).split(",")] if missing else []

    assert sorted(used) == sorted(w for w in WORDS if w not in unused)


# --- the three blank styles -------------------------------------------------

def test_a_fresh_visitor_gets_no_hint(client, app_module, deck):
    """*Fill the gap*'s default, for the same reason: a printed sheet cannot
    be retried, so the plain gap is the one to start from."""
    _held(client, app_module)
    body = client.get(f"{WORKSHEET}?hint=nonsense").get_data(as_text=True)
    assert all(b == "______" for _, b in _blanks(body))


def test_the_chosen_style_is_remembered(client, app_module, deck):
    """Read from the query and remembered, exactly as a round's hint is."""
    _held(client, app_module)
    client.get(f"{WORKSHEET}?hint={games.HINT_FIRST_LAST}")
    body = client.get(WORKSHEET).get_data(as_text=True)
    assert any(b not in ("", "______") for _, b in _blanks(body))


def test_it_does_not_change_the_fill_the_gap_hint(client, app_module, deck):
    """Its own session key, on the precedent #334 set when it gave *Fill the
    gap* a key separate from *Spell it*: choosing a style for a sheet about to
    be printed is not a choice about the next round played on screen."""
    _held(client, app_module)
    client.get(f"{WORKSHEET}?hint={games.HINT_FIRST_LAST}")
    with client.session_transaction() as s:
        assert s.get(games.GAP_HINT_KEY) in (None, games.HINT_NONE)
        assert s.get(games.WORKSHEET_HINT_KEY) == games.HINT_FIRST_LAST
