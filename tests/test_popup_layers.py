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
