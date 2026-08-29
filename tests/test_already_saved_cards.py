"""Cards the deck already holds, said before Add is pressed (kuantorflow#377).

The review popup used to say nothing until the press, and then said it on the
button — *Already in DB*, with the press spent. A file can carry thirty cards,
so finding out which ones were worth pressing cost thirty presses.

Every proposed card is now checked while the popup is built, in **one** query
for the whole popup, and marked beside the word. Two states, and telling them
apart is the whole point, because #101 deduplicates on **word + part of
speech** and a card parsed from notes often carries no part of speech at all:

* `card` — that word *and* that part of speech is saved. Add writes nothing
  (though `fill_missing_fields()` still fills what the stored card is missing,
  #349), and the sentence says so rather than implying a second copy;
* `word` — the word is saved under some other part of speech. This card **will**
  be added, beside the ones already there. A chip reading "already in DB" over
  it would be the same lie in the other direction.

Pressing Add on a marked card asks first — #145's question, moved to the moment
the press happens — and the answer decides whether the existing save runs. That
last part is browser behaviour and was measured there; the docstrings say which
claims are measurements rather than assertions.
"""

import io
import re

import pytest


MHT_TEMPLATE = """From: <saved>
MIME-Version: 1.0
Content-Type: multipart/related; boundary="----=_B"

------=_B
Content-Type: text/html; charset="utf-8"
Content-Transfer-Encoding: 8bit

<html><body>%s</body></html>
------=_B--
"""


def notes(*words):
    body = "".join("<p>%s - pereklad</p>" % word for word in words)
    return MHT_TEMPLATE.replace("%s", body, 1).encode("utf-8")


@pytest.fixture()
def deck(app_module, monkeypatch):
    """Say what the database holds for each card the popup is about to show.

    Records the calls too, because "one query for the popup" is a promise
    worth keeping: the alternative is a query per card, and a parsed file can
    carry thirty.
    """
    class Deck:
        def __init__(self):
            self.calls = []
            self.answers = {}

        def exact(self, word, owner=7):
            self.answers[word] = {"exact": (1, owner), "others": []}

        def other_pos(self, word, *poses):
            self.answers[word] = {"exact": None, "others": list(poses)}

        def __call__(self, pairs):
            self.calls.append(list(pairs))
            return [self.answers.get(word, {"exact": None, "others": []})
                    for word, _pos in pairs]

    state = Deck()
    monkeypatch.setattr(app_module, "find_saved_words", state, raising=False)
    return state


@pytest.fixture()
def review(user_client):
    """Open the file-review popup over a set of words."""
    def open_popup(*words):
        return user_client.post(
            "/", data={"action": "upload_notes", "topic": "vocab",
                       "notes_file": (io.BytesIO(notes(*words)), "notes.mht")},
            content_type="multipart/form-data", follow_redirects=True
        ).get_data(as_text=True)
    return open_popup


def card_for(html, word):
    """One proposal card's markup, from its form tag to the end of the form."""
    start = html.index('data-word="%s"' % word)
    start = html.rindex("<form", 0, start)
    return html[start:html.index("</form>", start)]


# --- what the card says before anything is pressed -------------------------

def test_a_saved_word_and_part_of_speech_is_marked(review, deck):
    deck.exact("resilient")
    card = card_for(review("resilient"), "resilient")

    assert 'data-already="card"' in card
    assert "Already in DB" in card
    assert "will not create a second card" in card, (
        "and says what Add will really do")


def test_a_word_saved_under_another_part_of_speech_is_marked_differently(
        review, deck):
    """It will be added, so it must not wear the label of a card that will
    not be. The parts of speech are named because that is the fact #145's
    warning cannot know yet — it fires before the lookup."""
    deck.other_pos("wind", "noun", "verb")
    card = card_for(review("wind"), "wind")

    assert 'data-already="word"' in card
    assert "Word already saved" in card
    assert "saved as noun, verb" in card
    assert "added as a separate card" in card


def test_a_new_word_is_not_marked(review, deck):
    card = card_for(review("qwertyzzz"), "qwertyzzz")

    assert "data-already" not in card
    assert "proposal-saved" not in card


def test_a_pos_less_card_names_the_gap_rather_than_leaving_a_blank(review,
                                                                   deck):
    """A `.mht` from plain text carries no part of speech at all, which is
    most of why the two states exist. The sentence has to read as English
    with the part of speech missing on either side."""
    deck.other_pos("wind", "noun")
    card = card_for(review("wind"), "wind")

    assert "This card has no part of speech" in card


# --- one query, and only when there is something to ask about --------------

def test_the_whole_popup_is_one_query(review, deck):
    deck.exact("resilient")
    review("resilient", "wind", "qwertyzzz")

    assert len(deck.calls) == 1, "one call for the popup, not one per card"
    assert [word for word, _pos in deck.calls[0]] == [
        "resilient", "wind", "qwertyzzz"]


