"""A dialog keeps its action row inside itself (kuantorflow#375).

The rewrite confirmation -- the popup *Look up & update* opens when the lookup
found text for a field that already holds some -- let **Replace the ticked
fields** and **Fill only the empty ones** hang out through the bottom of the
white box, painted over the overlay below the dialog's rounded corner.

Two caps that were written independently:

* `.modal` bounds a dialog at `max-height: 90vh`;
* `.modal-scroll` bounds the list inside it at a **fixed** `max-height: 65vh`.

Everything else -- title, hint, action row, padding -- is 150px of chrome added
on top of that 65vh, and a plain block cannot give: past 90vh the content simply
carries on past a box that has no `overflow` of its own to clip it. So the
threshold is arithmetic rather than a matter of how much the lookup returned
(the pane is already at its cap): `0.65H + 150 > 0.9H` at any viewport shorter
than about 740px. A maximised browser on a 1080p screen is fine; a half-height
window, or one with devtools docked underneath, is not.

Measured on the **real** `/flashcards/vocab` page -- dumped through the test
client, served beside the app's own stylesheet, rows built into
`#rewrite-fields` with the same DOM `lookup_update.js` builds -- at 1280 wide,
as the gap between the Apply button's bottom and the dialog's (negative is
inside):

| Viewport | before | after |
|---|---|---|
| 900px | -24px | -24px |
| 740px | -24px | -24px |
| 620px | -4.9px | -24px |
| 600px | **+10.8px** | -24px |

and at 500px, after the fix, -24px again.

`document.elementFromPoint` three pixels below the dialog's bottom edge at 600px
returned `rewrite-apply` before and the overlay after: the button really was
outside the box rather than merely close to its edge.

None of that is visible to an assertion in this suite, so what is pinned here is
the arrangement that produces it, and the measurements live in the docstrings.
The two rules the fix adds are what the first two tests fail without.
"""

import io
import re

import pytest
from bs4 import BeautifulSoup


MHT = b"""From: <saved>
MIME-Version: 1.0
Content-Type: multipart/related; boundary="----=_B"

------=_B
Content-Type: text/html; charset="utf-8"
Content-Transfer-Encoding: 8bit

<html><body><p>resilient - stiykyi</p></body></html>
------=_B--
"""


def _declarations(css_text, selector):
    """Every declaration written for one selector, joined and collapsed.

    All of them rather than the first: `.proposal-dialog` is declared where its
    width is set and again where #349 made it a flex column, and a helper that
    stopped at the first match reported the second rule as missing.
    """
    stripped = re.sub(r"/\*.*?\*/", "", css_text, flags=re.S)
    found = []
    for match in re.finditer(r"([^{}@]+?)\{([^{}]*?)\}", stripped, re.S):
        names = [n.strip() for n in match.group(1).split(",")]
        if selector in names:
            found.append(" ".join(match.group(2).split()))
    return " ".join(found)


@pytest.fixture()
def css(client):
    return client.get("/static/css/style.css").get_data(as_text=True)


# --- the arrangement that contains the buttons -----------------------------

def test_a_dialog_whose_body_scrolls_is_a_flex_column(css):
    """The head keeps its natural height and the scroll region takes the rest.

    Written as `:has(> .modal-scroll)` rather than against the two dialogs by
    name, because the bug is the shape and not the instance: #349 met it in the
    review popup, #375 in the rewrite confirmation, and the next dialog with a
    scrolling body would meet it again.
    """
    rule = _declarations(css, ".modal-dialog:has(> .modal-scroll)")

    assert rule, "no rule makes a dialog with a scroll pane a flex column"
    assert "display: flex" in rule
    assert "flex-direction: column" in rule


def test_its_scroll_region_may_shrink_below_its_content(css):
    """`min-height: 0` is the load-bearing half, and the silent one.

    A flex item defaults to `min-height: auto` and refuses to shrink below its
    content -- which is exactly how a child escapes its parent. Drop this line
    and the dialog is still a flex column, still looks fixed at a glance, and
    the buttons are outside again.
    """
    rule = _declarations(css, ".modal-dialog > .modal-scroll")

    assert rule, "the pane is not told it may shrink"
    assert "min-height: 0" in rule

    shrink = re.search(r"flex: \d+ (\d+)", rule)
    assert shrink, "no flex shorthand to read a shrink factor from"
    assert int(shrink.group(1)) > 0, "flex-shrink: 0 refuses the room as well"


