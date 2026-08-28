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
