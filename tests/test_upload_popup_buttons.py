"""On a phone, a card's two buttons in the upload popup stay one line each
(kuantorflow#578).

Each card in the *Upload notes* review popup ends with **Add** and **Look up &
update** (`.proposal-actions`). With the site's 25.6px button padding, a
phone's ~245px card left *Look up & update* 157px for 125px of text, so it broke
onto two lines and stood 54px tall beside a 36px Add. On a phone the buttons
now take 1rem of side padding and never wrap their text, and the row itself may
wrap instead -- so below 360px *Look up & update* moves to its own line.

Resolved through the stylesheet's cascade (`conftest.css_winning`); the
heights were measured in a real browser for the PR.
"""

import pytest

from conftest import css_winning

ROW = [{"proposal-dialog", "proposal-dialog--source"}, {"proposal-card"},
       {"proposal-actions"}]
ADD = ROW + [{"add-btn"}]
LOOKUP = ROW + [{"secondary", "proposal-lookup"}]


@pytest.fixture()
def css(app_module):
    from pathlib import Path
    return (Path(app_module.__file__).parent / "static" / "css" / "style.css") \
        .read_text(encoding="utf-8")


@pytest.mark.parametrize("button", [ADD, LOOKUP], ids=["add", "look-up"])
def test_on_a_phone_the_buttons_never_wrap_their_text(css, button):
    assert css_winning(css, button, "white-space", phone=True) == "nowrap"


@pytest.mark.parametrize("button", [ADD, LOOKUP], ids=["add", "look-up"])
def test_on_a_phone_the_buttons_have_slimmer_side_padding(css, button):
    assert css_winning(css, button, "padding-inline", phone=True) == "1rem"


def test_on_a_phone_the_row_wraps_instead_of_the_text(css):
    assert css_winning(css, ROW, "flex-wrap", phone=True) == "wrap"


@pytest.mark.parametrize("button", [ADD, LOOKUP], ids=["add", "look-up"])
def test_a_computer_keeps_the_site_s_button(css, button):
    assert css_winning(css, button, "padding-inline", phone=False) is None
    assert css_winning(css, button, "white-space", phone=False) is None
    assert css_winning(css, ROW, "flex-wrap", phone=False) is None
