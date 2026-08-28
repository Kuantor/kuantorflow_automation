"""Look up & update on a card in the review popup (kuantorflow#372).

kuantorflow#191 put the button in the edit dialog, so the way to enrich a card
parsed from notes was to save a thin one and repair it afterwards. Now each
card in the **file-review** popup carries the same button, before anything is
written.

Three things are worth holding, and only the first two can be held here:

* **which popup gets it.** The file review, not the word lookup — in the
  latter every card was just built by a lookup, so the button would ask the
  same providers the same question and pay for the same answer;
* **one implementation.** The fetch, the conflict rule and the two popups are
  `static/js/lookup_update.js` and `base.html`, shared with the edit dialog. A
  second copy is how kuantorflow#359 happened;
* what the button *does*, which is browser behaviour and was measured there.
  The docstrings say what was measured rather than implying an assertion
  covers it.
"""

import io

import pytest


MHT = b"""From: <saved>
MIME-Version: 1.0
Content-Type: multipart/related; boundary="----=_B"

------=_B
Content-Type: text/html; charset="utf-8"
Content-Transfer-Encoding: 8bit

<html><body><p>resilient - stiykyi</p><p>scholar - naukovets</p></body></html>
------=_B--
"""


@pytest.fixture()
def file_review(user_client, saved):
    """The popup a notes upload opens."""
    return user_client.post(
        "/", data={"action": "upload_notes", "topic": "vocab",
                   "notes_file": (io.BytesIO(MHT), "notes.mht")},
        content_type="multipart/form-data", follow_redirects=True
    ).get_data(as_text=True)


@pytest.fixture()
def word_lookup(user_client, app_module, monkeypatch, saved):
    monkeypatch.setattr(app_module, "lookup_word",
                        lambda word, topic=None, **kw: [
                            {"word": word, "pos": "noun", "topic": topic,
                             "explanation_en": "a definition"}])
    return user_client.post("/", data={"action": "parse_word", "word": "x",
                                       "topic": "T"}).get_data(as_text=True)


# --- which popup gets the button -------------------------------------------

def test_every_card_from_a_file_has_one(file_review):
    assert file_review.count('class="secondary proposal-lookup"') == 2
    assert file_review.count('class="proposal-card"') == 2


def test_a_word_lookup_does_not(word_lookup):
    """Its cards were just built by a lookup; asking again buys the same
    answer twice."""
    assert 'class="secondary proposal-lookup"' not in word_lookup
    assert 'class="proposal-card"' in word_lookup, "the popup is there"


def test_the_handler_is_present_either_way(word_lookup):
    """The script is not conditional, and does not need to be — it binds to
    whatever buttons exist, which on a word lookup is none. Asserted so that
    the test above is read as being about the *button*, not about a page that
    happens not to mention the class at all."""
    assert ".proposal-lookup" in word_lookup


# --- one implementation ----------------------------------------------------

def test_the_behaviour_lives_in_one_file(client):
    """Not in either template. kuantorflow#359 is what a second copy costs:
    the notes parser had carried a private fix for the same defect the
    dictionaries went without."""
    script = client.get("/static/js/lookup_update.js")

    assert script.status_code == 200
    body = script.get_data(as_text=True)
    assert "kfLookupUpdate" in body and "conflictsFor" in body


@pytest.mark.parametrize("page,label", [("/", "the review popup"),
                                        ("/flashcards/vocab", "the edit dialog")])
def test_both_pages_load_the_module_and_have_the_popups(user_client, page,
                                                        label):
    """The popups are in base.html, so a page gets them by extending it."""
    body = user_client.get(page).get_data(as_text=True)

    assert "js/lookup_update.js" in body, label
    assert 'id="field-rewrite-confirm-popup"' in body
    assert 'id="lookup-pos-modal"' in body


def test_neither_template_carries_its_own_copy(file_review, user_client):
    """The precise failure this guards: a page that grew its own fetch.

    Both call sites should say *which* form and *which* button and nothing
    else, so the words that decide behaviour appear in the module only. The
    review popup is taken from an actual upload rather than a bare `GET /`,
    because its script is inside the popup and a page with no cards on it
    would satisfy "does not contain a copy" by containing nothing at all.
    """
    dialog = user_client.get("/flashcards/vocab").get_data(as_text=True)

    for name, body in (("review popup", file_review), ("edit dialog", dialog)):
        assert "conflictsFor" not in body, name
        assert "askWhichPos" not in body, name
        assert "kfLookupUpdate({" in body, "%s calls it instead" % name


# --- the rule that only this call site tests -------------------------------

