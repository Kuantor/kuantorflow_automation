"""The review popup shows a card's examples (kuantorflow#357).

The popup is the one panel whose whole job is looking at a card *before* it is
written, and it drew every field except the examples: those travelled as hidden
JSON, saved with the card and shown to nobody. kuantorflow#349 made the gap
plain, promising "their English explanation and examples" beside a card that
displayed none.

They are textareas now, one example per line, in the edit dialog's field order.
Three rules are pinned here because each of them is a way the fix could have
gone wrong:

* **a language hidden in Settings is still saved** (kuantorflow#46/#79/#111).
  It renders no textarea and keeps the hidden JSON input, so the card is
  written complete — the same contract its translation has always had;
* **a card with no examples grows no empty box.** This panel reviews what the
  lookup found; an empty textarea invites inventing sentences instead;
* **both shapes still reach the database.** `add_card()` read JSON only, so
  the moment the field became a textarea its lines would have parsed as
  nothing and the examples would have been dropped on save — silently, since
  a missing examples column is not an error.

The round trip at the end is the one that would have caught that: it renders
the popup, reads the textarea out of the real page, and posts it back.

Everything is stubbed: no network, no database.
"""

import json
import re

import pytest


EXAMPLES_EN = ["She takes it for granted that we will help.",
               "I took his kindness for granted."]
EXAMPLES_UKR = ["Вона сприймає це як належне."]
EXAMPLES_RUS = ["Он принимает это как должное."]

CARD = {
    "word": "take for granted",
    "pos": "phrasal verb",
    "explanation_en": "to be so used to something that you no longer value it",
    "translation_ukr": "сприймати як належне",
    "translation_rus": "принимать как должное",
    "examples_en": EXAMPLES_EN,
    "examples_ukr": EXAMPLES_UKR,
    "examples_rus": EXAMPLES_RUS,
}


def _textarea(body, name):
    """The content of the popup's `name` textarea, or None if it has none."""
    found = re.search(r'<textarea name="%s"[^>]*>(.*?)</textarea>' % name,
                      body, re.S)
    return found.group(1) if found else None


def _hidden(body, name):
    return re.search(r'<input type="hidden" name="%s" value="([^"]*)"' % name,
                     body)


def _lookup(client, app_module, monkeypatch, **overrides):
    card = dict(CARD, **overrides)
    monkeypatch.setattr(
        app_module, "lookup_word",
        lambda word, topic=None, **providers: [dict(card, topic=topic)])
    return client.post("/", data={"action": "parse_word",
                                  "word": card["word"],
                                  "topic": "Character"}).get_data(as_text=True)


# --- what the popup draws ---------------------------------------------------

def test_the_popup_shows_the_english_examples(client, app_module, monkeypatch,
                                              saved):
    body = _lookup(client, app_module, monkeypatch)

    assert 'id="proposal-modal"' in body
    assert _textarea(body, "examples_en") == "\n".join(EXAMPLES_EN)
    assert "English examples" in body
    assert saved == [], "rendering the popup saves nothing"


def test_the_examples_are_no_longer_hidden(client, app_module, monkeypatch,
                                           saved):
    """The point of the ticket: they were in the form all along."""
    body = _lookup(client, app_module, monkeypatch)

    assert _hidden(body, "examples_en") is None


def test_both_languages_get_their_examples(client, app_module, monkeypatch,
                                           saved):
    body = _lookup(client, app_module, monkeypatch)

    assert _textarea(body, "examples_ukr") == "\n".join(EXAMPLES_UKR)
    assert _textarea(body, "examples_rus") == "\n".join(EXAMPLES_RUS)


def test_a_card_with_no_examples_gets_no_box(client, app_module, monkeypatch,
                                             saved):
    body = _lookup(client, app_module, monkeypatch,
                   examples_en=[], examples_ukr=[], examples_rus=[])

    assert 'class="proposal-card"' in body, "the card itself is still offered"
    assert _textarea(body, "examples_en") is None
    assert "English examples" not in body


def test_a_hidden_language_is_not_drawn_but_is_still_saved(
        user_client, app_module, monkeypatch, saved):
    """#46/#79/#111. The examples follow their translation exactly."""
    user_client.post("/settings", json={"show_russian": False})
    body = _lookup(user_client, app_module, monkeypatch)

    assert _textarea(body, "examples_rus") is None
    assert "Russian examples" not in body
    carried = _hidden(body, "examples_rus")
    assert carried, "a hidden language's examples must still reach the save"
    assert _textarea(body, "examples_ukr") == "\n".join(EXAMPLES_UKR)


# --- what reaches the database ---------------------------------------------

def test_examples_typed_one_per_line_are_saved(user_client, saved):
    r = user_client.post("/cards/add", data={
        "word": "resilient", "pos": "adjective", "topic": "character",
        "examples_en": "\n".join(EXAMPLES_EN),
    })

    assert r.status_code == 200 and r.get_json()["saved"] is True
    assert saved[0]["examples_en"] == EXAMPLES_EN


def test_the_hidden_json_shape_still_saves(user_client, saved):
    """The shape a hidden language still submits, and every older client."""
    user_client.post("/cards/add", data={
        "word": "resilient", "pos": "adjective", "topic": "character",
        "examples_rus": json.dumps(EXAMPLES_RUS),
    })

    assert saved[0]["examples_rus"] == EXAMPLES_RUS


