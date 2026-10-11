"""The upload review popup splits its two columns half and half (kuantorflow#576).

The *File content* column was a narrow strip beside the cards: both panes were
meant to be `flex: 1 1 0`, but #349's later `.proposal-dialog
.proposal-cards-pane { flex: 1 1 auto }` has the same specificity and a later
place, so the cards pane started from its content's width and the file's text
got what was left (measured 265px against 598px at 1280px). The same ordering
had overridden the phone rule that stacks the columns, so at 375px they stayed
side by side and the file column was 0px wide.

The suite cannot lay a page out, so these resolve the stylesheet's cascade for
the popup's elements the way a browser would -- specificity, then order, with
the phone media query applied or not -- and check what wins. The widths were
measured in a real browser for the PR.
"""

import pytest

from conftest import css_winning as _winning

# The popup's elements, each as its chain of class sets from the dialog down.
DIALOG = {"modal", "modal-dialog", "proposal-dialog", "proposal-dialog--source"}
BODY = [DIALOG, {"proposal-body"}]
SOURCE = BODY + [{"proposal-source"}]
CARDS = BODY + [{"modal-scroll", "proposal-cards-pane"}]


@pytest.fixture()
def css(app_module):
    from pathlib import Path
    return (Path(app_module.__file__).parent / "static" / "css" / "style.css") \
        .read_text(encoding="utf-8")


def test_on_a_computer_the_columns_sit_side_by_side(css):
    assert _winning(css, BODY, "flex-direction", phone=False) == "row"


def test_on_a_computer_both_columns_take_half(css):
    source = _winning(css, SOURCE, "flex", phone=False)
    cards = _winning(css, CARDS, "flex", phone=False)

    assert source == cards == "1 1 50%"


def test_on_a_phone_the_columns_stack(css):
    assert _winning(css, BODY, "flex-direction", phone=True) == "column"


def test_on_a_phone_the_file_content_keeps_its_height_cap(css):
    """Stacked, the file pane takes its own height up to 30vh and the cards
    the rest; a zero basis in a column would give the file nothing."""
    assert _winning(css, SOURCE, "flex", phone=True) == "0 0 auto"
    assert _winning(css, SOURCE, "max-height", phone=True) == "30vh"


def test_the_resolver_sees_the_override_that_caused_this(css):
    """The premise: #349's rule still gives the cards pane `1 1 auto` on its
    own, which is why the upload variant must restate its basis after it."""
    plain = [DIALOG - {"proposal-dialog--source"}, {"proposal-body"},
             {"modal-scroll", "proposal-cards-pane"}]
    assert _winning(css, plain, "flex", phone=False) == "1 1 auto"
