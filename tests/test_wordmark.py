"""The header's caption: the greeting on a laptop, the wordmark on a phone
(kuantorflow#502, item 5).

"Welcome to KuantorFlow" wrapped onto two lines on a phone. There it is the
wordmark alone -- and, as on every site, the way home -- so the Home link goes
and Settings, About and Help fit one row. On wider screens the greeting stays,
as Anton asked after seeing the wordmark everywhere.

Measured in the PR: the header is 58px at 1280, 700 and 375px, links in one
row at each; the phone header had been 102px (two rows of 44px links).
"""

import re


def _css(client):
    css = client.get("/static/css/style.css").get_data(as_text=True)
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _brand(body):
    return re.search(r'<a class="brand"[^>]*>(.*?)</a>', body, re.S)


def test_the_header_greets_on_a_laptop(client):
    brand = _brand(client.get("/").get_data(as_text=True))
    assert brand, "no brand in the header"
    text = re.sub(r"<[^>]+>", "", brand.group(1)).strip()
    assert text == "Welcome to KuantorFlow", text
    assert '<span class="brand-greeting">Welcome to </span>' in brand.group(1)


def test_a_phone_shows_only_the_wordmark(client):
    """The greeting is hidden at phone widths only, and it is not yellow --
    only "Flow" is."""
    css = _css(client)
    hides = [width for width, block in re.findall(
                 r"@media\s*\(max-width:\s*(\d+)px\)\s*\{((?:[^{}]*\{[^{}]*\})*[^{}]*)\}", css)
             if re.search(r"\.brand-greeting\s*\{[^}]*display\s*:\s*none", block)]
    assert hides and all(int(w) <= 640 for w in hides), hides
    assert re.search(r"\.brand \.brand-greeting\s*\{[^}]*color\s*:\s*inherit", css)


def test_the_live_sites_marker_is_unchanged(client):
    """`test_live_site.py` looks for exactly this; the greeting's span must
    not change it."""
    assert "Kuantor<span>Flow</span>" in client.get("/").get_data(as_text=True)


def test_the_wordmark_says_where_it_goes(client):
    """It says it goes home -- on a phone it is the only way home in the
    header -- and its name holds the whole greeting, so it contains the visible
    text at either width (WCAG 2.5.3: a speech user says what they see)."""
    brand = _brand(client.get("/").get_data(as_text=True)).group(0)
    assert 'href="/"' in brand
    label = re.search(r'aria-label="([^"]*)"', brand).group(1)
    assert "home" in label.lower() and "Welcome to KuantorFlow" in label, label


def test_home_goes_on_a_phone_and_stays_on_a_desktop(client):
    css = _css(client)
    hides_home = [block for block in re.findall(r"@media\s*\(max-width:\s*(\d+)px\)\s*\{((?:[^{}]*\{[^{}]*\})*[^{}]*)\}", css)
                  if re.search(r"\.nav-home\s*\{[^}]*display\s*:\s*none", block[1])]
    assert hides_home, "nothing hides Home on a phone"
    assert all(int(width) <= 640 for width, _ in hides_home), \
        "Home must stay where there is room for it"
    body = client.get("/").get_data(as_text=True)
    assert re.search(r'<a class="nav-home" href="/">Home</a>', body)
