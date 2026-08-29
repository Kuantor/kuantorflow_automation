"""How the review popup can and cannot be dismissed (kuantorflow#296).

Clicking the page outside the dialog used to close the popup and throw away
every card that had not been added yet — cards that cost a lookup against two
providers, or a parsed file. #146 had already given this popup a cross whose
title says what closing means, *"Close and discard the remaining cards"*; the
stray click did the same thing and said nothing.

The fix is a deletion, so these tests are mostly about what is **absent**, and
absence is easy to assert by accident. Two things keep them honest:

* the assertions are scoped to the popup's own script block, not to the page —
  the duplicate-warning modal keeps its outside-click dismissal and would
  satisfy a page-wide search for the same code;
* the duplicate warning is asserted to *still have* it, so a future
  search-and-replace that strips the pattern everywhere fails here rather than
  passing quietly.

The blocking itself needed no change and is pinned in CSS: the overlay covers
the viewport, and Mykola's widget sits above it, which is why the chat keeps
working while the page behind does not.
"""

import re

import pytest


def _stub_lookup(app_module, monkeypatch):
    monkeypatch.setattr(
        app_module, "lookup_word",
        lambda word, topic=None, **providers: [
            {"word": word, "pos": "noun", "translation_ukr": "імовірність",
             "topic": topic}])


def _script_for(body, element_id):
    """The inline script block that drives one modal.

    Each popup's behaviour lives in its own IIFE, keyed by the element it
    reaches for first. Slicing to that is what makes "no click-outside here"
    a statement about this popup rather than about the page.
    """
    marker = f'document.getElementById("{element_id}")'
    start = body.index(marker)
    start = body.rindex("<script>", 0, start)
    return body[start:body.index("</script>", start)]


@pytest.fixture()
def popup(client, app_module, monkeypatch):
    """The page as it looks with the review popup open."""
    _stub_lookup(app_module, monkeypatch)
    return client.post("/", data={"action": "parse_word", "word": "probability",
                                  "topic": "vocab"}).get_data(as_text=True)


@pytest.fixture()
def warning(client, app_module, monkeypatch):
    """The page as it looks with the duplicate-word warning open (#145)."""
    monkeypatch.setattr(app_module, "flashcard_word_exists", lambda w: True)
    return client.post("/", data={"action": "parse_word", "word": "probability",
                                  "topic": "vocab"}).get_data(as_text=True)


# --- what a click outside must not do -----------------------------------


def test_a_click_outside_the_review_popup_does_nothing(popup):
    """The bug. The overlay is the click target for everything outside the
    dialog, so a listener on it is a listener on the whole page."""
    script = _script_for(popup, "proposal-modal")
    assert "overlay.addEventListener" not in script
    assert "e.target === overlay" not in script


def test_the_cross_still_closes_it(popup):
    """The deliberate way out, and the only one that says what it does."""
    script = _script_for(popup, "proposal-modal")
    assert 'getElementById("proposal-close").addEventListener("click", close)' \
        in script


def test_escape_still_closes_it(popup):
    """Kept on purpose: a deliberate keypress rather than a stray click, and
    what a keyboard user expects a dialog to answer. If it should go, it goes
    with this test."""
    script = _script_for(popup, "proposal-modal")
    assert 'e.key === "Escape"' in script


def test_the_per_card_controls_are_untouched(popup):
    """Removing one card and adding one card are the popup's actual work."""
    script = _script_for(popup, "proposal-modal")
    assert ".proposal-remove" in script
    assert "form.remove()" in script
    # `addCard(form, anyway)` since kuantorflow#379 -- the second argument is
    # whether the learner confirmed a duplicate, and this test is about the
    # per-card add existing at all.
    assert "addCard(form" in script
    assert popup.count("card-delete proposal-remove") == 1


def test_the_duplicate_warning_still_dismisses_on_an_outside_click(warning):
    """The scope of the fix, asserted from the other side. Dismissing that
    modal costs nothing — there is nothing behind it to lose — so it keeps the
    convenience, and a change that stripped the pattern from every dialog fails
    here."""
    script = _script_for(warning, "dup-warning-modal")
    assert "overlay.addEventListener" in script
    assert "e.target === overlay" in script


# --- and the page behind stays blocked ----------------------------------


@pytest.fixture()
def css(client):
    return client.get("/static/css/style.css").get_data(as_text=True)


def _z_index(css_text, selector):
    match = re.search(rf"^{re.escape(selector)} \{{(.*?)\}}", css_text,
                      re.M | re.S)
    assert match, f"no rule for {selector}"
    found = re.search(r"z-index:\s*(-?\d+)", match.group(1))
    assert found, f"{selector} sets no z-index"
    return int(found.group(1))


def test_the_overlay_covers_the_whole_viewport(css):
    """What makes "the page is blocked" true, and why removing the listener was
    the whole fix rather than the first half of one: the click never reached
    the page, it reached this."""
    match = re.search(r"^\.modal-overlay \{(.*?)\}", css, re.M | re.S)
    assert match, "no .modal-overlay rule"
    assert "position: fixed" in match.group(1)
    assert "inset: 0" in match.group(1)


def test_mykola_sits_above_the_overlay(css):
    """The one thing that should still work from inside the popup, and it does
    so by height rather than by any code: the widget is painted above the
    overlay, so its clicks never reach it."""
    assert _z_index(css, "#mykola-launcher") > _z_index(css, ".modal-overlay")
    assert _z_index(css, "#mykola-panel") > _z_index(css, ".modal-overlay")
