"""A one-line wordmark, and no Home link on a phone (kuantorflow#502, item 5).

The header's brand was the greeting "Welcome to KuantorFlow", which wrapped
onto two lines on a phone. It is the wordmark now -- and, as on every site,
the way home -- so on a phone the Home link goes and Settings, About and Help
fit one row beside it.

Measured in the PR: the phone header 102px (two rows of 44px links, item 2)
-> 58px, one row, at both 375px and 320px; desktop unchanged at 58px with all
four links.
"""

import re


def _css(client):
    css = client.get("/static/css/style.css").get_data(as_text=True)
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _brand(body):
    return re.search(r'<a class="brand"[^>]*>(.*?)</a>', body, re.S)


def test_the_header_says_the_name_not_a_greeting(client):
    brand = _brand(client.get("/").get_data(as_text=True))
    assert brand, "no brand in the header"
    text = re.sub(r"<[^>]+>", "", brand.group(1)).strip()
    assert text == "KuantorFlow", text


def test_the_wordmark_says_where_it_goes(client):
    """A screen reader hears "KuantorFlow, home", since on a phone it is the
    only way home in the header."""
    brand = _brand(client.get("/").get_data(as_text=True)).group(0)
    assert 'href="/"' in brand
    assert re.search(r'aria-label="[^"]*home', brand, re.I), brand


def test_home_goes_on_a_phone_and_stays_on_a_desktop(client):
    css = _css(client)
    hides_home = [block for block in re.findall(r"@media\s*\(max-width:\s*(\d+)px\)\s*\{((?:[^{}]*\{[^{}]*\})*[^{}]*)\}", css)
                  if re.search(r"\.nav-home\s*\{[^}]*display\s*:\s*none", block[1])]
    assert hides_home, "nothing hides Home on a phone"
    assert all(int(width) <= 640 for width, _ in hides_home), \
        "Home must stay where there is room for it"
    body = client.get("/").get_data(as_text=True)
    assert re.search(r'<a class="nav-home" href="/">Home</a>', body)
