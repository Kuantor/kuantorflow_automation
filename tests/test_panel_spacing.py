"""The gap between a panel's fields and its button (kuantorflow#298).

*Look up & save* sat 52px below its fields while *Upload & save* sat 14px below
its own. 14px is `button { margin-top: 0.9rem }`, which both have; the other
38px was the hint added by #292. The hint lives in the **Topic** column, a flex
row is as tall as its tallest column, and so a caption belonging to the right
column was pushing the button down under the left one.

The fix is to take the hint out of the row's flow. That makes three things
load-bearing, and each fails silently rather than loudly:

* `position: absolute` on the hint — without it the row grows again and the
  buttons drift apart, which looks like nothing in particular;
* `position: relative` on the column — without it the hint anchors to whatever
  ancestor is positioned, or to the page, and lands somewhere unrelated;
* `position: static` again below 600px — where the row stacks, the Topic box is
  the last field, and an out-of-flow hint would sit on top of the button.

All three are CSS, so this file reads the stylesheet. The geometry itself was
measured in a browser at 1280px, 620px, 601px and 375px: 14px in both panels,
the hint 5px under the Topic box and never overlapping the button, wrapping to
two lines at the narrowest two-column width with 31px still clear of the
panel's edge.
"""

import re

import pytest


@pytest.fixture()
def css(client):
    return client.get("/static/css/style.css").get_data(as_text=True)


def _blocks(css_text, within):
    """Every `@media <within>` block's body — there is more than one of each.

    The stylesheet opens a second `@media (max-width: 600px)` further down
    rather than keeping one, so taking the first is how a rule that is really
    there reads as missing.
    """
    return [css_text[m.end():css_text.index("\n}", m.end())]
            for m in re.finditer(rf"@media {re.escape(within)} \{{", css_text)]


def _rule(css_text, selector, within=None):
    """Every declaration written for `selector`, joined.

    All of them, not the first: `.form-row > div` is set where the row is
    defined and could be extended anywhere below, and a helper that stopped at
    the first match would report a rule that has since been overridden.

    **A selector counts wherever it appears in the list, not only alone on its
    own line.** This used to anchor on `^\\s*<selector> {`, which quietly
    reported "no rule" the moment `button` joined a comma-separated list
    (kuantorflow#340 put `a.button-link` beside it so the two could not drift).
    Grouping a selector does not change what it declares, and a helper that
    says otherwise fails on a refactor rather than on a regression.
    """
    scopes = _blocks(css_text, within) if within else [css_text]
    found = []
    for scope in scopes:
        # Comments first: one containing a brace would otherwise close a block
        # early and truncate the declarations being read.
        stripped = re.sub(r"/\*.*?\*/", "", scope, flags=re.S)
        for m in re.finditer(r"([^{}@]+?)\{([^{}]*?)\}", stripped, re.S):
            names = [n.strip() for n in m.group(1).split(",")]
            if selector in names:
                found.append(" ".join(m.group(2).split()))
    assert found, (f"no rule for {selector}"
                   + (f" in @media {within}" if within else ""))
    return " ".join(found)


# --- what makes the two gaps equal --------------------------------------


def test_the_hint_is_out_of_the_rows_flow(css):
    """The whole fix. In flow it adds its height to its own column, and the row
    is as tall as its tallest column — so the button under the *other* column
    moves down with it."""
    rule = _rule(css, ".form-hint")
    assert "position: absolute" in rule
    assert "top: 100%" in rule, "it has to hang below the field, not over it"


def test_the_hint_is_anchored_to_its_own_column(css):
    """Without a positioned column it would anchor to the nearest positioned
    ancestor — or the page — and appear somewhere unrelated. This one line is
    what keeps it under the Topic box."""
    assert "position: relative" in _rule(css, ".form-row > div")


def test_the_button_still_carries_the_only_gap(css):
    """14px in both panels, and it comes from the button rather than from
    anything panel-specific. A second source of spacing here is how the two
    would drift apart again."""
    assert "margin-top: 0.9rem" in _rule(css, "button")


def test_the_hint_adds_no_margin_below_itself(css):
    """It used to end with a 0.9rem bottom margin, which was part of the 38px.
    Out of flow that margin would do nothing; stacked, it would put the hint
    and the button 24px apart instead of the button's own 14px."""
    rule = _rule(css, ".form-hint")
    margin = re.search(r"margin:\s*([^;]+)", rule)
    assert margin, "the hint sets no margin at all"
    # Exact, not a prefix: `0.3rem 0 0.9rem` starts with `0.3rem 0 0` and would
    # satisfy a substring check while being the value this fixed.
    assert margin.group(1).split() == ["0.3rem", "0", "0"]


# --- and the phone, where the row stacks --------------------------------


def test_the_hint_returns_to_the_flow_when_the_row_stacks(css):
    """Stacked, the Topic box is the last field and the hint belongs between it
    and the button. Out of flow it would land on the button — and the mismatch
    this ticket is about cannot arise there anyway, since both panels stack the
    same way."""
    assert "position: static" in _rule(css, ".form-hint", within="(max-width: 600px)")


def test_the_row_still_stacks_at_the_same_width(css):
    """The two rules are a pair: the hint goes back into the flow exactly where
    the columns become rows. Splitting them by a pixel would leave a width with
    a hint on top of a button."""
    assert "flex-direction: column" in \
        _rule(css, ".form-row", within="(max-width: 600px)")


# --- the markup the CSS depends on --------------------------------------


def test_the_hint_is_still_inside_the_topic_column(client):
    """The CSS anchors the hint to its column, so the fix is only true while
    the hint is *in* that column (#292 put it there). Moved back under the row,
    every rule above would still be satisfied and the layout would be wrong."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(client.get("/").get_data(as_text=True), "html.parser")
    field = soup.find(id="word-topic")
    hint = soup.find("p", class_="form-hint")

    assert hint.parent is field.parent
    assert "form-row" in hint.parent.parent.get("class", []), \
        "the column has to be a child of the row the CSS positions against"