def test_the_part_of_speech_is_asked_about_too(review, deck):
    """The pair, not the word: #101's rule is word **and** part of speech, and
    a chip that answered a different question would mispredict every card
    whose word is saved under another one."""
    review("wind")

    assert deck.calls[0][0][0] == "wind"
    assert len(deck.calls[0][0]) == 2


def test_a_dead_database_costs_the_chips_and_nothing_else(review, deck,
                                                          app_module,
                                                          monkeypatch):
    """The rule `_word_already_saved()` set for #145: unknown warns about
    nothing. The cards behind this popup cost a parsed file — losing them to a
    failed nicety would throw away the expensive half of the request for the
    cheap one.
    """
    def boom(pairs):
        raise RuntimeError("MySQL has gone away")

    monkeypatch.setattr(app_module, "find_saved_words", boom, raising=False)
    html = review("resilient", "wind")

    assert html.count('class="proposal-card"') == 2, "the popup still opens"
    assert "data-already" not in html
    assert "proposal-saved" not in html


# --- #186: the duplicate you cannot see ------------------------------------

def test_a_hidden_duplicate_says_where_it_is(review, deck, user_client):
    """Duplicate detection is global (#101) while #127 hides other people's
    cards, so "already in DB" can be said about a card the visitor cannot
    find. #186 wrote that sentence for the message after a skipped save; the
    chip needs it for the same reason, one moment earlier.
    """
    user_client.post("/settings", json={"individual_cards": True})
    deck.exact("resilient", owner=999)
    card = card_for(review("resilient"), "resilient")

    assert "hidden from you by your" in card


def test_your_own_duplicate_does_not(review, deck, user_client):
    """The plain wording is correct whenever the blocking card is one they can
    actually find — #186's own rule, and the reason the note is an addition
    rather than the message."""
    user_client.post("/settings", json={"individual_cards": True})
    deck.exact("resilient", owner=7)   # TEST_USER_ID
    card = card_for(review("resilient"), "resilient")

    assert "hidden from you by your" not in card


def test_the_note_is_written_once(app_module):
    """It is said in two places now - after a skipped save, and on the chip -
    so it is a constant rather than a literal in each. Read out of the source,
    because "there is only one copy" is a claim about the file: a second
    literal would pass every behavioural assertion right up until somebody
    reworded one of them.
    """
    import inspect

    source = inspect.getsource(app_module)

    assert "individual cards" in app_module.HIDDEN_DUPLICATE_NOTE
    assert source.count("hidden from you by your") == 1


# --- which popup asks, and which only marks --------------------------------

@pytest.fixture()
def look_up(user_client, app_module, monkeypatch):
    """The *word-lookup* popup, which is the same popup through another door.

    Callable rather than the page itself, so a test can say what the deck
    holds before the request runs: a fixture that fetched at setup time would
    have asked the database before the test had answered.
    """
    monkeypatch.setattr(app_module, "lookup_word",
                        lambda word, topic=None, **kw: [
                            {"word": word, "pos": "noun", "topic": topic,
                             "explanation_en": "a definition"}])

    def open_popup(word):
        return user_client.post("/", data={"action": "parse_word",
                                           "word": word, "topic": "T"}
                                ).get_data(as_text=True)
    return open_popup


@pytest.fixture()
def word_lookup(look_up):
    return look_up("resilient")


def test_the_file_review_carries_the_confirmation(review, deck):
    html = review("resilient")

    assert 'id="duplicate-confirm-popup"' in html
    for control in ("dup-confirm-question", "dup-confirm-list",
                    "dup-confirm-add", "dup-confirm-skip", "dup-confirm-close"):
        assert 'id="%s"' % control in html, control


def test_the_word_lookup_popup_does_not(word_lookup):
    """#145 asked this question one step earlier — "you already have card(s)
    for X, look it up anyway?" — and asking again on Add would be the second
    dialog about one word.

    The script resolves "add" when the dialog is absent, so the popup without
    it simply never asks; that path was exercised in a browser.
    """
    assert 'id="duplicate-confirm-popup"' not in word_lookup


def test_the_chips_are_in_both(look_up, deck):
    """They say *which part of speech* is the duplicate, which is precisely
    what #145's warning cannot know: it fires before the lookup that decides
    the parts of speech. So the popup #145 already guards still earns a chip.
    It just does not ask a second time."""
    deck.exact("resilient")
    html = look_up("resilient")

    assert 'data-already="card"' in html
    assert "Already in DB" in html
    assert 'id="duplicate-confirm-popup"' not in html, "marked, not asked"


# --- the wiring the script reads -------------------------------------------

def test_the_form_carries_the_sentence_the_dialog_asks(review, deck):
    """Built in app.py and read by both the chip's tooltip and the question,
    so the two cannot drift into saying different things about one card."""
    deck.exact("resilient")
    card = card_for(review("resilient"), "resilient")

    detail = re.search(r'data-already-detail="([^"]+)"', card)
    title = re.search(r'class="proposal-saved[^"]*"\s*\n?\s*title="([^"]+)"',
                      card)

    assert detail and title, "both the form and the chip carry it"
    assert detail.group(1) == title.group(1)


