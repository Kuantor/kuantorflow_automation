"""The header's links are boxes you can hit (kuantorflow#502, item 2).

*Home*, *Settings*, *About* and *Help* were 20px lines of text spaced by a
margin; guidance for a finger is 44px (Apple, Google; WCAG 2.2's floor is
24px). Each is now a 44px box, the gaps between the words are its padding, and
the header's own padding halved so it stays the height it was on a desktop
(57 -> 58px, measured). On a phone the two wrapped rows make it 85 -> 102px,
which item 5 (the one-line wordmark) revisits.
"""

import re


def _css(client):
    return client.get("/static/css/style.css").get_data(as_text=True)


def _declarations(css, selector):
    """Every declaration written for exactly `selector`, later ones winning."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    found = {}
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if selector not in [s.strip() for s in selectors.split(",")]:
            continue
        for prop, value in re.findall(r"([\w-]+)\s*:\s*([^;]+)", body):
            found[prop.strip()] = value.strip()
    return found


def _px(value):
    number = float(re.match(r"[\d.]+", value).group())
    return number * 16 if value.endswith("rem") else number


def test_each_header_link_is_a_44px_box(client):
    link = _declarations(_css(client), ".site-header nav a")
    # `min-height` does nothing to an inline element, which is what an <a>
    # is unless told otherwise -- so the display is half of the rule.
    assert link.get("display") in {"inline-flex", "flex", "inline-block", "block"}, link
    assert _px(link["min-height"]) >= 44, link["min-height"]
    assert "padding" in link and "margin-left" not in link, \
        "the space between the words should be part of the targets"


def test_a_keyboard_user_can_see_the_focused_link(client):
    assert "outline" in _declarations(_css(client), ".site-header nav a:focus-visible")


def test_the_header_does_not_grow_on_a_desktop(client):
    """The links' boxes make the height now, so the header's own vertical
    padding must shrink with them (0.9rem -> 0.45rem)."""
    padding = _declarations(_css(client), ".site-header")["padding"].split()[0]
    assert _px(padding) <= 8, padding


def test_the_four_links_are_all_there(client):
    body = client.get("/").get_data(as_text=True)
    nav = re.search(r'<header class="site-header">.*?<nav>(.*?)</nav>', body, re.S).group(1)
    assert [re.sub(r"\s+", " ", t).strip() for t in re.findall(r">([^<]+)</a>", nav)] == \
        ["Home", "Settings", "About", "Help"]
