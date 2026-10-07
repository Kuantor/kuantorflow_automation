"""The deck's *Flip animation* toggle is readable (kuantorflow#572).

The toggle is a `<label>` in the deck's toolbar, which sets white text for
everything in it over the dark page. But the global form rule in `style.css`,
`label { ... color: var(--muted) }`, applies to the label **element itself**,
and a rule on an element beats an inherited value -- so the toggle rendered
grey on its dark pill (measured `rgb(74, 88, 102)`), and the same rule's margin
put the pill 3px below the counter beside it. The counter is a `<span>`, which
is why it stayed white.

So the toggle sets its own colour and resets that margin. The suite cannot see
computed styles; these pin the rule that produces them, on the page as served,
and the premise that makes the rule necessary. The computed colour was checked
in a real browser for the PR.
"""

import re

import pytest

CARDS = [{"id": 1, "word": "abstract", "pos": "adjective", "topic": "Work",
          "translation_ukr": "абстрактний", "translation_rus": "абстрактный"}]


def _rule(text, selector):
    """The declarations of `selector { ... }` in `text`, as a dict."""
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", text)
    assert match, f"no {selector} rule"
    return {k.strip(): v.strip() for k, v in
            (d.split(":", 1) for d in match.group(1).split(";") if ":" in d)}


@pytest.fixture()
def deck_page(client, stub_deck):
    stub_deck(cards=CARDS)
    response = client.get("/deck/Work")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def test_the_toggle_sets_its_own_white(deck_page):
    assert 'class="deck-anim-toggle"' in deck_page
    assert _rule(deck_page, ".deck-anim-toggle").get("color") == "#fff"


def test_the_toggle_resets_the_label_margin(deck_page):
    """Without it the pill sat 3px below the counter it lines up with."""
    assert _rule(deck_page, ".deck-anim-toggle").get("margin") in ("0", "0px")


def test_the_premise_a_global_label_colour_still_applies(app_module):
    """Why the toggle needs a colour of its own: if the global label rule ever
    stops setting one, this test says the toggle's own rule can be simplified."""
    from pathlib import Path
    css = (Path(app_module.__file__).parent / "static" / "css" / "style.css") \
        .read_text(encoding="utf-8")

    assert "color" in _rule(css, "\nlabel")
