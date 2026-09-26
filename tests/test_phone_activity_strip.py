"""On a phone the topic page's strip is the back arrow alone (kuantorflow#452).

Eleven items wrapped into three rows at 375pt and pushed the topic heading
down the page before it had said what it is. Under the phone breakpoint the
row now holds **← Home** and nothing else, on the same blue background so it
stays a recognisable strip rather than becoming a bare link.

**What a test file can and cannot settle here.** Whether the heading is above
the fold is a rendered-layout fact, and this suite does not render — it was
measured in a browser instead (375x812: strip 110px → 36px, heading y=251 →
y=177) and that measurement lives in the PR, not in an assertion pretending to
be one. What *is* pinned here is the part that rots: the **selector**, and the
markup it depends on. Those are two files that can drift apart silently, and
every failure mode below leaves a page that renders perfectly.

Three ways this goes wrong, none of which a green run would otherwise notice:

**The rule escapes its scope.** `.crumbs` is on nineteen templates, not the
three the stylesheet claimed until now — every game page, the picker, the
quiz, the deck, the worksheet. On all of those the row is one or two links and
is the way back *out*. A rule written on `.crumbs` rather than on the modifier
hides a learner's only exit mid-game, on a phone, where they cannot see the
URL bar to fix it.

**The hook disappears from the markup.** The selector names two classes the
template has to keep supplying. Remove either and the CSS is still valid, still
present, and matches nothing.

**The rule is phrased as what goes.** The greyed stubs are `<span>`s (#261),
so "hide every `a` after the first" leaves one stranded; and *Take quiz* is
conditional on a visible language, so nothing may count children.
"""

import re

import pytest


CARDS = [
    {"id": 1, "word": "verdict", "pos": "noun", "topic": "Law",
     "translation_ukr": "vyrok", "translation_rus": "prigovor",
     "explanation_en": "a jury's decision", "added_by_user_id": None},
]


@pytest.fixture()
def css(client):
    return client.get("/static/css/style.css").get_data(as_text=True)


@pytest.fixture()
def topic_page(client, stub_deck):
    stub_deck(cards=CARDS)
    r = client.get("/flashcards/Law")
    assert r.status_code == 200
    return r.get_data(as_text=True)


def _phone_rule(css):
    """The block inside the phone media query that hides the row's items."""
    for match in re.finditer(r"@media\s*\(max-width:\s*(\d+)px\)\s*\{", css):
        start = match.end()
        depth, i = 1, start
        while depth and i < len(css):
            depth += (css[i] == "{") - (css[i] == "}")
            i += 1
        body = css[start:i - 1]
        if "crumbs" in body:
            return int(match.group(1)), body
    return None, None


# --- the markup supplies both hooks -----------------------------------------

def test_the_row_carries_the_modifier(topic_page):
    """Without it the rule below matches nothing and the phone layout silently
    reverts — the page renders exactly as it did before #452."""
    assert 'class="crumbs crumbs--activities"' in topic_page


def test_the_home_link_is_marked_as_the_one_that_stays(topic_page):
    """The selector is `:not(.crumbs-home)`, so this class is what keeps the
    arrow on screen. Lose it and the phone strip is an empty blue bar."""
    assert 'class="crumbs-home"' in topic_page

    at = topic_page.index('class="crumbs-home"')
    tag = topic_page[topic_page.rindex("<a", 0, at):topic_page.index(">", at)]
    assert "Home" in topic_page[at:at + 120], tag


def test_the_marked_link_is_the_first_thing_in_the_row(topic_page):
    """A back arrow that is not first is not a back arrow. Asserted because
    the selector does not care about order — it would happily keep a
    `crumbs-home` somebody had moved to the end."""
    at = topic_page.index('class="crumbs crumbs--activities"')
    row = topic_page[at:topic_page.index("</p>", at)]
    first_link = row.index("<a")

    assert "crumbs-home" in row[first_link:first_link + 120]


# --- the rule exists, and is scoped -----------------------------------------

def test_there_is_a_phone_rule_for_the_row(css):
    width, body = _phone_rule(css)

    assert body is not None, "no media query touches .crumbs at all"
    assert width <= 640, f"the breakpoint is {width}px, above a large phone"


def test_the_rule_is_scoped_to_the_topic_pages_row(css):
    """The one that matters. `.crumbs` is on nineteen templates and on
    eighteen of them the row is the way back out."""
    _, body = _phone_rule(css)

    assert "crumbs--activities" in body
    for line in body.splitlines():
        line = line.split("/*")[0].strip()
        if "crumbs" in line and "{" in line:
            assert "crumbs--activities" in line, (
                f"this selector is not scoped to the topic page: {line!r}")


def test_the_rule_hides_children_rather_than_the_panel(css):
    """`display: none` on the container would take the arrow with it and leave
    a bare link where a blue strip was."""
    _, body = _phone_rule(css)

    for line in body.splitlines():
        line = line.split("/*")[0].strip()
        if line.startswith(".crumbs--activities") and "{" in line:
            selector = line.split("{")[0].strip()
            assert selector != ".crumbs--activities", (
                "the panel itself is being hidden, not its children")


def test_the_rule_says_what_stays_rather_than_what_goes(css):
    """A rule naming `a` leaves the greyed `<span>` stubs (#261) stranded on
    the strip, and one naming `nth-child` breaks when *Take quiz* hides."""
    _, body = _phone_rule(css)

    assert ":not(.crumbs-home)" in body.replace(" ", ""), (
        "the rule should select what stays, not enumerate what goes")
    assert "nth-child" not in body, "the row's length is not fixed"


# --- the pages that must not be touched -------------------------------------

@pytest.mark.parametrize("path,label", [
    ("/deck/Law", "the card deck"),
    ("/quiz/Law", "the quiz"),
])
def test_another_pages_row_is_not_scoped(client, stub_deck, path, label):
    """These two share `.crumbs` and their row is the way back out. If either
    ever gains the modifier, its exits vanish on a phone."""
    stub_deck(cards=CARDS)
    r = client.get(path)
    if r.status_code == 404:
        pytest.skip(f"{path} is not reachable with this stub")
    body = r.get_data(as_text=True)

    assert "crumbs" in body, f"{label} lost its row entirely"
    assert "crumbs--activities" not in body, (
        f"{label} picked up the topic page's phone rule")


def test_only_one_template_carries_the_modifier(app_module):
    """Stated over the whole template directory rather than the two pages
    above, because the next page to copy this row is the one nobody thinks to
    check."""
    from pathlib import Path

    templates = Path(app_module.app.root_path) / "templates"
    carriers = sorted(p.name for p in templates.glob("*.html")
                      if "crumbs--activities" in p.read_text(encoding="utf-8"))

    assert carriers == ["flashcards.html"], carriers


def test_plenty_of_templates_still_share_the_plain_class(app_module):
    """The control for the case above, and the reason the scope matters: if
    `.crumbs` were only on the topic page, none of this care would be needed
    and a future reader would wonder why the modifier exists."""
    from pathlib import Path

    templates = Path(app_module.app.root_path) / "templates"
    sharers = [p.name for p in templates.glob("*.html")
               if "crumbs" in p.read_text(encoding="utf-8")]

    assert len(sharers) > 10, (
        f"only {len(sharers)} templates use .crumbs; the scoping rationale "
        "in the stylesheet needs revisiting")
