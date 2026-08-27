"""Folding a section of Browse flashcards (kuantorflow#288).

The panel is the tallest thing on the front page, so a section folds away by
clicking its heading and stays folded. Almost all of that is the browser's
work — the markup is a real `<details>`, which folds, answers the keyboard and
announces itself without a line of JavaScript — and the tests follow that
split:

* **the markup**, asserted on the rendered page, because choosing `<details>`
  is the whole design and a click handler bolted onto an `<h3>` would pass a
  test that only asked "does it fold";
* **the twin renderer**, `refreshBrowseTopics()` in base.html, which rebuilds
  this block after a chat save (#53). It has to produce the same markup *and*
  ask for the fold state to be restored — miss the second and every section
  springs open behind a card saved from the chat, which is a bug nobody would
  attribute to folding;
* **the storage rules** in `browse_folds.js`, read from the source, since what
  the file stores is a promise to every device that has already folded
  something.

What is deliberately *not* here: whether a click actually folds the section.
That is `<details>` doing its job, and asserting it would be testing the
browser. It was verified by hand in one — the panel goes from 1,294px to
478px — and the tests guard the markup that lets the browser do it.
"""

import re

import pytest

from conftest import CURRICULUM_SECTION, browse_panel, in_other

TOPICS = [("basics", 12), ("solo", 1)]

FOLD = re.compile(r'<details class="topic-fold" data-section="([^"]*)"([^>]*)>')


@pytest.fixture()
def sections(app_module, monkeypatch):
    """One topic in the curriculum section, two in Other."""
    grouped = [(CURRICULUM_SECTION, [("environment", 4)]),
               ("Other", list(TOPICS))]
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None, alphabetical=False: grouped)
    return grouped


def _browse(body):
    """The Browse panel only — the rest of the page has its own headings."""
    return browse_panel(body)


def _fold(body, section):
    """Everything inside the `<details>` for one section."""
    panel = _browse(body)
    match = re.search(rf'<details class="topic-fold" data-section="{section}"',
                      panel)
    assert match, f"no fold for {section}"
    return panel[match.start():panel.index("</details>", match.start())]


# --- the markup ---------------------------------------------------------


def test_a_section_with_topics_is_a_disclosure(client, sections):
    """`<details>` rather than a heading with a click handler: it folds with
    JavaScript disabled, takes the keyboard, and tells a screen reader what it
    is — none of which a handler gets for free."""
    body = _browse(client.get("/").get_data(as_text=True))
    assert [name for name, _ in FOLD.findall(body)] == \
        [CURRICULUM_SECTION, "Other"]


def test_the_heading_stays_a_heading_inside_the_summary(client, sections):
    """The section's place in the page outline is the `<h3>`, under Browse
    flashcards' `<h2>`. A `<summary>` alone is a control, not a heading, and
    the outline would lose a level."""
    fold = _fold(client.get("/").get_data(as_text=True), "Other")
    assert re.search(r'<summary>\s*(<!--.*?-->\s*)?'
                     r'<h3 class="topic-section">Other</h3>\s*</summary>',
                     fold, re.S), fold[:400]


def test_the_tiles_live_inside_the_fold(client, sections):
    """What folding *is*: the grid is inside the details, so closing it takes
    the tiles with it. A grid left as a sibling would fold nothing and look
    identical in a screenshot."""
    fold = _fold(client.get("/").get_data(as_text=True), "Other")
    assert '<div class="topic-tiles">' in fold
    assert fold.count('class="topic-tile"') == len(TOPICS)


def test_every_section_is_rendered_open(client, sections):
    """The server cannot know what this device folded, and expanded is the
    state that costs nothing to be wrong about: the page a first-time visitor
    gets is the page that existed before #288."""
    body = _browse(client.get("/").get_data(as_text=True))
    assert [attrs.strip() for _, attrs in FOLD.findall(body)] == ["open", "open"]


def test_an_empty_section_gets_a_plain_heading_and_no_fold(client, app_module,
                                                            monkeypatch):
    """#218 keeps the heading for a section with no topics — it says what the
    deck is going to be. A disclosure there would offer to reveal nothing."""
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None, alphabetical=False: in_other(TOPICS))
    panel = _browse(client.get("/").get_data(as_text=True))

    assert [name for name, _ in FOLD.findall(panel)] == ["Other"]
    assert f'<h3 class="topic-section">{CURRICULUM_SECTION}</h3>' in panel
    curriculum = panel.index(CURRICULUM_SECTION)
    assert "topic-fold" not in panel[:curriculum], \
        "the empty section was wrapped in a fold"


def test_the_section_name_is_what_identifies_a_fold(client, app_module,
                                                     monkeypatch):
    """`data-section` is the key the fold state is stored under, so it carries
    the name as it is — including a quote, which would otherwise break out of
    the attribute and take the rest of the panel with it."""
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None, alphabetical=False: [('Ann\'s "shelf"', [("a", 1)])])
    panel = _browse(client.get("/").get_data(as_text=True))
    assert 'data-section="Ann&#39;s &#34;shelf&#34;"' in panel
    assert panel.count("<details") == 1


