"""The edit-card popup's width and the room in its fields (kuantorflow#227),
and the caption that was said twice (kuantorflow#208).

#227's finding is the interesting one and it is why this file asserts a
*selector* rather than a number: `.edit-dialog` had asked for 560px since it
was written and rendered at 420, because `.modal-dialog` sets the same property
at the same specificity 700 lines later and won on file order alone. Raising
560 to 700 would have changed nothing — which is the trap, since the diff would
have looked exactly like a fix.

So what has to hold is that the rule can *win*, and the repo already had one
answer for that: `.proposal-dialog.proposal-dialog--source` carries the same
doubled class for the same reason.

The rendered result was measured in a browser: 700px wide at a 1024px viewport
with the textarea at 615px, and 345px at 375px wide with nothing overflowing.
"""

import re

import pytest


@pytest.fixture()
def css(app_module):
    from pathlib import Path
    return Path(app_module.app.static_folder, "css", "style.css").read_text(
        encoding="utf-8")


@pytest.fixture(autouse=True)
def deck(stub_deck):
    return stub_deck(cards=[])


# --- #227 -----------------------------------------------------------------

def test_the_edit_dialog_can_out_specify_the_shared_dialog(css):
    """The whole of the fix. A single `.edit-dialog` rule ties with
    `.modal-dialog` and loses on order, silently."""
    assert ".edit-dialog.edit-dialog" in css


def test_no_lone_edit_dialog_rule_sets_a_width_that_cannot_win(css):
    """The regression that would undo this without looking like it: somebody
    adds `.edit-dialog { max-width: … }` back, it ties with `.modal-dialog`
    again, and the dialog quietly returns to 420px."""
    for block in re.findall(r"(?:^|[,}*/])\s*\.edit-dialog\s*\{([^}]*)\}", css,
                            re.MULTILINE):
        assert "width" not in block, \
            "a single-class .edit-dialog rule cannot win against .modal-dialog"


def test_the_dialog_is_still_clamped_to_the_viewport(css):
    """A phone must not be given a 700px dialog. `min()` is what keeps the
    width honest, and dropping it is the easy half of this to get wrong."""
    rule = re.search(r"\.edit-dialog\.edit-dialog\s*\{([^}]*)\}", css).group(1)
    assert "min(" in rule and "vw" in rule


@pytest.mark.parametrize("field", ["explanation_en", "examples_en"])
def test_the_english_fields_have_room_for_what_arrives_in_them(client, field):
    """#225 made these the two that overflow: an explanation can carry three
    senses joined with `; `, and examples arrive as up to three lines."""
    body = client.get("/flashcards/Work").get_data(as_text=True)
    box = re.search(rf'<textarea id="edit-{field}"[^>]*>', body)
    assert box, f"no {field} box on the edit form"
    assert int(re.search(r'rows="(\d+)"', box.group(0)).group(1)) >= 4


# --- #208 -----------------------------------------------------------------

def test_the_greeting_is_in_the_header(client):
    assert "Welcome to Kuantor" in client.get("/").get_data(as_text=True)


def test_the_greeting_is_not_also_a_caption_above_the_first_panel(client):
    """It was said twice on the front page: once in the header and once as a
    page title directly above *Browse flashcards*.

    Asserted against the heading rather than by counting the phrase, because
    the welcome popup's image carries it as alt text -- which is a description
    of a picture, not a caption on the page.
    """
    body = client.get("/").get_data(as_text=True)
    assert 'class="page-title"' not in body
    assert body.index("Welcome to Kuantor") < body.index("Browse flashcards")
