"""Editing the word in the review popup (kuantorflow#380).

Every field on a proposed card could be corrected before it was saved except
the one that decides everything else about it. A word parsed out of a file is
whatever the file said: the deck holds a card saved as `dist'inct`, stress mark
and all, and nothing about it works — Oxford has no such headword, the games'
matcher (`games.word_pattern()`) cannot find it in any English text, the speaker
pronounces the apostrophe, and *Look up & update*, the one button that could
have repaired the card, asks the providers for `dist'inct` and comes back empty.

So the word keeps its heading and gains a pencil, and the pencil opens a popup
with one box. Two halves are testable here — the endpoint the rename asks, and
the markup the rename needs — and the rename itself is browser behaviour, which
was measured on the real page and is recorded in the docstrings.

**The mark is the interesting part.** #377 marks each card on the server, for the
word the *parser* produced. Rename it and that answer is about a different word:
a card renamed onto a word the deck already holds would show nothing, ask
nothing, and be refused in silence by #101 — the exact "the press did nothing"
that #377 and #379 were both filed to end. So the card asks again.
"""

import io

import pytest


MHT = """From: <saved>
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
    return (MHT % body).encode("utf-8")


@pytest.fixture()
def review(user_client):
    def open_popup(*words):
        return user_client.post(
            "/", data={"action": "upload_notes", "topic": "vocab",
                       "notes_file": (io.BytesIO(notes(*words)), "notes.mht")},
            content_type="multipart/form-data", follow_redirects=True
        ).get_data(as_text=True)
    return open_popup


@pytest.fixture()
def word_lookup(user_client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "lookup_word",
                        lambda word, topic=None, **kw: [
                            {"word": word, "pos": "noun", "topic": topic}])
    return user_client.post("/", data={"action": "parse_word", "word": "x",
                                       "topic": "T"}).get_data(as_text=True)


def card_for(html, word):
    start = html.index('data-word="%s"' % word)
    start = html.rindex("<form", 0, start)
    return html[start:html.index("</form>", start)]


# --- the pencil, and the popup it opens ------------------------------------

def test_every_parsed_card_has_a_pencil(review):
    html = review("resilient", "scholar")

    assert html.count('class="word-edit"') == 2


def test_the_word_lookup_popup_has_none(word_lookup):
    """A word typed into the lookup panel is the learner's own and can be
    typed again. A word parsed out of a file is whatever the file said, which
    is the case the pencil exists for — the same scoping *Look up & update*
    (#372) and #377's confirmation already use."""
    assert 'class="word-edit"' not in word_lookup
    assert 'id="word-edit-popup"' not in word_lookup


def test_the_pencil_cannot_submit_the_card(review):
    """The card **is a form** and its submit is *Add*. The speaker beside it
    says so twice in a comment, having been the control that found it."""
    card = card_for(review("resilient"), "resilient")
    pencil = card[card.index('class="word-edit"') - 200:
                  card.index('class="word-edit"') + 40]

    assert 'type="button"' in pencil


def test_the_popup_has_the_controls_the_script_reads(review):
    html = review("resilient")

    assert 'id="word-edit-popup"' in html
    for control in ("word-edit-input", "word-edit-save", "word-edit-cancel",
                    "word-edit-close", "word-edit-error"):
        assert 'id="%s"' % control in html, control


def test_it_is_painted_above_the_popup_it_opens_over(client):
    """#372's lesson, and #375's: this opens on top of the review popup, and
    every dialog is a `.modal-overlay` at `z-index: 100`. Measured with
    `elementFromPoint` on the real page: with the editor open, the topmost
    element at the text box is the text box.
    """
    import re

    css = client.get("/static/css/style.css").get_data(as_text=True)
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)

    def layer(selector):
        for match in re.finditer(r"([^{}@]+?)\{([^{}]*?)\}", stripped, re.S):
            if selector in [n.strip() for n in match.group(1).split(",")]:
                found = re.search(r"z-index:\s*(\d+)", match.group(2))
                if found:
                    return int(found.group(1))
        return None

    assert layer("#word-edit-popup") > layer(".modal-overlay")


