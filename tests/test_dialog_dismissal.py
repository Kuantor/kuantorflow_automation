"""Dialogs that hold work do not close on a stray click (kuantorflow#369).

kuantorflow#296 settled the rule for the review popup: clicking the page
outside a dialog that would *discard* something must not close it, while a
dialog holding nothing keeps that dismissal because there is nothing to lose.
The edit dialog was never covered, the Settings popup was never covered — and
it lives in `base.html`, so it had the flaw on every page — and kuantorflow#191's
two new popups were written against the older pattern and inherited it.

The fix is a deletion, so most of this file asserts what is **absent**, which
is the easiest kind of test to pass by accident. Two things keep it honest,
both borrowed from #296's own tests:

* every assertion is scoped to the script that owns the dialog, not to the
  page, because the dialogs that *keep* the dismissal would satisfy a
  page-wide search for the same code;
* the keepers are asserted to still have it, so a search-and-replace that
  strips the pattern everywhere fails here rather than passing quietly.

Escape is untouched and stays: #296 drew the line at a *slip*, and a keypress
is a deliberate act. But it had to learn something here — see the last test.
"""

import pytest


CARD = {"id": 7, "word": "resilient", "pos": "adjective", "topic": "character",
        "added_by_user_id": 7, "explanation_en": "", "translation_ukr": "стійкий",
        "translation_rus": "", "examples_en": ["An old example."],
        "examples_ukr": [], "examples_rus": []}


@pytest.fixture()
def cards_page(user_client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "get_flashcards_by_topic",
                        lambda topic, owner_id=None: [dict(CARD)])
    return user_client.get("/flashcards/character").get_data(as_text=True)


def _escape_handler(body):
    """Just the Escape branch, which is the only place that needs slicing —
    everything else below is asserted on a name unique to one dialog."""
    at = body.index('if (e.key === "Escape")')
    return body[at:at + 500]


# --- the four that hold something ------------------------------------------

@pytest.fixture()
def lookup_script(client):
    """kuantorflow#372 moved the two lookup popups' behaviour into a shared
    file, so the assertions about them follow it there rather than staying in
    the page and passing on its absence."""
    return client.get("/static/js/lookup_update.js").get_data(as_text=True)


@pytest.mark.parametrize("overlay,what", [
    ("editOverlay", "everything typed into the card, including a field the "
                    "#191 lookup has just filled"),
    ("settingsOverlay", "every switch and slider changed since it opened — and "
                        "this one is in base.html, so on every page"),
])
def test_a_dialog_holding_work_ignores_a_click_outside_it(cards_page, overlay,
                                                          what):
    """Asserted on the overlay's own name rather than a slice of the script.

    #296's warning was that a *generic* pattern — `e.target === overlay` — is
    satisfied by any dialog on the page, so a page-wide search proves nothing.
    These four names each belong to exactly one dialog, which makes the whole
    page the right place to look and removes the boundary that made the first
    version of this test pass against a restored handler.
    """
    assert overlay in cards_page, "the dialog is on this page at all"
    assert "e.target === %s" % overlay not in cards_page, what


# --- the ones that keep it, and must ---------------------------------------

@pytest.mark.parametrize("overlay", [
    "moveOverlay",        # #177 — one typed topic name, deliberately left alone
    "refusedOverlay",     # a notice; holds nothing
    "signInOverlay",      # a prompt; holds nothing
])
def test_a_dialog_holding_nothing_still_closes_on_a_click_outside(cards_page,
                                                                  overlay):
    """The half of #296 that is easy to lose: dismissing by looking away is
    right when there is nothing to lose, and a sweep that stripped the pattern
    everywhere would take these with it."""
    assert "e.target === %s" % overlay in cards_page


def test_the_delete_confirmation_still_closes_on_a_click_outside(cards_page):
    """The one keeper whose variable really is called `overlay`, so this is
    the one assertion that has to be scoped."""
    at = cards_page.index('function close() { overlay.hidden = true;')
    assert "e.target === overlay" in cards_page[at:at + 400]


# --- escape, and what it had to learn --------------------------------------

def test_escape_still_closes_the_edit_dialog(cards_page):
    assert "closeEdit()" in _escape_handler(cards_page)


@pytest.mark.parametrize("overlay", ["posOverlay", "rewriteOverlay"])
def test_the_lookup_popups_ignore_a_click_outside_them(lookup_script, overlay):
    """Both hold a lookup that has been paid for and not yet applied.

    Their markup is in base.html now and their behaviour in
    `lookup_update.js`, so this reads the script: an overlay that is only ever
    opened and closed by name there cannot be dismissed by a click it never
    listens for.
    """
    assert overlay not in lookup_script, "no variable of that name survives"
    assert "e.target ===" not in lookup_script, (
        "the file registers no backdrop dismissal at all, for either popup")


def test_escape_answers_the_popups_rather_than_hiding_them(cards_page,
                                                           lookup_script):
    """The bug the browser found while #369 was being checked.

    Both #191 popups hold a promise the lookup is waiting on. Escape used to
    set `hidden` directly, which left that promise pending for good: the button
    stayed disabled on "Looking up…" and the next press did nothing at all — so
    a learner who dismissed the question with the keyboard could not look
    anything up again without reloading the page.

    Every way out now goes through the popup's own dismissal, which is what
    resolves it. Measured in a browser: after Escape the button is usable
    again, and pressing it re-opens the picker.
    """
    handler = _escape_handler(cards_page)

    # The page asks the module rather than reaching into the popups itself.
    assert "kfLookupEscape()" in handler
    assert "hidden = true" not in handler.split("kfLookupEscape()")[1][:120], (
        "the page must not hide a popup behind the module's back")

    # And the module's own answer goes through each popup's dismissal, which
    # is the call that resolves the promise the lookup is waiting on.
    assert "dismissPos(); return true" in lookup_script
    assert "dismissRewrite(); return true" in lookup_script
