"""Card deck as a banner on the topic page (kuantorflow#453).

The topic page offers **Card deck** as a wide banner button, the shape and size
of the text generator's on the front page, and the link **moved** there out of
the blue activity row rather than being duplicated — one route to a place,
which is #451's reasoning for the header applied to a panel.

Three things are pinned, and each of them fails silently rather than loudly:

**The link carries the topic.** The reader's banner goes to the picker, because
it sits on the front page with no topic chosen. This one stands inside a topic
and must open *that* deck. A banner pointing at the picker still renders, still
looks right and still works — it just costs the learner the two interactions
the button exists to save.

**The image is named directly, not through `game_icon`.** `card_deck` is a
route with no entry in `games.ACTIVITIES`, so the filter answers `None` for it
and the template renders the banner **with no picture and no complaint**. That
is the failure the ticket predicted, and it is invisible in a green run.

**It is gone from the activity row.** Two doors into one room was the thing
#453 set out to fix, and a half-applied change leaves both.

What is deliberately *not* here: how the banner looks. Contrast, sizing and
crop were measured against the artwork before it was placed (worst-case label
contrast 15.11:1 over the gradient, against the reader banner's 7.40:1) and
they are properties of a picture, not of this template.
"""

import re
from pathlib import Path

import pytest


def _webp_size(path):
    """(width, height) read out of a WebP header.

    By hand because there is no Pillow in this venv and two assertions do not
    justify adding it -- the same call `test_static_images.py` makes for its
    JPEGs, and for the same reason. Three container forms exist and the two
    that matter here store the dimensions at fixed offsets.
    """
    data = Path(path).read_bytes()
    assert data[:4] == b"RIFF" and data[8:12] == b"WEBP", f"not a WebP: {path}"
    kind = data[12:16]
    if kind == b"VP8X":                      # extended
        return (int.from_bytes(data[24:27], "little") + 1,
                int.from_bytes(data[27:30], "little") + 1)
    if kind == b"VP8L":                      # lossless
        bits = int.from_bytes(data[21:25], "little")
        return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
    return (int.from_bytes(data[26:28], "little") & 0x3FFF,   # lossy
            int.from_bytes(data[28:30], "little") & 0x3FFF)


CARDS = [
    {"id": 1, "word": "verdict", "pos": "noun", "topic": "Law",
     "translation_ukr": "vyrok", "translation_rus": "prigovor",
     "explanation_en": "a jury's decision", "added_by_user_id": None},
    {"id": 2, "word": "plaintiff", "pos": "noun", "topic": "Law",
     "translation_ukr": "pozyvach", "translation_rus": "istets",
     "explanation_en": "the party bringing a case", "added_by_user_id": None},
]


@pytest.fixture()
def topic_page(client, stub_deck):
    """The topic page for a deck with cards in it."""
    def render(topic="Law"):
        stub_deck(cards=CARDS)
        r = client.get(f"/flashcards/{topic}")
        assert r.status_code == 200, f"the topic page answered {r.status_code}"
        return r.get_data(as_text=True)
    return render


def _banner(html):
    """The banner's anchor tag, on its own."""
    at = html.index("reader-banner")
    start = html.rindex("<a ", 0, at)
    return html[start:html.index("</a>", at) + 4]


# --- the banner is there, and it is the reader's shape ----------------------

def test_the_topic_page_carries_a_card_deck_banner(topic_page):
    html = topic_page()

    assert "reader-banner" in html, "no banner on the topic page"
    assert "Card deck" in html


def test_it_uses_the_reader_banners_classes(topic_page):
    """`reader-banner` is what carries `aspect-ratio: 1600 / 679` and the
    24rem width; `reader-banner--image` is what draws the left-to-right scrim
    the label sits on. Without the modifier the label has nothing behind it
    and the picture still renders, so the page looks *nearly* right."""
    tag = _banner(topic_page())

    assert "reader-banner" in tag
    assert "reader-banner--image" in tag


def test_the_label_is_html_over_the_image(topic_page):
    """The artwork carries no lettering, by design (#453, and #234 before it:
    generated type comes out mangled). So the words have to come from the
    template."""
    html = topic_page()

    assert 'class="reader-banner-label">Card deck<' in html