# --- the markup a rename writes into ---------------------------------------

def test_the_word_is_wrapped_so_a_rename_has_one_place_to_write(review):
    """It was a bare text node between the controls. Renaming meant finding it
    among them, which is the kind of thing that works until somebody adds a
    second control to the row — which #377 had just done."""
    card = card_for(review("resilient"), "resilient")

    assert '<span class="word-text">resilient</span>' in card


def test_the_mark_has_a_container_even_when_there_is_no_mark(review, deck):
    """A chip that only exists when the server drew one has nowhere to appear
    after a rename. Empty, it must take no room."""
    card = card_for(review("resilient"), "resilient")

    assert 'class="proposal-mark"' in card
    assert "proposal-saved" not in card, "and nothing in it"


def test_an_empty_container_is_not_drawn(client):
    css = client.get("/static/css/style.css").get_data(as_text=True)

    assert ".proposal-mark:empty" in css


def test_the_script_moves_the_word_everywhere_it_lives(review):
    """Five copies and a question. Measured on the real page, renaming
    `zzzznotaword` to `distinct`: heading, hidden input, `data-word`,
    `data-say` and the pencil's own label all followed, and the chip appeared
    because `distinct` really is in that deck. Renaming `castigate` (which is)
    to `qwertyzzz123` (which is not) took the chip away again.
    """
    page = review("resilient")
    rename = page[page.index("function renameCard("):
                  page.index("function editWord(")]

    assert '.word-text").textContent = word' in rename, "the heading"
    assert "form.elements.word.value = word" in rename, "what gets saved"
    assert "form.dataset.word = word" in rename, "Add All's list (#377)"
    assert '"data-say", word' in rename, "what the speaker says"
    assert "saved.json" in rename, "and the mark is asked for again"


def test_the_lookup_reads_the_field_the_rename_writes(client):
    """Why *Look up & update* needs no change of its own: it asks for
    `form.elements.word.value`, which is the input the rename sets. Measured:
    after correcting a word, the lookup asks the providers for the corrected
    one."""
    script = client.get("/static/js/lookup_update.js").get_data(as_text=True)

    assert "form.elements.word.value" in script


# --- /saved.json: the question a renamed card asks -------------------------

@pytest.fixture()
def deck(app_module, monkeypatch):
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


def test_a_renamed_word_that_is_saved_gets_the_mark(user_client, deck):
    deck.exact("distinct")

    body = user_client.post("/saved.json",
                            json={"word": "distinct", "pos": ""}).get_json()

    assert body["known"] is True
    assert body["mark"]["already"] == "card"
    assert body["mark"]["already_label"] == "Already in DB"
    assert "as a second card" in body["mark"]["already_detail"]


def test_a_renamed_word_that_is_not_saved_gets_none(user_client, deck):
    body = user_client.post("/saved.json",
                            json={"word": "qwertyzzz", "pos": ""}).get_json()

    assert body["known"] is True
    assert body["mark"] == {}, "so the card takes its chip off"


def test_the_part_of_speech_is_part_of_the_question(user_client, deck):
    """#101's rule is word **and** part of speech, and the card keeps its own
    across a rename."""
    deck.other_pos("wind", "noun")

    body = user_client.post("/saved.json",
                            json={"word": "wind", "pos": "verb"}).get_json()

    assert deck.calls[-1] == [("wind", "verb")]
    assert body["mark"]["already"] == "word"


def test_the_sentence_is_the_one_the_popup_would_have_drawn(user_client, deck):
    """The chip, the confirmation and this endpoint all say one sentence,
    built in one place (`_saved_mark`). Two copies would drift, and the
    confirmation is what #379 made worth reading."""
    import app as app_module

    deck.exact("distinct")
    from_endpoint = user_client.post(
        "/saved.json", json={"word": "distinct"}).get_json()["mark"]
    rendered = app_module._saved_mark(
        "distinct", "", {"exact": (1, 7), "others": []}, False, 7)

    assert from_endpoint == rendered


