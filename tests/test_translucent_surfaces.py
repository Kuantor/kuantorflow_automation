"""Half-transparent panels, chat widget and cards (kuantorflow#197, #201).

The site sits on a photograph and almost none of it was visible. The content
panels are translucent now, and Mykola's panel is too — but less so, because it
holds a whole conversation rather than a short form. The flashcards got a third
value again (#201): a topic page is one panel per card, dozens of them stacked,
so what reads as a tint behind three short forms becomes a wall of
half-transparent text there.

Two things here are not obvious from looking at the page:

The opacity is a pair of CSS variables rather than literal alphas, because the
values are meant to be tuned by eye and a single place to do that is the point.

And the widget's knob is only doing anything because its *interior* panes were
made transparent. They used to be solid, which covered the panel's background
completely — the alpha could be set to anything at all and nothing would
change. That is the failure this file mostly exists to catch, because it looks
like nothing is wrong: the CSS is valid, the variable is there, and the widget
simply stays opaque.
"""

import re

import pytest


@pytest.fixture()
def css(client):
    return client.get("/static/css/style.css").get_data(as_text=True)


def _alpha(css_text, name):
    """The value of a --*-alpha custom property."""
    match = re.search(rf"--{name}-alpha:\s*([0-9.]+)", css_text)
    assert match, f"--{name}-alpha is not defined"
    return float(match.group(1))


def _rule(css_text, selector):
    """The declarations of the rule whose selector is exactly `selector`.

    Anchored to the start of a line, or `#mykola-panel` would match
    `body.settings-open #mykola-panel { display: none }` and `.mykola-auth`
    would match the `.minimized` override — both of which say nothing about
    the background and would let these tests pass on the wrong rule.
    """
    match = re.search(rf"^{re.escape(selector)} \{{", css_text, re.M)
    assert match, f"no rule for {selector}"
    return css_text[match.start():css_text.index("}", match.start())]


# --- the knobs ---------------------------------------------------------------

def test_both_opacities_are_variables(css):
    """They are meant to be adjusted by eye; literals scattered through the
    stylesheet would make that a hunt."""
    assert 0 < _alpha(css, "panel") <= 1
    assert 0 < _alpha(css, "widget") <= 1


def test_the_panels_use_the_panel_variable(css):
    assert "rgba(255, 255, 255, var(--panel-alpha))" in _rule(css, ".panel")


def test_the_widget_uses_its_own_variable(css):
    assert "var(--widget-alpha)" in _rule(css, "#mykola-panel")


def test_the_widget_is_the_more_opaque_of_the_two(css):
    """A conversation is the most reading-heavy surface on the site, so it
    gets more white behind it than a panel holding a short form."""
    assert _alpha(css, "widget") > _alpha(css, "panel")


def test_neither_surface_is_blurred(css):
    """A backdrop blur hides the background, which is the thing being
    revealed — asked for explicitly."""
    assert "backdrop-filter" not in _rule(css, ".panel")
    assert "backdrop-filter" not in _rule(css, "#mykola-panel")


# --- the flashcards page gets a third (#201) ---------------------------------

def test_the_cards_have_their_own_opacity(css):
    assert 0 < _alpha(css, "flashcard") <= 1
    assert "rgba(255, 255, 255, var(--flashcard-alpha))" in _rule(css, ".card")


def test_a_card_is_more_opaque_than_a_main_page_panel(css):
    """Why it needs a number at all: the main page has three panels, a topic
    page has one per card — dozens, stacked, each carrying a word, a part of
    speech, an explanation and two translations with their examples."""
    assert _alpha(css, "flashcard") > _alpha(css, "panel")


def test_the_plain_panels_on_that_page_are_unaffected(css):
    """A topic page also renders an ordinary `.panel` — the empty-topic
    explanation (#127). It keeps the main page's value, because it is doing
    the main page's job rather than the card's. Decided, not incidental."""
    assert "var(--panel-alpha)" in _rule(css, ".panel")
    assert "--panel-alpha" not in _rule(css, ".card")


# --- the part that fails silently --------------------------------------------

@pytest.mark.parametrize("pane", ["#mykola-messages", "#mykola-form",
                                  ".mykola-auth"])
def test_the_widgets_inner_panes_do_not_cover_it(css, pane):
    """Each of these used to be a solid fill spanning the panel. With any one
    of them opaque again, --widget-alpha silently stops meaning anything: the
    CSS stays valid and the widget just looks the same as before."""
    assert "background: transparent" in _rule(css, pane), pane


def test_the_message_bubbles_keep_their_fills(css):
    """They are content, not the surface behind it — a transparent bubble
    would leave the two speakers indistinguishable."""
    assert "background: #fff" in _rule(css, ".mykola-msg.mykola")


# --- what must not change ----------------------------------------------------

def test_the_top_bar_is_untouched(css):
    """Excluded from #197 by name."""
    assert "background: rgba(20, 40, 60, 0.55)" in _rule(css, ".site-header")


def test_the_settings_dialog_stays_solid(css):
    """Dropped from #197: through a translucent dialog you would see the
    dimmed page rather than the background, which is not the effect."""
    assert "background: #fff" in _rule(css, ".modal-dialog")


def test_the_topic_tiles_stay_solid(css):
    """#185 will put a picture on each; a translucent tile showing the
    background behind a photograph inside it would be a mess."""
    assert "var(--blue)" in _rule(css, ".topic-tile")
    assert "--panel-alpha" not in _rule(css, ".topic-tile")
