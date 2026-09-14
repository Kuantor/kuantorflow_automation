"""Saving Settings refreshes a page the change would alter (kuantorflow#433).

The Settings popup saves by `fetch`, so nothing refreshes unless the handler
asks for it — and it used to ask only for two settings, named in an array:
`individual_cards` and `alphabetical_topics`. Hiding a language stored the
choice and left the cards on screen with their Ukrainian still in them.

**These assertions read the script text, and that needs justifying**, because
this suite does not execute JavaScript. What is being guarded is not a value
but a *property*: that the decision is derived from the form's own controls
rather than enumerated from a list of setting names. A list is the failure —
it cannot be remembered by whoever adds the next setting — so a test that
merely checked the list contained `show_ukrainian` would bless the shape that
caused the bug.

The behaviour itself was checked in a browser, against the real form on a
flashcards page: the predicate returns true after hiding Ukrainian, true after
hiding Russian, true for `individual_cards` as before, and false when only
`speech_rate` moves or nothing is touched.
"""

import re

import pytest


@pytest.fixture()
def script(app_module):
    """The Settings save handler, as rendered into the page."""
    from pathlib import Path
    base = Path(app_module.app.root_path, "templates", "base.html")
    html = base.read_text(encoding="utf-8")
    start = html.index("settingsForm.addEventListener(\"submit\"")
    return html[start:start + 8000]


def test_the_reload_is_not_decided_by_a_list_of_setting_names(script):
    """The bug itself. Two names were in the array and the language settings
    were not, so a control's author had to remember a line somewhere else.

    Asserted on the *mechanism* rather than on the old array's text, because
    the comment explaining the fix quotes that array — and a test that read a
    comment would fail the moment somebody reworded it.
    """
    assert "settingsForm[name]" not in script


def test_it_asks_the_form_which_controls_changed(script):
    """Derived, so a setting added tomorrow is covered without an edit."""
    assert "settingsForm.querySelectorAll" in script


def test_it_compares_against_what_the_server_rendered(script):
    """`defaultChecked` and `defaultValue` hold the values the page was built
    with, which is exactly the question: is what the learner is looking at
    still what the server would send?"""
    assert "defaultChecked" in script
    assert "defaultValue" in script


def test_the_settings_the_browser_applies_itself_are_exempt_and_named(script):
    """Not an omission this time: both are applied in this same handler —
    `speech_rate` through a data attribute that `speech.js` reads on every
    press, and the typewriter through the widget's own setter. Reloading for
    them would be churn."""
    exempt = re.search(r"APPLIED_WITHOUT_A_RELOAD\s*=\s*\[([^\]]*)\]", script)
    assert exempt, "the exemptions should be a named declaration"
    names = re.findall(r'"([a-z_]+)"', exempt.group(1))
    assert sorted(names) == ["mykola_typewriter", "speech_rate"]


def test_a_reload_still_happens_at_all(script):
    """The half that would make every other assertion vacuous."""
    assert "window.location.reload()" in script


@pytest.mark.parametrize("setting", ["show_ukrainian", "show_russian",
                                     "individual_cards", "alphabetical_topics",
                                     "explanatory_dictionary", "quiz_lang"])
def test_every_server_rendered_setting_is_still_submitted(client, setting):
    """The derivation only works over controls that are in the form. A setting
    saved but not rendered as an input would be invisible to it."""
    body = client.get("/").get_data(as_text=True)
    assert f'name="{setting}"' in body
