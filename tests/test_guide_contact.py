"""The user guide says who made the site and how to reach him.

Until 2 Oct 2026 nothing on the site did: the privacy section told a learner
to "ask the site's owner" about their data and never said how. The guide is
the one place the site describes itself -- `/help` renders it and Mykola
answers from it (#310, #460) -- so the contact lives there, under its own
`###` heading, because a heading is what Mykola retrieves by.
"""

import re
from pathlib import Path

import web

EMAIL = "anton.kuznietsov@gmail.com"
SITE = "https://kuantor.github.io/"
REPO = "https://github.com/Kuantor/kuantorflow"
HEADING = "### Who made it, and how to get in touch"


def _guide():
    return Path(web.USER_GUIDE).read_text(encoding="utf-8")


def test_the_guide_ends_with_who_made_it_and_how_to_reach_him():
    guide = _guide()
    section = guide[guide.index(HEADING):]

    assert f"[{EMAIL}](mailto:{EMAIL})" in section
    assert f"]({SITE})" in section
    assert "made by **Anton Kuznietsov** using [Claude Code](" in section
    assert f"[github.com/Kuantor/kuantorflow]({REPO})" in section,         "the source is public, and the visible text is the address for the PDF"
    assert "## " not in section[len(HEADING):].replace("### ", ""), \
        "the contact is the guide's last section"


def test_the_privacy_section_says_where_to_ask(client):
    guide = _guide()
    privacy = guide[guide.index("## Privacy: what the site keeps"):guide.index("## The idea behind it")]

    assert "To ask about your data, or to have something removed" in privacy
    assert "(#who-made-it-and-how-to-get-in-touch)" in privacy


def test_the_help_page_renders_both_links_and_the_anchor(client):
    body = client.get("/help").get_data(as_text=True)

    assert f'<a href="mailto:{EMAIL}">{EMAIL}</a>' in body
    assert f'<a href="{SITE}">kuantor.github.io</a>' in body
    assert f'<a href="{REPO}">github.com/Kuantor/kuantorflow</a>' in body
    assert '<a href="https://claude.com/claude-code">Claude Code</a>' in body
    assert 'id="who-made-it-and-how-to-get-in-touch"' in body
    assert re.search(r'href="#who-made-it-and-how-to-get-in-touch"', body), \
        "the privacy section links to it"