def test_an_empty_deck_still_says_so(client, app_module, monkeypatch):
    """No headings, no folds, one sentence — #218's rule, unchanged."""
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None, alphabetical=False: in_other([]))
    panel = _browse(client.get("/").get_data(as_text=True))
    assert "topic-fold" not in panel
    assert "No topics yet" in panel


# --- the script that remembers ------------------------------------------


def test_the_script_is_loaded_where_the_panel_is(client, sections):
    """Loaded on the index page and *without* `defer`, so it runs as soon as
    the panel is parsed. Deferred, a folded section would be painted open and
    collapse a moment later — a flicker on every visit."""
    body = client.get("/").get_data(as_text=True)
    tag = re.search(r'<script src="[^"]*browse_folds\.js[^"]*"([^>]*)>', body)
    assert tag, "browse_folds.js is not loaded on the index page"
    assert "defer" not in tag.group(1) and "async" not in tag.group(1)
    assert body.index("browse-topics") < tag.start(), \
        "the script runs before the panel exists"


def test_it_is_not_loaded_on_pages_without_the_panel(client, app_module,
                                                     monkeypatch):
    """It is the index page's script, not the site's: nothing else renders
    this block, and base.html carries enough already."""
    monkeypatch.setattr(app_module, "get_flashcards_by_topic",
                        lambda *a, **k: [])
    body = client.get("/flashcards/basics").get_data(as_text=True)
    assert "browse_folds.js" not in body


@pytest.fixture()
def script(client):
    return client.get("/static/js/browse_folds.js").get_data(as_text=True)


def test_the_storage_key_is_versioned_and_pinned(script):
    """Spelled out here because renaming it silently forgets what every
    existing device had folded — a change worth having to make twice."""
    assert '"kf_browse_folds_v1"' in script


def test_it_stores_what_is_closed_rather_than_what_is_open(script):
    """The whole default rests on this. A section nobody has touched is absent
    from the list and therefore open — including one created since the last
    visit, which storing the *open* ones would arrive folded, hiding cards the
    learner had just added."""
    assert "closedNames" in script
    assert "if (!fold.open) closed.push(name)" in script


def test_apply_is_exported_for_the_rebuild(script):
    """The panel has two renderers and one restore. Without this the chat
    rebuild would have to re-implement reading the store."""
    assert "window.kfBrowseFolds" in script
    assert "apply: apply" in script


def test_blocked_storage_cannot_break_the_page(script):
    """Private modes and locked-down browsers throw on `localStorage`. The
    fold is a nicety; the front page is not."""
    assert "hasStorage" in script
    # Both directions ask first — a store can be readable and refuse a write
    # once it is full — and both are wrapped anyway, because the probe passing
    # is not a promise about the next call.
    assert script.count("if (!hasStorage())") >= 2
    for entry in ("function closedNames()", "function remember("):
        body = script[script.index(entry):]
        assert "try {" in body[:body.index("\n    }")], f"{entry} is unguarded"


# --- the widget's copy of the markup ------------------------------------


def _refresh_source(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    body = client.get("/").get_data(as_text=True)
    return body.split("function refreshBrowseTopics()")[1] \
               .split("\n            function ")[0]


def test_the_rebuild_builds_folds_too(client, app_module, monkeypatch):
    """The trap base.html has carried a comment about since #184: this
    JavaScript and index.html render the same block. Left alone, a card saved
    from the chat would replace every fold with a bare heading and the panel
    would stop folding until the next full page load."""
    refresh = _refresh_source(client, app_module, monkeypatch)
    assert '"topic-fold"' in refresh
    assert '"data-section"' in refresh
    assert 'createElement("details")' in refresh
    assert 'createElement("summary")' in refresh


def test_the_rebuild_restores_what_was_folded(client, app_module, monkeypatch):
    """The folds are new elements, so their state has to be put back. This is
    the half that would be missed: the markup would look right and every
    section would still spring open on a chat save."""
    refresh = _refresh_source(client, app_module, monkeypatch)
    assert "kfBrowseFolds" in refresh and ".apply(" in refresh
    assert "if (window.kfBrowseFolds)" in refresh, \
        "the panel exists on pages the script does not"


def test_the_rebuild_leaves_an_empty_section_unfolded(client, app_module,
                                                      monkeypatch):
    """Same rule as the template's, in the other renderer: a heading with
    nothing under it is not a disclosure."""
    refresh = _refresh_source(client, app_module, monkeypatch)
    empty = refresh[refresh.index("if (!section[1].length)"):]
    assert empty.index("appendChild(heading)") < empty.index('"topic-fold"'), \
        "an empty section is wrapped in a fold before it is checked"