def test_a_word_is_required(user_client, deck):
    r = user_client.post("/saved.json", json={"word": "   "})

    assert r.status_code == 400
    assert r.get_json()["ok"] is False


def test_a_dead_database_answers_unknown_rather_than_failing(user_client,
                                                             app_module,
                                                             monkeypatch):
    """The card then wears nothing, rather than a mark about a word it no
    longer holds. Same answer `_mark_already_saved()` gives, and #145's before
    it: an unreachable database costs the nicety and nothing else."""
    def boom(pairs):
        raise RuntimeError("MySQL has gone away")

    monkeypatch.setattr(app_module, "find_saved_words", boom, raising=False)

    body = user_client.post("/saved.json", json={"word": "distinct"}).get_json()

    assert body["ok"] is True
    assert body["known"] is False
    assert body["mark"] == {}


def test_it_asks_no_permission_the_popup_does_not_have(client, deck):
    """A read: one query, no provider call, nothing written. `/lookup.json`
    wants an account because it spends money (#125); this cannot, so an
    anonymous visitor looking at the same popup gets the same answer.
    """
    deck.exact("distinct")

    r = client.post("/saved.json", json={"word": "distinct"})

    assert r.status_code == 200
    assert r.get_json()["mark"]["already"] == "card"


def test_it_writes_nothing(user_client, deck, saved):
    user_client.post("/saved.json", json={"word": "distinct"})

    assert saved == []

def test_the_buttons_are_not_glued_to_the_text_box(client):
    """Reported after the first pass: the action row sat flat against the
    input.

    `.modal-actions` carries no spacing of its own -- it is normally preceded
    by a paragraph or a list with a bottom margin of its own, which is why
    #372 had to give the part-of-speech chips theirs -- and a bare `<input>`
    carries none either, so the two met at 0px.

    Both numbers are read from the stylesheet rather than one of them written
    here: what matters is that the gap is the rhythm this dialog already uses,
    so growing `.modal-dialog p`'s margin without growing this one is caught.
    Measured after: 17px above the buttons, and 6px / 18px around the error
    line when it shows.
    """
    import re

    css = client.get("/static/css/style.css").get_data(as_text=True)
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)

    def rule(selector):
        for match in re.finditer(r"([^{}@]+?)\{([^{}]*?)\}", stripped, re.S):
            if selector in [n.strip() for n in match.group(1).split(",")]:
                return " ".join(match.group(2).split())
        return ""

    gap = re.search(r"margin-top: ([\d.]+)rem",
                    rule("#word-edit-popup .modal-actions"))
    rhythm = re.search(r"margin: 0 0 ([\d.]+)rem",
                       rule(".modal-dialog p"))

    assert gap, "the action row still has no room above it"
    assert rhythm, "the dialog's own paragraph rhythm is not declared"
    assert float(gap.group(1)) >= float(rhythm.group(1)), (
        "%srem above the buttons is tighter than the %srem this dialog uses "
        "between everything else" % (gap.group(1), rhythm.group(1)))

def test_enter_saves_the_word(review):
    """The other half of the Escape that already cancels, and what a one-field
    dialog is for.

    What matters is that the key runs **the same** `commit()` the button runs:
    a second copy of the save would be a second place for the empty-word
    refusal to be forgotten, which is the one rule this dialog has.

    Measured on the real page by dispatching a keydown at the focused box,
    because this browser's `key` action does not reach the page at all --
    neither Enter nor an ordinary letter produced a keydown, while `type` did.
    With a changed word: the popup closed and all five copies followed. With
    an empty box: the popup stayed open, "A card needs a word.", and the
    card's word untouched. No card was added either way.
    """
    page = review("resilient")
    editor = page[page.index("function editWord("):
                  page.index("overlay.querySelectorAll(\".word-edit\")")]

    assert "save.onclick = commit" in editor, "the button runs commit()"
    assert 'if (e.key !== "Enter") return' in editor, "and so does Enter"
    assert "e.preventDefault()" in editor
    assert editor.count("commit()") >= 1, "the key calls it rather than its own copy"
    assert editor.count("A card needs a word") == 1, (
        "one refusal, in the path both of them take")
