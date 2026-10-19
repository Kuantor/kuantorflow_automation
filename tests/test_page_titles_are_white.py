"""Every page heading on the photo is white (kuantorflow#638).

A page built on `base.html` puts its heading straight on the background
photograph, and `.page-title` is what makes it readable there: white, with a
soft shadow. Three pages used a bare `<h1>` and stayed dark grey -- *Build a
topic*, *Add more words to "…"* and the filling page -- seen while recording
the "Meet KuantorFlow" video.

The rule is read from the templates, not listed here: any template that extends
`base.html` and has an `<h1>` must give it `page-title`, so a page added later
is held to it too. The two printable pages (`word_list.html`,
`worksheet.html`) have their own `<body>` and a white sheet, so they are
outside the rule by construction rather than by an exception list.
"""

import re
from pathlib import Path

import pytest

from conftest import KUANTORFLOW_PATH

TEMPLATES = Path(KUANTORFLOW_PATH) / "templates"
EXTENDS_BASE = re.compile(r"""\{%\s*extends\s+["']base\.html["']\s*%\}""")
H1 = re.compile(r"<h1\b([^>]*)>")


def _on_the_photo():
    """{template name: [the attributes of each <h1>]} for base.html pages."""
    found = {}
    for path in sorted(TEMPLATES.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        if EXTENDS_BASE.search(text) and H1.search(text):
            found[path.name] = H1.findall(text)
    return found


def test_the_rule_reaches_the_pages_it_is_about():
    # Guards the derivation: if the regexes stopped matching, every check
    # below would pass on an empty list.
    pages = _on_the_photo()
    assert {"generate_topic.html", "add_words.html", "filling_topic.html",
            "quiz.html", "flashcards.html"} <= set(pages)


@pytest.mark.parametrize("name", sorted(_on_the_photo()))
def test_every_heading_on_the_photo_is_a_page_title(name):
    for attrs in _on_the_photo()[name]:
        classes = re.search(r"""class=["']([^"']*)["']""", attrs)
        assert classes and "page-title" in classes.group(1).split(), \
            f"{name}: <h1{attrs}> needs class=\"page-title\" to be white on the photo"


def test_the_printable_pages_are_outside_the_rule():
    pages = _on_the_photo()
    assert "word_list.html" not in pages and "worksheet.html" not in pages


def test_page_title_is_white():
    css = (Path(KUANTORFLOW_PATH) / "static" / "css" / "style.css").read_text(encoding="utf-8")
    rule = re.search(r"\n\.page-title\s*\{([^}]*)\}", css)
    assert rule and re.search(r"color:\s*#fff\b", rule.group(1))
