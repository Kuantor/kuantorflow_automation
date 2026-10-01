"""Printing a game's page (kuantorflow#521).

Ctrl+P on a round printed the screen: the header, Mykola's widget covering
the results, the photograph and titles in white. One `@media print` block in
`style.css` now covers every page on `base.html`, and a print-only heading
says what the round was -- the activity, the topics it was dealt from (or that
it was a review) and the date.

Verified in the PR by printing a Multiple choice results page to PDF with
headless Chrome and reading it back: no header, no Mykola, no buttons, the
heading present, black titles, a check or cross on every question.
"""

import re
from pathlib import Path

import pytest

import chat

APP = Path(chat.__file__).parent


def _print_css(client):
    css = client.get("/static/css/style.css").get_data(as_text=True)
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    blocks = []
    for match in re.finditer(r"@media\s+print\s*\{", css):
        depth, i = 1, match.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        blocks.append(css[match.end():i - 1])
    assert blocks, "no @media print block in style.css"
    return "\n".join(blocks)


def _hidden_in_print(css):
    hidden = set()
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if re.search(r"display\s*:\s*none", body):
            hidden.update(s.strip() for s in selectors.split(","))
    return hidden


@pytest.mark.parametrize("selector", [".site-header", "#mykola-launcher",
                                      "#mykola-panel", ".site-footer",
                                      ".crumbs", ".modal-overlay",
                                      ".welcome-overlay", "button"])
def test_the_screen_furniture_does_not_print(client, selector):
    assert selector in _hidden_in_print(_print_css(client)), selector


def test_the_page_prints_white_with_black_titles(client):
    css = _print_css(client)
    assert re.search(r"html,\s*body\s*\{[^}]*background:\s*#fff", css)
    title = re.search(r"\.page-title,\s*\.score\s*\{([^}]*)\}", css)
    assert title and "#000" in title.group(1) and "text-shadow: none" in title.group(1)


def test_a_question_never_splits_across_two_pages(client):
    css = _print_css(client)
    panel = re.search(r"\.panel,\s*\.card\s*\{([^}]*)\}", css)
    assert panel and re.search(r"break-inside:\s*avoid", panel.group(1))


def test_right_and_wrong_survive_black_and_white(client):
    css = _print_css(client)
    assert re.search(r'\.question\.correct > \.word:first-child::before\s*\{\s*content:\s*"\\2713', css)
    assert re.search(r'\.question\.wrong > \.word:first-child::before\s*\{\s*content:\s*"\\2717', css)


def test_the_heading_is_hidden_on_screen(client):
    css = client.get("/static/css/style.css").get_data(as_text=True)
    outside = re.sub(r"@media\s+print\s*\{.*", "", css, flags=re.S)
    assert re.search(r"\.print-only\s*\{\s*display:\s*none", outside)


def _heading(body):
    found = re.search(r'<p class="print-only print-heading">(.*?)</p>', body, re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", found.group(1))).replace("&middot;", "·").strip() if found else None


WORDS = ["employer", "salary", "overtime", "deadline", "promotion", "colleague"]


@pytest.fixture()
def deck(stub_deck):
    cards = [{"id": i, "word": w, "pos": "noun", "topic": "Work",
              "translation_ukr": f"переклад{i}", "translation_rus": f"перевод{i}",
              "explanation_en": f"meaning {i}", "examples_en": []}
             for i, w in enumerate(WORDS, 1)]
    return stub_deck(cards=cards)


def test_a_game_page_says_what_was_played(client, deck):
    heading = _heading(client.get("/games/multiple_choice/play?topic=Work&words=3").get_data(as_text=True))
    assert heading and heading.startswith("Multiple choice · Work · "), heading
    assert re.search(r"\d{1,2} \w+ \d{4}$", heading), heading


def test_the_quiz_says_what_was_played(client, deck):
    heading = _heading(client.get("/quiz?topic=Work&words=3").get_data(as_text=True))
    assert heading and heading.startswith("Quiz · Work · "), heading


def test_a_review_says_so_instead_of_listing_the_deck(user_client, deck, monkeypatch):
    import datetime
    monkeypatch.setattr("utils.due_dates", lambda user_id: {
        ("salary", "noun"): datetime.date.today()}, raising=False)
    heading = _heading(user_client.get("/games/multiple_choice/play?review=1").get_data(as_text=True))
    assert heading and "Review: words due today" in heading and "Work" not in heading, heading


def test_pages_that_are_not_a_round_have_no_heading(client):
    assert "print-heading" not in client.get("/").get_data(as_text=True)


def test_read_a_text_still_prints_only_its_sheet():
    """Its own rules come first and are unchanged by the global ones."""
    source = (APP / "templates" / "game_read_a_text.html").read_text(encoding="utf-8")
    assert ".reader-sheet, .reader-sheet * { visibility: visible; }" in source
