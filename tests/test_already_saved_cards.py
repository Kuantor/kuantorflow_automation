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
    assert "as a second card" in card, "and says what Add will really do"


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

# --- and what the press turns out to have done -----------------------------

@pytest.fixture()
def duplicate(app_module, monkeypatch):
    """A save that #101 refuses, with control over what it then fills."""
    monkeypatch.setattr(app_module, "save_flashcard",
                        lambda entry, added_by_user_id=None, **kw: None)

    def fills(*fields):
        monkeypatch.setattr(app_module, "fill_missing_fields",
                            lambda entry: list(fields), raising=False)

    return fills


def test_a_duplicate_that_filled_something_says_which_fields(user_client,
                                                             duplicate):
    """The report Anton hit: he pressed Add on a card already in the deck,
    said yes to the confirmation, the stored card gained an explanation and a
    Ukrainian translation -- and the button said "Already in DB", which reads
    as nothing having happened.

    Three FILL lines in cards.log that week were exactly this, and the
    automatic-add path has reported it since #349 ("Completed N of them with
    this lookup"). The review popup was the surface that never did.
    """
    duplicate("explanation_en", "translation_ukr")

    body = user_client.post("/cards/add",
                            data={"word": "castigate"}).get_json()

    assert body["saved"] is False, "still not a save"
    assert body["duplicate"] is True
    assert body["filled"] == ["English explanation", "Ukrainian translation"]


def test_a_duplicate_that_filled_nothing_keeps_the_old_answer(user_client,
                                                              duplicate):
    """The ordinary duplicate answer keeps its existing shape, so the key is
    present only when there is something extra to say -- the rule #186's
    `note` already follows."""
    duplicate()

    body = user_client.post("/cards/add",
                            data={"word": "castigate"}).get_json()

    assert body == {"ok": True, "saved": False, "duplicate": True}


def test_a_real_save_says_nothing_about_filling(user_client, saved):
    """A written card is a written card. `filled` is the answer to a question
    that only arises when #101 refused."""
    body = user_client.post("/cards/add", data={"word": "brandnew"}).get_json()

    assert body == {"ok": True, "saved": True}


def test_every_fillable_column_has_a_name_a_learner_would_recognise(app_module):
    """The map is what stops the tooltip reading `translation_rus`, and a new
    fillable column is exactly when that would happen -- silently, in a
    sentence shown to somebody who just pressed a button."""
    import utils

    missing = [field for field in utils.FILLABLE_FIELDS
               if field not in app_module.FILLED_FIELD_LABELS]

    assert not missing, "no learner-facing name for %s" % missing


def test_the_caption_depends_on_whether_the_press_was_confirmed(review, deck):
    """Three answers, three captions, and the difference is what the press
    actually did (#379).

    A confirmed press really writes a card now, so it comes back
    `saved: true` and the button says "Added" truthfully. The duplicate
    branch is what remains for a press nobody could warn about -- no chip,
    because the database was unreachable when the popup was built, or somebody
    added the word in between -- and there "Added" would be the lie #308 is
    about.

    Measured on the real page: a confirmed press on a marked card posts
    `confirmed_duplicate=1` and reads "Added"; an unconfirmed press posts
    nothing extra, opens no dialog, and reads "Already in DB".
    """
    page = review("castigate")
    handler = page[page.index("function addCard("):page.index("// #357.")]

    captions = re.findall(r'btn\.textContent = "([^"]+)"', handler)

    assert "Added ✓" in captions, "a real save"
    assert "Filled in ✓" in captions, "#349 filled the card instead"
    assert "Already in DB" in captions, (
        "and an unconfirmed press that wrote nothing still says so")


def test_the_tooltip_still_says_no_second_card_was_made(review, deck):
    """The caption is the outcome; the tooltip is the mechanism. Dropping it
    would leave the popup claiming a duplicate row that does not exist, which
    is the objection that made this worth thinking about at all."""
    page = review("castigate")
    handler = page[page.index("function addCard("):page.index("// #357.")]

    assert "No second card was made" in handler
    assert "filled in on the card you already had" in handler


def test_the_answer_itself_still_says_no_card_was_saved(user_client,
                                                        duplicate):
    """The button's word changed; the report did not.

    Anything that reads this route -- a test, a log line, another client --
    still learns that #101 refused, which is what keeps the caption a matter
    of wording rather than a lie the whole app now tells.
    """
    duplicate("translation_ukr")

    body = user_client.post("/cards/add",
                            data={"word": "castigate"}).get_json()

    assert body["saved"] is False
    assert body["duplicate"] is True

# --- and when the answer is yes, a card is really written (#379) -----------

def _cards_log(directory):
    """The lines cards.log holds, in the temp directory `action_logs` made."""
    path = directory / "cards.log"
    return [line for line in path.read_text(encoding="utf-8").splitlines()
            if line] if path.exists() else []


