"""A scroll region leaves room for a focus ring (kuantorflow#370).

`.modal-scroll` had `padding-right: 0.4rem` for the scroll bar and nothing on
the left. Two facts turn that into a visible defect:

* `overflow-y: auto` cannot be one-directional — when either axis is not
  `visible` the other computes to `auto` as well, so the box clips
  horizontally too, at its **padding** edge;
* an outline is painted *outside* the border box, so the 2px focus ring on a
  `width: 100%` field lands 2px beyond the content on each side.

With no padding on the left the ring was sliced off flat down the whole edit
dialog, while the right kept its rounded corner on the scroll bar's gutter.
Measured before the fix: **0px of room on the left against the 2px the ring
needs**, on all five fields measured (the word, the part of speech, the
explanation, a translation and an examples box).

Neither of those facts is visible to a markup assertion, and a clipped outline
is not visible to one either — so what is pinned here is the declaration that
keeps the room, and the measurement lives in the docstrings.
"""

import re

import pytest


RING_PX = 2          # `input[type="text"]:focus { outline: 2px solid ... }`
GUTTER = "0.4rem"    # 6.4px, comfortably more than the ring needs


def _declarations(css, selector):
    """Every declaration of one rule, whitespace-collapsed."""
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for match in re.finditer(r"([^{}@]+?)\{([^{}]*?)\}", stripped, re.S):
        names = [n.strip() for n in match.group(1).split(",")]
        if selector in names:
            return " ".join(match.group(2).split())
    return None


@pytest.fixture()
def css(client):
    return client.get("/static/css/style.css").get_data(as_text=True)


def test_the_scroll_region_has_room_on_both_sides(css):
    """The fix, and the reason it is on `.modal-scroll` rather than on the
    edit dialog: any focusable element that is a **direct child** of a scroll
    region has this problem, and the edit dialog is only the first to have
    one. The review popup's textareas escape it by sitting inside
    `.proposal-card`, which has padding of its own — luck rather than design.
    """
    rule = _declarations(css, ".modal-scroll")

    assert rule, ".modal-scroll has no rule at all"
    assert "padding-left: %s" % GUTTER in rule
    assert "padding-right: %s" % GUTTER in rule


def test_the_gutter_is_wider_than_the_ring(css):
    """Both numbers read from the stylesheet, not one of them from here.

    The first version compared the gutter against `RING_PX`, a constant in
    this file — so growing the *ring* to 12px against a 6.4px gutter left it
    passing, which is the arrangement it exists to forbid. A deliberate break
    proved that by failing only the test below. Read both and the invariant is
    the real one: whatever the ring is, the room is at least that.
    """
    gutters = re.findall(r"padding-(?:left|right): ([\d.]+)rem",
                         _declarations(css, ".modal-scroll"))
    ring = re.search(r"outline: ([\d.]+)px",
                     _declarations(css, 'input[type="text"]:focus'))

    assert len(gutters) == 2, "both sides are set explicitly"
    assert ring, "the ring's own width is declared"
    for gutter in gutters:
        assert float(gutter) * 16 >= float(ring.group(1)), (
            "%srem of room is less than the %spx ring it has to show"
            % (gutter, ring.group(1)))


def test_the_ring_itself_is_still_two_pixels(css):
    """The app's own ring, which is a global rule rather than the edit
    dialog's — `input[type="text"]:focus`, so every text field in the site
    gets it and any of them dropped into a scroll region would have had the
    same defect.

    If this grows, the gutter above has to grow with it, which is why the two
    are asserted in one file. The dialog's *textareas* take the browser's own
    focus ring instead, and its width is the browser's business and varies —
    a second reason the gutter is 6.4px rather than exactly the 2px this rule
    asks for.
    """
    rule = _declarations(css, 'input[type="text"]:focus')

    assert rule and "outline: %dpx" % RING_PX in rule


def test_the_scroll_bar_gutter_survives(css):
    """The right-hand padding predates #370 and was doing a second job by
    accident. It still has its first one: keeping the scroll bar off the
    content. Measured with the dialog scrolling at 1280x460 — a 15px scroll
    bar, and 6.7px still clear between it and the focused field's ring.
    """
    rule = _declarations(css, ".modal-scroll")

    assert "overflow-y: auto" in rule
    assert "padding-right" in rule


def test_the_review_popup_shares_the_class_and_is_unharmed(client, app_module,
                                                           monkeypatch, saved):
    """The one thing that could have been broken by fixing this elsewhere.

    `.proposal-cards-pane` is a `.modal-scroll` too, so its cards became 6.4px
    narrower and symmetric. Measured at 1280x800: the cards stay inside the
    pane, the pane inside the dialog, the dialog inside the viewport, and
    nothing scrolls sideways.
    """
    monkeypatch.setattr(app_module, "lookup_word",
                        lambda word, topic=None, **kw: [
                            {"word": word, "pos": "noun", "topic": topic,
                             "explanation_en": "a definition",
                             "examples_en": ["An example."],
                             "translation_ukr": "переклад"}])
    body = client.post("/", data={"action": "parse_word", "word": "x",
                                  "topic": "T"}).get_data(as_text=True)

    assert 'class="modal-scroll proposal-cards-pane"' in body
