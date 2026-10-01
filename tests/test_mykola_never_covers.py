"""Ask Mykola never covers the page (kuantorflow#502, item 4).

The launcher and the minimized bar are fixed to the bottom-right, so on a phone
the last thing on a page -- a game's final answer, *Check answers*, the footer
-- sat underneath them with no way to scroll it out. Two fixes:

* **Room at the bottom of the page** while either is on screen, as tall as what
  covers it plus a gap. Measured at 375px: the launcher covers the bottom 66px
  (5rem = 80px given), the minimized bar 86px (6.5rem = 104px). Scrolled to
  the end, the footer now ends above both.
* **Minimizing hides #495's recap row.** It was left out of the minimized
  panel's hide list when the row was added, so the bar kept a second row and
  covered twice as much.

The open panel is not padded for: it covers 460px on purpose while a
conversation is under way.
"""

import re


def _css(client):
    css = client.get("/static/css/style.css").get_data(as_text=True)
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _px(value):
    number = float(re.match(r"[\d.]+", value).group())
    return number * 16 if value.endswith("rem") else number


def _padding_for(css, selector):
    rule = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert rule, f"no rule for {selector}"
    value = re.search(r"padding-bottom\s*:\s*([^;]+);", rule.group(1))
    assert value, f"{selector} sets no padding-bottom"
    return _px(value.group(1).strip())


# What each covers at 375px, measured in the PR -- the floor the padding must
# clear. A redesign of the launcher or the bar is the moment to re-measure.
LAUNCHER_COVERS = 66
MINIMIZED_COVERS = 86


def test_the_page_can_scroll_clear_of_the_launcher(client):
    pad = _padding_for(_css(client), "body:has(#mykola-launcher:not([hidden]))")
    assert pad > LAUNCHER_COVERS, pad


def test_the_page_can_scroll_clear_of_the_minimized_bar(client):
    pad = _padding_for(_css(client), "body:has(#mykola-panel.minimized:not([hidden]))")
    assert pad > MINIMIZED_COVERS, pad


def test_minimizing_hides_the_recap_row(client):
    """Every part of the panel below its header goes when it is minimized --
    the recap row included."""
    css = _css(client)
    hidden = set()
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if re.search(r"display\s*:\s*none", body):
            hidden.update(s.strip() for s in selectors.split(","))
    for part in ("#mykola-messages", "#mykola-form", ".mykola-auth", ".mykola-tools"):
        assert f"#mykola-panel.minimized {part}" in hidden, part


def test_the_recap_row_is_in_the_panel_for_a_learner(user_client, app_module,
                                                     monkeypatch):
    """The hide rule above is only worth having while the row is where it
    looks for it: inside #mykola-panel."""
    monkeypatch.setattr("chat.MYKOLA_AVAILABLE", True)
    body = user_client.get("/").get_data(as_text=True)
    panel = body[body.index('id="mykola-panel"'):]
    assert 'class="mykola-tools"' in panel