def test_a_hidden_language_travels_as_a_hidden_input(user_client, saved):
    """Which is what makes "fill what the learner can see" a real rule here.

    The edit dialog renders no field at all for a hidden language, so the
    question never arises there. A proposal card carries one, and the module
    skips it — measured in a browser: with Russian hidden, a lookup returning
    `translation_rus` left that input at the value the parser gave it, while
    the visible Ukrainian field was filled.
    """
    user_client.post("/settings", json={"show_russian": False})
    body = user_client.post(
        "/", data={"action": "upload_notes", "topic": "vocab",
                   "notes_file": (io.BytesIO(MHT), "notes.mht")},
        content_type="multipart/form-data", follow_redirects=True
    ).get_data(as_text=True)

    # From the card, to the end of *that* form: the page has forms above the
    # popup, so an unanchored search finds one of those and slices nothing.
    start = body.index('class="proposal-card"')
    card = body[start:body.index("</form>", start)]

    assert 'type="hidden" name="translation_rus"' in card
    assert "Russian translation" not in card, "no visible field on the card"
    assert "Show Russian translation" in body, (
        "and the assertion above is scoped, since the Settings panel in "
        "base.html says those words on every page")


def test_the_module_only_fills_what_is_visible(client):
    """The rule, in the one place it is written down."""
    script = client.get("/static/js/lookup_update.js").get_data(as_text=True)

    assert 'input.type !== "hidden"' in script


def test_the_labels_are_associated_with_their_fields(file_review):
    """They were decorative until the rewrite confirmation started reading
    them back, and listed a conflicted row as `explanation_en`. Unique per
    card, since a popup holds a dozen."""
    assert 'for="proposal-1-explanation_en"' in file_review
    assert 'id="proposal-1-explanation_en"' in file_review
    assert 'for="proposal-2-explanation_en"' in file_review

# --- and where they are painted --------------------------------------------

def _z_index(css, selector):
    import re
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for match in re.finditer(r"([^{}@]+?)\{([^{}]*?)\}", stripped, re.S):
        if selector in [n.strip() for n in match.group(1).split(",")]:
            found = re.search(r"z-index:\s*(\d+)", match.group(2))
            if found:
                return int(found.group(1))
    return None


def test_the_popups_are_painted_above_the_dialog_they_open_over(client):
    """The bug this file's browser pass missed, and the user found.

    Both popups open **on top of another dialog** — the edit dialog, or the
    review popup — and every dialog is a `.modal-overlay` at `z-index: 100`.
    Sharing that layer leaves the stack to document order, and kuantorflow#372
    put these two in base.html *before* the content block: so the dialog they
    are supposed to sit above painted over them instead. The question was
    asked where nobody could see it, nothing could be clicked to answer it,
    and the button that opened it stayed on "Looking up…" for good.

    Measured with `elementFromPoint` on both callers after the fix: the
    topmost element at the popup's centre is inside the popup, and its Apply
    button is genuinely clickable. Forced back to 100 in the same page it is
    the overlay beneath — the hang, on demand.

    Asserted as arithmetic against `.modal-overlay` rather than as the number
    150, because what matters is the relationship: any dialog these open over
    must be below them.
    """
    css = client.get("/static/css/style.css").get_data(as_text=True)

    dialogs = _z_index(css, ".modal-overlay")
    for popup in ("#field-rewrite-confirm-popup", "#lookup-pos-modal"):
        layer = _z_index(css, popup)
        assert layer, "%s sets no layer of its own" % popup
        assert layer > dialogs, (
            "%s at %s is not above a dialog at %s" % (popup, layer, dialogs))


def test_they_stay_below_mykolas_widget(client):
    """kuantorflow#296 keeps the chat reachable while a dialog is open, and
    that arrangement should survive a popup opening on top of one."""
    css = client.get("/static/css/style.css").get_data(as_text=True)
    widget = _z_index(css, "#mykola-panel") or 200

    for popup in ("#field-rewrite-confirm-popup", "#lookup-pos-modal"):
        assert _z_index(css, popup) < widget

# --- the picker's own spacing and wording ----------------------------------

def test_the_chip_row_carries_its_own_spacing(client):
    """Both gaps were wrong and in opposite directions (#372).

    Above: the question's 17.6px bottom margin was joined by the 14.4px every
    `button` inherits, giving 32px. Below: `.modal-actions button` sets
    `margin-top: 0`, so *nothing* separated a chip from the button underneath
    and they touched — which is what a learner reported as an overlap.

    Measured after: 18px above and 19px below, at 1280x900 and 375x812, with
    one chip and with four.
    """
    css = client.get("/static/css/style.css").get_data(as_text=True)
    import re
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)

    row = re.search(r"\.pos-options\s*\{([^}]*)\}", stripped).group(1)
    chip = re.search(r"\.pos-option\s*\{([^}]*)\}", stripped).group(1)

    assert "margin-bottom" in row, "the row separates itself from the actions"
    assert "margin-top: 0" in chip, (
        "and does not inherit a second gap from `button`")


def test_one_entry_is_not_none_of_them(client):
    """The sentence said "found 1 entry, none of them matching": the plural
    was pluralised and the rest of it was not. Broken English on a page built
    for English teachers."""
    script = client.get("/static/js/lookup_update.js").get_data(as_text=True)

    assert "and it does not match this" in script, "the singular sentence"
    assert "entries, none of " in script, "and the plural one, unchanged"