def test_every_card_carries_its_word_for_the_batch_question(review, deck):
    """Add All lists the words it found, and reads them off the forms."""
    deck.exact("resilient")
    html = review("resilient", "wind")

    assert 'data-word="resilient"' in html
    assert 'data-word="wind"' in html


def test_the_confirmation_is_painted_above_the_popup_it_opens_over(client):
    """#372's lesson, asserted rather than rediscovered: this dialog opens on
    top of the review popup, and every dialog is a `.modal-overlay` at
    `z-index: 100`. Sharing that layer leaves the stack to document order and
    hangs the question where nobody can answer it.

    Measured with `elementFromPoint` on the real page: with the dialog open,
    the topmost element at each of its three controls is that control, and the
    Add button of the card behind is covered by the dialog's own box.
    """
    css = client.get("/static/css/style.css").get_data(as_text=True)
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)

    def layer(selector):
        for match in re.finditer(r"([^{}@]+?)\{([^{}]*?)\}", stripped, re.S):
            if selector in [n.strip() for n in match.group(1).split(",")]:
                found = re.search(r"z-index:\s*(\d+)", match.group(2))
                if found:
                    return int(found.group(1))
        return None

    assert layer("#duplicate-confirm-popup") > layer(".modal-overlay")
    assert layer("#duplicate-confirm-popup") < (layer("#mykola-panel") or 200), (
        "#296 keeps the chat above every dialog")

# --- the classifier the chips are only as good as --------------------------

class FakeDeckCursor:
    """The `flashcards` rows a canned deck would return, and a record of how
    many statements it took to get them."""

    def __init__(self, rows, log):
        self.rows = rows
        self.log = log

    def execute(self, sql, params=()):
        self.log.append((sql, params))
        wanted = {str(w).lower() for w in params}
        self.answer = [row for row in self.rows if row[0].lower() in wanted]

    def fetchall(self):
        return self.answer

    def close(self):
        pass


@pytest.fixture()
def stored(monkeypatch):
    """A deck, in the shape `find_saved_words()` reads it out of MySQL."""
    import utils

    log = []

    def install(rows):
        class FakeConn:
            def cursor(self):
                return FakeDeckCursor(rows, log)

            def close(self):
                pass

        monkeypatch.setattr(utils, "get_db_connection", lambda: FakeConn())
        return log

    return install


def test_a_pos_less_card_is_a_duplicate_of_a_pos_less_card(stored):
    """`pos <=> %s` is NULL-safe, which is what lets `.mht` imports be
    deduplicated at all - and a UNIQUE index could not do it, since MySQL
    treats NULLs in a unique key as distinct."""
    import utils

    stored([("baffled", None, 1, 7)])

    state = utils.find_saved_words([("baffled", None)])[0]

    assert state["exact"] == (1, 7)
    assert state["others"] == []


def test_a_pos_less_card_is_not_a_duplicate_of_a_noun(stored):
    """The case the two chips exist for: this card *will* be saved, beside the
    noun already there."""
    import utils

    stored([("wind", "noun", 1, 7), ("wind", "verb", 2, 7)])

    state = utils.find_saved_words([("wind", None)])[0]

    assert state["exact"] is None
    assert state["others"] == ["noun", "verb"]


def test_the_part_of_speech_is_matched_case_insensitively(stored):
    """Same as the column's collation, so the chip predicts what the save will
    really do rather than a stricter rule of its own."""
    import utils

    stored([("record", "Noun", 1, 7)])

    state = utils.find_saved_words([("record", "noun")])[0]

    assert state["exact"] == (1, 7)
    assert state["others"] == []


def test_the_matching_entry_is_not_also_listed_as_another(stored):
    import utils

    stored([("record", "noun", 1, 7), ("record", "verb", 2, 7)])

    state = utils.find_saved_words([("record", "noun")])[0]

    assert state["exact"] == (1, 7)
    assert state["others"] == ["verb"]


def test_an_unknown_word_holds_nothing(stored):
    import utils

    stored([("record", "noun", 1, 7)])

    assert utils.find_saved_words([("qwertyzzz", "noun")])[0] == {
        "exact": None, "others": []}


def test_thirty_cards_are_one_statement(stored):
    """The promise that makes this affordable at page-build time. One query
    per card would put thirty round trips in front of a popup that already
    waited for a file to be parsed."""
    import utils

    log = stored([("word%d" % n, None, n, 7) for n in range(30)])
    pairs = [("word%d" % n, None) for n in range(30)]

    states = utils.find_saved_words(pairs)

    assert len(states) == 30
    assert all(state["exact"] for state in states)
    assert len(log) == 1


def test_no_words_is_no_query_at_all(stored):
    """An empty popup cannot happen today, but a query built from an empty
    `IN ()` is a syntax error rather than an empty answer."""
    import utils

    log = stored([])

    assert utils.find_saved_words([]) == []
    assert log == []
