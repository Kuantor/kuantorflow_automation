"""*Edit the card* on a phone: two rows of one-line buttons, and textareas in
the site's own box (kuantorflow#580).

The dialog's three buttons shared one row, `.modal-actions` (flex,
`justify-content: flex-end`), at the site's 25.6px side padding. A phone's
~320px row cannot hold them: *Look up & update* broke onto three lines (72px
tall) and *Save changes* spilled 17px past the dialog's left margin -- the
flex-end spill #238 met in Settings. On a phone they are now a two-column grid:
*Look up & update* across the top, *Save changes* | *Cancel* below, every label
on one line. At every width the row has 1rem above it, where it had none.

The textareas (explanation, examples) had no style in this dialog at all, so
they rendered in the browser's default monospace at 13px beside rounded 16px
text inputs. They now inherit the site's font, in the inputs' box.

Resolved through the stylesheet's cascade (`conftest.css_winning`); the
layout was measured in a real browser at 320, 375 and 412px for the PR.
"""

import pytest

from conftest import css_winning

DIALOG = {"modal", "modal-dialog", "edit-dialog"}
ROW = [DIALOG, {"modal-actions"}]
SAVE = ROW + [{"#edit-save"}]
LOOKUP = ROW + [{"secondary", "#edit-lookup"}]
CANCEL = ROW + [{"secondary", "#edit-cancel"}]

BUTTONS = pytest.mark.parametrize("button", [SAVE, LOOKUP, CANCEL],
                                  ids=["save", "look-up", "cancel"])


@pytest.fixture()
def css(app_module):
    from pathlib import Path
    return (Path(app_module.__file__).parent / "static" / "css" / "style.css") \
        .read_text(encoding="utf-8")


# --- the buttons ------------------------------------------------------------

def test_on_a_phone_the_row_is_a_two_column_grid(css):
    assert css_winning(css, ROW, "display", phone=True) == "grid"
    assert css_winning(css, ROW, "grid-template-columns", phone=True) == "1fr 1fr"


def test_on_a_phone_look_up_spans_the_top_row(css):
    assert css_winning(css, LOOKUP, "grid-row", phone=True) == "1"
    assert css_winning(css, LOOKUP, "grid-column", phone=True) == "1 / -1"


def test_on_a_phone_save_and_cancel_share_the_second_row_save_first(css):
    assert css_winning(css, SAVE, "grid-row", phone=True) == "2"
    assert css_winning(css, CANCEL, "grid-row", phone=True) == "2"
    assert css_winning(css, SAVE, "grid-column", phone=True) == "1"
    assert css_winning(css, CANCEL, "grid-column", phone=True) == "2"


@BUTTONS
def test_on_a_phone_every_label_stays_on_one_line(css, button):
    assert css_winning(css, button, "white-space", phone=True) == "nowrap"
    assert css_winning(css, button, "padding-inline", phone=True) == "0.8rem"


@BUTTONS
def test_a_computer_keeps_the_one_row(css, button):
    assert css_winning(css, ROW, "display", phone=False) == "flex"
    assert css_winning(css, button, "grid-row", phone=False) is None
    assert css_winning(css, button, "white-space", phone=False) is None


@pytest.mark.parametrize("phone", [False, True], ids=["computer", "phone"])
def test_the_row_has_room_above_it(css, phone):
    """It sat directly on the scrolling fields' bottom edge -- measured 0px at
    1280px, Anton's report on the PR -- so the buttons looked glued to it."""
    assert css_winning(css, ROW, "margin-top", phone=phone) == "1rem"


@pytest.mark.parametrize("phone", [False, True], ids=["computer", "phone"])
def test_a_hairline_marks_where_the_scrolling_stops(css, phone):
    """A field cut off mid-line above the buttons read as a glitch rather than
    as "more below" (Anton, on kuantorflow#581). One thin solid line."""
    line = css_winning(css, ROW, "border-top", phone=phone)
    assert line and line.split()[:2] == ["1px", "solid"]
    assert css_winning(css, ROW, "padding-top", phone=phone)


def test_the_hairline_is_seeable_but_quieter_than_a_field(css):
    """Darker than the site's usual divider, which is barely there over a white
    dialog, and lighter than a field's border, so it does not compete with the
    fields. Both bounds are read from the stylesheet, not restated here."""
    import re
    from collections import Counter

    def brightness(hex_colour):
        return sum(int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))

    line = css_winning(css, ROW, "border-top", phone=False).split()[2]
    dividers = Counter(re.findall(r"border-top:\s*1px solid (#[0-9a-fA-F]{6})", css))
    usual_divider = dividers.most_common(1)[0][0]
    field = _rules_for(css, 'input[type="text"]')["border"].split()[2]

    assert brightness(field) < brightness(line) < brightness(usual_divider)


def test_on_a_computer_look_up_stands_apart_at_the_left_edge(css):
    """It fills the fields and keeps the dialog open, where Save and Cancel
    close it, so it sits apart from that pair (Anton, on kuantorflow#581)."""
    assert css_winning(css, LOOKUP, "margin-right", phone=False) == "auto"


def test_on_a_phone_look_up_still_fills_its_row(css):
    """`auto` in a grid cell would shrink the button to its text and pin it
    left; the phone rule takes it back."""
    assert css_winning(css, LOOKUP, "margin-right", phone=True) == "0"


def test_look_up_comes_first_in_the_page_so_tab_reaches_it_first(
        user_client, stub_deck):
    """Placed first by order rather than by CSS `order`, which would leave the
    keyboard visiting the buttons in a different order from the eye. Enter in
    a field still saves: Save is the form's only submit button (checked in a
    browser, the submit event's submitter is #edit-save)."""
    stub_deck(cards=[{"id": 1, "word": "abstract", "pos": "noun",
                      "topic": "Work", "user_id": 1}])
    body = user_client.get("/flashcards/Work").get_data(as_text=True)

    positions = [body.index(f'id="{b}"') for b in
                 ("edit-lookup", "edit-save", "edit-cancel")]
    assert positions == sorted(positions)
    assert body.count('form="edit-form"') == 1


# --- the textareas ----------------------------------------------------------

def test_the_textareas_inherit_the_site_font(css):
    """Not the browser's monospace: `font-family: inherit`, at the inputs'
    1rem."""
    rule = _rules_for(css, ".edit-fields textarea")
    assert rule.get("font-family") == "inherit"
    assert rule.get("font-size") == "1rem"


def test_the_textareas_have_the_inputs_box(css):
    rule = _rules_for(css, ".edit-fields textarea")
    assert rule.get("border-radius") == "8px"
    assert rule.get("border") == "1px solid #c5d0da"


def _rules_for(css, selector):
    """Every declaration of the top-level rules whose selector list holds
    exactly `selector`, later ones winning -- a type selector is outside what
    `css_winning` resolves, and nothing else styles these textareas."""
    from conftest import css_rules
    out = {}
    for media, selectors, decls in css_rules(css):
        if media is None and selector in [s.strip() for s in selectors.split(",")]:
            out.update((k.strip(), v.strip()) for k, v in
                       (d.split(":", 1) for d in decls.split(";") if ":" in d))
    return out
