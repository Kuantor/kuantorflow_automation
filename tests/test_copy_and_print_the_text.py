"""Taking a generated text away with you (kuantorflow#403).

Two buttons on #237's page: copy the passage with its highlighting, and print
the title and the text on a sheet of their own.

**Most of what matters here is not visible to pytest**, which is why this file
is mostly coupling assertions and says so. What a clipboard receives and what a
printer draws are both browser behaviour; what a test can hold is the shape of
the page that produces them, and the two decisions that shape it:

* the copy button lives **outside** `.reader-text`. That panel is `pre-wrap`,
  so anything inside it renders -- including the whitespace around a tag, which
  is the whole of #399. A button moved inside would put a blank line above the
  text again -- the guard for that lives in `test_generated_text.py` and is not
  restated here;
* the print rules **name nothing in base.html**. `worksheet.html` is a
  standalone page precisely because a print stylesheet that hides the header,
  the footer and the widget one at a time rots the next time the layout
  changes; these rules hide everything and bring one subtree back, so a new
  panel cannot arrive on the sheet by default.

Measured in a browser at the time, and recorded here because the numbers cannot
be: the clipboard got both `text/html` and `text/plain`, the highlighted words
came through as `<strong>` with an inline background, the paragraph break came
through as `<br><br>`, and with the print rules applied to the screen the
sheet, its title and its text were visible while the header, the crumbs, the
summary panel and the write form were hidden.
"""

import re

import pytest

import textgen


CARDS = [
    {"id": 1, "word": "empirical", "pos": "adjective", "topic": "Study",
     "explanation_en": "based on observation"},
    {"id": 2, "word": "hypothesis", "pos": "noun", "topic": "Study",
     "explanation_en": "an idea to be tested"},
]

PASSAGE = ("An empirical study begins with a question.\n\n"
           "The hypothesis came later.")

PLAY = "/games/read_a_text/play?topic=Study"


@pytest.fixture()
def deck(stub_deck):
    return stub_deck(cards=CARDS)


@pytest.fixture(autouse=True)
def claude(monkeypatch):
    monkeypatch.setattr(textgen, "_ask_claude", lambda prompt, length: PASSAGE)


def _text(client):
    """A page with a text on it, reached the way a learner reaches one."""
    return client.post(PLAY, data={}, follow_redirects=True).get_data(as_text=True)


def _panel(body):
    found = re.search(r'<div class="panel reader-text">(.*?)</div>', body, re.S)
    return found.group(1) if found else ""


# --- the copy button --------------------------------------------------------

def test_the_text_has_a_copy_button(client, deck):
    body = _text(client)

    assert 'id="reader-copy"' in body
    assert 'aria-label="Copy the text"' in body, (
        "icon-only, so the name has to come from the attribute")


def test_it_sits_outside_the_panel_it_copies(client, deck):
    """#399's lesson, and the reason the wrapper exists. `.reader-text` is
    `pre-wrap`: a button inside it would be surrounded by newlines and
    indentation, and every one of those characters is drawn."""
    body = _text(client)

    assert 'id="reader-copy"' not in _panel(body)
    assert 'class="reader-sheet"' in body, "the wrapper it is positioned in"


def test_the_clipboard_gets_both_flavours(client, deck):
    """The payload is where this differs from Mykola's button (#245), which
    copies plain text on purpose. Here the highlighting is the feature, so the
    page writes `text/html` beside `text/plain` -- and the HTML carries inline
    styles, since nothing on the other end has our stylesheet."""
    body = _text(client)

    assert '"text/html"' in body and '"text/plain"' in body
    assert "ClipboardItem" in body
    assert "font-weight:700;background:" in body, (
        "a class name would arrive meaningless in Word")


def test_it_has_something_to_fall_back_on(client, deck):
    """A selection copy carries the rendered formatting where the async
    clipboard is unavailable, and plain text is better than failing."""
    body = _text(client)

    assert 'execCommand("copy")' in body
    assert "writeText" in body


# --- printing ---------------------------------------------------------------

def test_there_is_a_print_button(client, deck):
    body = _text(client)

    assert "window.print()" in body
    assert "Print the text" in body


def test_the_print_rules_name_nothing_from_the_site_layout(client, deck):
    """The whole reason `worksheet.html` is a standalone page. A stylesheet
    that hides the header, the footer and the widget by name rots the next time
    the layout changes; this one hides everything and brings the sheet back, so
    a panel added tomorrow is off the sheet by default."""
    body = _text(client)
    printed = re.search(r"@media print \{(.*?)\n        \}", body, re.S)

    assert printed, "the page has no print rules"
    rules = printed.group(1)
    assert "body * { visibility: hidden; }" in rules
    assert ".reader-sheet, .reader-sheet * { visibility: visible; }" in rules
    for chrome in ("header", "footer", "mykola", ".crumbs", ".reader-words",
                   ".reader-form"):
        assert chrome not in rules, f"{chrome} is named in the print rules"


def test_the_highlight_prints_two_ways(client, deck):
    """Bold for the monochrome office printer #340's stylesheet worries about,
    and `print-color-adjust` so a colour one does not drop the background it
    could have drawn."""
    body = _text(client)
    printed = re.search(r"@media print \{(.*?)\n        \}", body, re.S).group(1)

    assert "font-weight: 700" in printed
    assert "print-color-adjust: exact" in printed


def test_the_buttons_are_not_on_the_sheet(client, deck):
    body = _text(client)
    printed = re.search(r"@media print \{(.*?)\n        \}", body, re.S).group(1)

    assert ".reader-copy" in printed and "display: none" in printed


# --- and the worksheet is still the other thing you can do ------------------

def test_the_worksheet_link_is_untouched(client, deck):
    """#340 makes a gap-fill exercise out of the same text; this ticket adds
    printing the text *as it is*. Two different things to do with one passage,
    and the new button must not have replaced the old link."""
    body = _text(client)

    assert "Make a printable gap-fill worksheet" in body
    assert "/games/read_a_text/worksheet" in body