# --- the two things that fail silently --------------------------------------

def test_the_banner_opens_this_topics_deck(topic_page):
    """Not the picker, and not some other topic. A banner that lost the topic
    renders identically and works — it just undoes the reason for the
    button."""
    tag = _banner(topic_page())
    href = re.search(r'href="([^"]+)"', tag).group(1)

    assert href.startswith("/deck/") or "/deck" in href, href
    assert "Law" in href, f"the banner lost the topic: {href}"


def test_the_banner_actually_has_a_picture(topic_page):
    """The failure #453 predicted: `card_deck` is not in `games.ACTIVITIES`,
    so `game_icon` answers None and the `{% if banner %}` around the reader's
    `<img>` would skip it — a banner with no picture, no error and no test
    noticing. The file is named directly for that reason."""
    tag = _banner(topic_page())

    assert "<img" in tag, "the banner renders without a picture"
    src = re.search(r'src="([^"]+)"', tag).group(1)
    assert "card_deck.webp" in src, src


def test_the_picture_is_versioned_like_every_other_asset(topic_page):
    """#300. Named directly rather than through `game_icon`, which is the one
    path that already applies `static_url` — so this is exactly the call site
    where the cache-buster is easy to drop."""
    src = re.search(r'src="([^"]+)"', _banner(topic_page())).group(1)

    assert "?v=" in src, f"unversioned: {src}"


def test_the_image_is_actually_served(client, topic_page):
    """A path that resolves to nothing renders an empty banner rather than an
    error, so the URL is followed rather than pattern-matched."""
    src = re.search(r'src="([^"]+)"', _banner(topic_page())).group(1)

    assert client.get(src).status_code == 200


# --- it moved, rather than being duplicated ---------------------------------

def _crumbs(html):
    at = html.index('class="crumbs"')
    return html[at:html.index("</p>", at)]

def test_card_deck_is_gone_from_the_activity_row(topic_page):
    """The whole point of #453: one route to a place. This is also what lets
    #452 narrow the row on a phone to the back arrow alone."""
    assert "Card deck" not in _crumbs(topic_page())


def test_the_deck_link_appears_exactly_once_on_the_page(topic_page):
    """Stated over the whole page rather than the row, because "removed from
    the row" and "not duplicated" are different claims and a third copy
    somewhere else would satisfy the first."""
    html = topic_page()

    assert html.count("Card deck") == 1, (
        f"'Card deck' appears {html.count('Card deck')} times")


def test_the_rest_of_the_activity_row_survived(topic_page):
    """The row is edited by hand, so the neighbouring links are what a
    mis-drawn boundary would take with it."""
    crumbs = _crumbs(topic_page())

    assert "Home" in crumbs
    assert "Take quiz" in crumbs


# --- the artwork itself, which is content in version control ----------------

def test_the_artwork_matches_the_reader_banners_geometry(app_module):
    """Both banners render in a box with `aspect-ratio: 1600 / 679` and
    `object-fit: cover`, so a file of some other ratio is silently cropped
    from the sides — and this artwork puts a card near the right-hand frame
    edge, which is the first thing such a crop would take.

    Derived from `read_a_text.webp` rather than restated as 1600x679: the pair
    sharing a ratio is the actual requirement, and a literal here would freeze
    the number it was meant to guard.
    """
    games = Path(app_module.app.static_folder) / "img" / "games"
    deck = _webp_size(games / "card_deck.webp")
    reader = _webp_size(games / "read_a_text.webp")

    assert deck == reader, f"card_deck is {deck}, read_a_text is {reader}"


def test_the_artwork_is_no_heavier_than_its_neighbour(app_module):
    """#234 sized these against the eighteen topic icons; the banner is the
    largest asset on the page it appears on, and a 5 MB source shipped by
    mistake would still render perfectly."""
    games = Path(app_module.app.static_folder) / "img" / "games"
    deck = (games / "card_deck.webp").stat().st_size
    reader = (games / "read_a_text.webp").stat().st_size

    assert deck <= reader * 1.5, (
        f"card_deck.webp is {deck/1024:.0f} KB against "
        f"read_a_text.webp's {reader/1024:.0f} KB")
