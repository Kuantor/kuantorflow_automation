"""The tip above the lookup box (kuantorflow#19).

The front page offers a lookup, an upload and a deck at once and said which one
to start with nowhere. This is the sentence that says it.

What can be asserted here is the markup and where it sits; **the dismissal is
browser behaviour and is verified in a real browser instead**, as the repo's
rule for that kind of change requires. What this file can still do is prove the
script that performs it is actually loaded, which is the half that silently
fails when a file is added but never referenced.
"""

import pytest


@pytest.fixture(autouse=True)
def deck(stub_deck):
    return stub_deck(cards=[])


def _index(client):
    return client.get("/").get_data(as_text=True)


def test_the_tip_says_what_to_do(client):
    body = _index(client)
    assert "Enter a word here" in body
    assert "Look up &amp; save" in body


def test_the_tip_is_above_the_box_it_is_about(client):
    """Below the field it would be a caption on something already used, and
    the visitor it is written for reads the page top to bottom."""
    body = _index(client)
    assert 0 <= body.index('id="lookup-tip"') < body.index('name="word"')


def test_the_script_that_dismisses_it_is_loaded(client):
    """The half that fails silently: markup with no behaviour leaves a tip
    that never goes away, and nothing about the page would look wrong."""
    assert "lookup_tip.js" in _index(client)


def test_it_can_be_dismissed_without_touching_the_box(client):
    """A visitor who has read it and does not want to type yet still needs a
    way out of it."""
    assert "lookup-tip__close" in _index(client)


def test_hiding_the_tip_actually_hides_it(app_module):
    """The one CSS rule this feature cannot live without, and the only bug the
    browser found: `.lookup-tip` sets `display: flex`, and a class selector
    beats the browser's own `[hidden] { display: none }` -- so the script set
    the attribute and the tip stayed on the screen, dismissed and still there.

    Asserted against the stylesheet because nothing else in this suite computes
    style. It is deliberately a rule about *this* class rather than a copy of
    the declaration: what must hold is that hiding the tip hides it.
    """
    from pathlib import Path
    css = Path(app_module.app.static_folder, "css", "style.css").read_text(
        encoding="utf-8")
    assert ".lookup-tip[hidden]" in css