def test_a_confirmed_save_writes_past_the_duplicate_rule(monkeypatch):
    """#101 refuses a second card for one word and part of speech. That is
    still the default; this is the one press allowed past it.

    Answering yes used to do nothing at all: no row, because of #101, and no
    improvement to the card already saved either, because #349's fill only
    touches columns that are **empty**. A card whose translations were already
    there simply absorbed the press.
    """
    import utils
    from conftest import fake_card_db, inserted_card

    cursor, _conn = fake_card_db(monkeypatch, duplicate=(1,),
                                 topic=(3, "vocab"))
    row_id = utils.save_flashcard(
        {"word": "castigate", "pos": "verb", "topic": "vocab"},
        allow_duplicate=True)

    assert row_id == cursor.card_id, "a row was written"
    assert inserted_card(cursor), "and it was an INSERT INTO flashcards"


def test_without_the_flag_the_rule_still_refuses(monkeypatch):
    """The half that must not move. Everything that does not carry a
    learner's answer -- every other save path, and this one by default --
    behaves exactly as it did."""
    import utils
    from conftest import fake_card_db

    cursor, _conn = fake_card_db(monkeypatch, duplicate=(1,),
                                 topic=(3, "vocab"))

    assert utils.save_flashcard(
        {"word": "castigate", "pos": "verb", "topic": "vocab"}) is None
    assert not [q for q, _ in cursor.queries
                if q.startswith("INSERT INTO flashcards")]


def test_the_route_forwards_only_what_the_form_confirmed(user_client, saved):
    """The flag is the learner's answer, carried on the request that answers
    it. A press with no confirmation behind it cannot set it by accident."""
    user_client.post("/cards/add", data={"word": "castigate", "pos": "verb"})
    user_client.post("/cards/add", data={"word": "castigate", "pos": "verb",
                                         "confirmed_duplicate": "1"})

    assert saved.allowed_duplicates == [False, True]


@pytest.mark.parametrize("value,confirmed", [
    ("1", True), ("true", True), ("yes", True),
    ("0", False), ("", False), ("maybe", False),
])
def test_what_counts_as_a_confirmation(user_client, saved, value, confirmed):
    user_client.post("/cards/add", data={"word": "castigate", "pos": "verb",
                                         "confirmed_duplicate": value})

    assert saved.allowed_duplicates == [confirmed]


def test_the_automatic_add_never_forces(user_client, app_module, monkeypatch,
                                        saved):
    """Nobody was asked, so nobody answered. #200's auto-add saves without
    opening the popup at all, which is exactly the pile-up #101 is for."""
    monkeypatch.setattr(app_module, "lookup_word",
                        lambda word, topic=None, **kw: [
                            {"word": word, "pos": "verb", "topic": topic}])
    user_client.post("/settings", json={"cards_automatically": True})
    user_client.post("/", data={"action": "parse_word", "word": "castigate",
                                "topic": "vocab"})

    assert saved.allowed_duplicates == [False]


def test_the_log_says_which_card_it_was_added_beside(user_client, app_module,
                                                     monkeypatch, saved,
                                                     action_logs):
    """A second row for one word and part of speech is otherwise
    indistinguishable, later, from the accident #101 exists to prevent."""
    monkeypatch.setattr(app_module, "find_duplicate",
                        lambda word, pos, exclude_id=None: (671, 7))

    user_client.post("/cards/add", data={"word": "castigate", "pos": "verb",
                                         "confirmed_duplicate": "1"})

    line = _cards_log(action_logs)[-1]

    assert " CREATE " in line
    assert "alongside=671" in line


def test_an_ordinary_create_says_nothing_about_alongside(user_client, saved,
                                                         action_logs):
    """`_write` drops a None field, so the line a normal save writes is the
    line it always wrote."""
    user_client.post("/cards/add", data={"word": "brandnew", "pos": "verb"})

    assert "alongside" not in _cards_log(action_logs)[-1]


def test_the_confirmation_promises_a_second_card(review, deck):
    """The sentence has to match what the answer now does. It used to promise
    the opposite -- "will not create a second card" -- which was true when the
    answer did nothing."""
    deck.exact("castigate")
    card = card_for(review("castigate"), "castigate")

    assert "as a second card" in card
    assert "will not create a second card" not in card


def test_the_popup_sends_the_answer_it_was_given(review, deck):
    """Wiring here; measured in the browser. A confirmed press on a marked
    card posts `confirmed_duplicate=1`, an unconfirmed press posts nothing
    extra and opens no dialog, and Add All's "add them anyway" sends it for
    the marked cards while "add only the new ones" sends it for none.
    """
    page = review("castigate")
    handler = page[page.index("function addCard("):page.index("// #357.")]

    assert 'body.append("confirmed_duplicate", "1")' in handler
    assert "if (anyway)" in handler
    assert "addCard(form, !!form.dataset.already)" in page, (
        "one card: confirmed, and only for a card the popup marked")
    assert "anyway && !!form.dataset.already" in page, (
        "the batch: only the ones the question was about")
