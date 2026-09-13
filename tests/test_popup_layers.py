"""Which popup covers which (kuantorflow#75).

The stacking order is decided in five separate CSS rules, each of which only
knows its own number, and **the default is that Mykola's widget covers the
dialogs** — #296 chose that on purpose so a learner can ask about the card in
front of them, and #372's popups were given 150 rather than more for exactly
that reason.

About is one of the two deliberate exceptions, because there is nothing in it
to ask about: it is a page of prose you read and close, and on a phone the chat
panel is most of the screen, so an open conversation covered it.

So what is asserted here is a **relationship, not a number**. Both values are
read out of the stylesheet and compared; changing either one deliberately keeps
this green, and changing one by accident does not. A test holding `260` would
freeze the value it was written to protect.

The rendered result was checked in a real browser at 375x812, with the chat
open: the point over the launcher belongs to `#about-modal`.
"""

import re

import pytest


LAYERS = {
    "#about-modal": None,
    "#mykola-launcher": None,
    "#mykola-panel": None,
    ".modal-overlay": None,
    ".welcome-overlay": None,
}


@pytest.fixture()
def css_text(app_module):
    from pathlib import Path
    return Path(app_module.app.static_folder, 'css', 'style.css').read_text(
        encoding='utf-8')


@pytest.fixture()
def z(app_module):
    """`{selector: z-index}` read out of the stylesheet itself."""
    from pathlib import Path
    css = Path(app_module.app.static_folder, "css", "style.css").read_text(
        encoding="utf-8")
    found = {}
    for selector in LAYERS:
        # Every block whose selector is *this element itself* -- the name
        # followed by `{` or by a comma, so `#mykola-launcher::after`'s own
        # `z-index: -1` is not mistaken for the launcher's layer. A selector
        # usually has several rules and only one of them sets the layer.
        blocks = re.findall(
            re.escape(selector) + r"\s*(?:,[^{}]*)?\{([^}]*)\}", css)
        assert blocks, f"no rule found for {selector}"
        layers = [int(m.group(1)) for m in
                  (re.search(r"z-index:\s*(-?\d+)", b) for b in blocks) if m]
        assert len(layers) == 1, f"{selector} sets z-index {len(layers)} times"
        found[selector] = layers[0]
    return found


def test_about_covers_the_chat_widget(z):
    """#75, and the whole of it: on a phone the panel is most of the screen."""
    assert z["#about-modal"] > z["#mykola-launcher"]
    assert z["#about-modal"] > z["#mykola-panel"]


def test_the_welcome_screen_covers_it_too(z):
    """The other deliberate exception, and it was already true — the thing you
    see before the app has nothing to ask about either."""
    assert z[".welcome-overlay"] > z["#mykola-panel"]


def test_an_ordinary_dialog_still_sits_below_the_chat(z):
    """The half that keeps #296: a dialog that is part of *doing* something
    keeps the chat usable on top of it. Raising the shared `.modal-overlay`
    would have fixed #75 and silently undone that."""
    assert z[".modal-overlay"] < z["#mykola-panel"]


# --- beside the widget rather than behind it (kuantorflow#424) -------------


def _media_min_width(css, needle):
    """The `min-width` of the media query whose body contains `needle`."""
    import re
    for m in re.finditer(r"@media\s*\(min-width:\s*(\d+)px\)\s*\{", css):
        # The query's own body: brace-count from the opening brace, because it
        # contains nested rules.
        depth, i = 1, m.end()
        while depth and i < len(css):
            depth += (css[i] == "{") - (css[i] == "}")
            i += 1
        if needle in css[m.end():i]:
            return int(m.group(1))
    return None


def test_a_dialog_moves_out_of_the_open_panels_way(css_text):
    """#424: #227 made the edit popup 700px and its Cancel button went behind
    the chat. #296 keeps the widget above dialogs on purpose, so the answer is
    to move the dialog, not to raise it."""
    assert "body.mykola-open .modal-overlay" in css_text


def test_it_reserves_the_panels_own_width(css_text):
    """Not a second copy of the panel's dimensions: `--mykola-space` is the
    declaration, and the page shift already reads it."""
    import re
    rule = re.search(
        r"body\.mykola-open \.modal-overlay[^{]*\{([^}]*)\}", css_text)
    assert rule and "var(--mykola-space)" in rule.group(1)


def test_about_is_left_where_it_is(css_text):
    """It sits *above* the widget since #75 and its overlay hides the chat
    completely, so an off-centre dialog there would look like a mistake."""
    import re
    selector = re.search(
        r"(body\.mykola-open \.modal-overlay[^{]*)\{", css_text).group(1)
    assert "#about-modal" in selector and ":not(" in selector


def test_dialogs_shift_at_the_same_width_the_page_does(css_text):
    """A relationship rather than a number, and the reason is in the page
    rule's own comment: below this width the space beside the panel is narrower
    than the thing being centred in it, so shifting pushes the *left* edge off
    screen -- losing the Word field to save the Cancel button. Two breakpoints
    drifting apart would mean the page had moved and the dialog had not."""
    page = _media_min_width(css_text, "body.mykola-open .page")
    dialog = _media_min_width(css_text, "body.mykola-open .modal-overlay")
    assert page is not None and dialog == page