def test_blank_lines_are_not_examples(user_client, saved):
    user_client.post("/cards/add", data={
        "word": "resilient", "pos": "adjective",
        "examples_en": "  \n%s\n\n   \n" % EXAMPLES_EN[0],
    })

    assert saved[0]["examples_en"] == [EXAMPLES_EN[0]]


def test_an_emptied_box_saves_no_examples(user_client, saved):
    """Clearing the field is how a learner drops an example they dislike."""
    user_client.post("/cards/add", data={
        "word": "resilient", "pos": "adjective", "examples_en": "   "})

    assert saved[0]["examples_en"] is None


# --- the round trip ---------------------------------------------------------

def test_what_the_popup_shows_is_what_gets_saved(user_client, app_module,
                                                 monkeypatch, saved):
    """Render the popup, take the textarea out of the page, post it back.

    Neither half of the fix is worth anything alone: a rendered textarea whose
    lines `add_card()` cannot read loses the examples it just showed, which is
    a worse bug than not showing them at all.
    """
    body = _lookup(user_client, app_module, monkeypatch)
    shown = _textarea(body, "examples_en")

    user_client.post("/cards/add", data={
        "word": CARD["word"], "pos": CARD["pos"], "topic": "Character",
        "examples_en": shown,
    })

    assert saved[0]["examples_en"] == EXAMPLES_EN


def test_an_edited_example_is_saved_as_edited(user_client, saved):
    """The reason the field is editable rather than a read-only list."""
    user_client.post("/cards/add", data={
        "word": CARD["word"], "pos": CARD["pos"],
        "examples_en": "I took his kindness for granted.",
    })

    assert saved[0]["examples_en"] == ["I took his kindness for granted."]


# --- and it must not break the popup it lives in ---------------------------

def test_the_examples_fields_are_inside_the_scrolling_pane(
        client, app_module, monkeypatch, saved):
    """The lesson kuantorflow#349 paid for, and the reason this can be three
    new fields per card without measuring anything.

    The dialog's height is capped and the cards pane is what scrolls, so
    anything added *inside* the pane costs the layout nothing however long a
    card's examples run. Anything added beside it pushes cards out of the
    popup's bottom edge, which is exactly how #349's notice first shipped.
    """
    body = _lookup(client, app_module, monkeypatch)
    pane_opens = body.index('class="modal-scroll proposal-cards-pane"')
    card_opens = body.index('class="proposal-card"', pane_opens)
    examples = body.index('name="examples_en"', card_opens)
    add_button = body.index('class="add-btn"', card_opens)

    assert pane_opens < card_opens < examples < add_button


def test_the_examples_boxes_are_styled_like_the_explanation_box(client):
    """`.proposal-card textarea` is why these arrive dressed rather than as a
    raw browser default, and it is the rule the explanation box already used —
    so the two are one field type, not a matched pair somebody has to keep in
    step."""
    import re
    css = client.get("/static/css/style.css").get_data(as_text=True)
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rules = [m.group(1) for m in re.finditer(r"([^{}@]+?)\{([^{}]*?)\}",
                                             stripped, re.S)]
    assert any(".proposal-card textarea" in [n.strip() for n in r.split(",")]
               for r in rules)


# --- the box is the size of what is in it -----------------------------------

import pytest


@pytest.mark.parametrize("count,rows", [(1, 2), (2, 4), (3, 6), (5, 6)])
def test_rows_are_measured_from_the_number_of_examples(
        client, app_module, monkeypatch, saved, count, rows):
    """Two rows per example, capped at six.

    Measured rather than picked: at the popup's 300px field width an Oxford
    example wraps to about two lines, and a box that shows half its contents
    and scrolls for the rest is barely better than the hidden input it
    replaced. The cap is `parsers.MAX_EXAMPLES`, doubled.

    This is the floor a page without JavaScript keeps; the script below fits
    the box to its actual content at the width it is actually being read.
    """
    body = _lookup(client, app_module, monkeypatch,
                   examples_en=["An example sentence." for _ in range(count)])

    # Read off the tag rather than matched as one string: kuantorflow#372 put
    # an `id` between the two attributes so the popup's labels could be
    # associated with their fields, and the guarantee here is the row count,
    # not which attribute sits next to which.
    tag = re.search(r'<textarea[^>]*name="examples_en"[^>]*>', body).group(0)
    assert 'rows="%d"' % rows in tag


def test_the_popup_fits_its_boxes_to_their_content(client, app_module,
                                                   monkeypatch, saved):
    """The script, pinned by its parts, because pytest renders no layout.

    Measured in a browser at 1280x720 and 375x812: every examples box holds
    all of its examples with nothing clipped and no scrollbar, the dialog
    stays inside the viewport, the cards pane keeps scrolling inside the
    dialog, and typing a fourth example grows its box from 142px to 186px.

    The `ResizeObserver` is the part that is easy to think unnecessary and is
    not: a box fitted before the layout settles is fitted to a width it never
    really had, and stood 2,935px tall in exactly that case — a window resize
    listener alone never fired, because the window had not changed.
    """
    body = _lookup(client, app_module, monkeypatch)
    script = body[body.index('id="proposal-modal"'):]

    assert "function fitBox(" in script
    assert 'box.style.overflowY = "hidden"' in script, "measured without a scrollbar"
    assert "ResizeObserver" in script
    assert 'addEventListener("input"' in script, "and again as it is typed in"