def test_the_dialog_is_bounded_in_the_first_place(css):
    """The other half of the arithmetic, and not part of the fix.

    Without `max-height` on `.modal` a dialog simply grows and a flex column
    changes nothing -- there is no shortfall to distribute. Asserted so the two
    numbers that decide this are read together.
    """
    rule = _declarations(css, ".modal")

    assert rule and "max-height: 90vh" in rule


# --- and what it deliberately does not change ------------------------------

def test_the_caps_stay_caps(css):
    """No `max-height: none` beside the shrink rule.

    #349 lifted the cap when it did this for the review popup, because the flex
    row around it bounded the pane instead. Here nothing else does, and lifting
    it would grow both panes on a tall window -- a change to dialogs that were
    not broken. Only shrinking is new: with room to spare the page renders as it
    did, which is what the 740px and 900px rows in this file's table say.
    """
    shrink = _declarations(css, ".modal-dialog > .modal-scroll")
    pane = _declarations(css, ".modal-scroll")
    edit = _declarations(css, ".edit-fields")

    assert "max-height" not in shrink, "the fix must not touch the cap"
    assert "max-height: 65vh" in pane, "the shared cap"
    assert "max-height: 58vh" in edit, (
        "and the edit dialog's own, which is why its threshold is a ~366px "
        "viewport and it was never reachable in practice (#227 owns its "
        "sizing)")


def test_the_review_popup_keeps_its_own_arrangement(css):
    """#349's fix is a different one and stays.

    Its pane is **not** a direct child of the dialog -- `.proposal-body` sits
    between them -- so `.modal-dialog > .modal-scroll` does not reach it, and
    the flex row it lives in is what bounds it there.
    """
    dialog = _declarations(css, ".proposal-dialog")
    body = _declarations(css, ".proposal-dialog .proposal-body")
    pane = _declarations(css, ".proposal-dialog .proposal-cards-pane")

    assert "display: flex" in dialog and "flex-direction: column" in dialog
    assert "min-height: 0" in body
    assert "max-height: none" in pane


# --- the markup half: the rule only reaches a direct child -----------------

def _panes(html):
    return BeautifulSoup(html, "lxml").select(".modal-scroll")


@pytest.fixture()
def flashcards(user_client, saved):
    return user_client.get("/flashcards/vocab").get_data(as_text=True)


@pytest.fixture()
def review(user_client, saved):
    return user_client.post(
        "/", data={"action": "upload_notes", "topic": "vocab",
                   "notes_file": (io.BytesIO(MHT), "notes.mht")},
        content_type="multipart/form-data", follow_redirects=True
    ).get_data(as_text=True)


def test_the_dialogs_that_scroll_are_the_two_expected_ones(flashcards):
    """A third one appearing is not a failure -- it is a prompt to check that
    the rule reaches it, which the test below is what does."""
    ids = sorted(pane.get("id") or pane.get("class")[-1]
                 for pane in _panes(flashcards))

    assert ids == ["edit-form", "rewrite-fields"]


@pytest.mark.parametrize("page", ["flashcards", "review"])
def test_every_scroll_pane_is_reached_by_one_of_the_two_arrangements(page,
                                                                     request):
    """The regression this guards, which no CSS assertion can.

    `.modal-dialog > .modal-scroll` is a **child** selector, so wrapping a pane
    in a div -- a heading, a toolbar, an error line given its own container --
    silently stops the rule applying and puts the buttons back outside. Nothing
    breaks loudly; the dialog just grows past itself again on a short window.

    Two arrangements are allowed: a direct child (#375), or the review popup's
    flex row (#349), which is the one pane that is deliberately nested.
    """
    html = request.getfixturevalue(page)
    panes = _panes(html)

    assert panes, "no scroll pane on this page at all"
    for pane in panes:
        parent = pane.parent
        classes = parent.get("class") or []
        if "modal-dialog" in classes:
            continue
        assert "proposal-body" in classes, (
            "%s sits inside <%s class=%r>, which neither arrangement reaches"
            % (pane.get("id") or pane.get("class"), parent.name, classes))
        assert "proposal-dialog" in (parent.parent.get("class") or [])
