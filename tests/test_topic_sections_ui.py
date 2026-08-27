"""
Sections on the Browse flashcards page (kuantorflow#218).

#215 gave topics a section and rendered nothing. This is the UI half, and the
decisions worth pinning are all about **what a heading means**:

* it is structure, so an empty section still gets one — the B2–C1 shelf has to
  say what the deck is going to be before #203 fills it;
* except when the whole deck is empty, where one sentence beats two headings
  above nothing;
* and #127's "nothing of *yours*" explanation has to win over both.

The Mykola widget rebuilds this block in JavaScript after a chat save (#53),
so the same rules are asserted against that code too. `base.html` has carried a
comment about that trap since #184 and this is the test behind it.
"""

import re

import pytest

from conftest import CURRICULUM_SECTION, browse_panel, in_other

TOPICS = [("basics", 12), ("solo", 1)]

HEADING = re.compile(r'<h3 class="topic-section">([^<]+)</h3>')


def _browse(body):
    """The Browse panel only — the rest of the page has its own headings."""
    return browse_panel(body)


def _layout(body):
    """Headings and grids in the order they are rendered, as a flat list.

    Reading order is the assertion: `('section', 'Other')` immediately followed
    by `('grid', 2)` is what "these tiles belong to that heading" looks like in
    markup, and a heading with no grid after it is an empty section.
    """
    panel = _browse(body)
    out = []
    for m in re.finditer(
            r'<h3 class="topic-section">([^<]+)</h3>|<div class="topic-tiles">',
            panel):
        if m.group(1):
            out.append(("section", m.group(1)))
        else:
            grid = panel[m.end():panel.index("</div>", m.end())]
            out.append(("grid", len(re.findall(r'class="topic-tile"', grid))))
    return out


@pytest.fixture()
def sections(app_module, monkeypatch):
    """Two sections with topics in each, so ordering is observable."""
    grouped = [(CURRICULUM_SECTION, [("environment", 4)]),
               ("Other", list(TOPICS))]
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None, alphabetical=False: grouped)
    return grouped


# --- the headings -------------------------------------------------------


def test_each_section_is_a_heading_followed_by_its_tiles(client, sections):
    assert _layout(client.get("/").get_data(as_text=True)) == [
        ("section", CURRICULUM_SECTION), ("grid", 1),
        ("section", "Other"), ("grid", 2),
    ]


def test_sections_render_in_the_order_they_are_given(client, app_module,
                                                     monkeypatch):
    """The order is the query's — `(section.position, …)` from #215 — and the
    template must not re-sort it into something alphabetical."""
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None, alphabetical=False: [("Zebra", [("a", 1)]),
                                               ("Apple", [("b", 1)])])
    body = client.get("/").get_data(as_text=True)
    assert HEADING.findall(_browse(body)) == ["Zebra", "Apple"]


def test_an_empty_section_keeps_its_heading_and_gets_no_grid(client, app_module,
                                                             monkeypatch):
    """#215 left this open and #218 answers it: the B2–C1 shelf appears, empty,
    until #203 fills it. A heading that showed up only once it had content
    could not do the one job it has."""
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None, alphabetical=False: in_other(TOPICS))
    assert _layout(client.get("/").get_data(as_text=True)) == [
        ("section", CURRICULUM_SECTION),
        ("section", "Other"), ("grid", 2),
    ]


def test_topics_keep_their_order_within_a_section(client, app_module,
                                                  monkeypatch):
    """Also the query's — `(topic.position, topic.name)`. Every topic in
    'Other' holds position 0, so alphabetical there is a *consequence*, not a
    rule the page applies."""
    ordered = [("second", 1), ("first", 1), ("third", 1)]
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None, alphabetical=False: [("Curriculum", ordered)])
    body = _browse(client.get("/").get_data(as_text=True))
    assert re.findall(r'topic-tile-name">([^<]+)<', body) == \
        ["second", "first", "third"]


def test_a_tile_still_links_to_its_topic_with_a_count(client, sections):
    """#184's tile is unchanged by the grouping around it."""
    body = _browse(client.get("/").get_data(as_text=True))
    assert "/flashcards/basics" in body and "12 cards" in body
    assert "/flashcards/solo" in body and "1 card<" in body, "the singular survives"


# --- when there is nothing to show --------------------------------------


def test_an_empty_deck_shows_the_hint_not_bare_headings(client, app_module,
                                                        monkeypatch):
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None, alphabetical=False: in_other([]))
    body = client.get("/").get_data(as_text=True)
    assert HEADING.findall(_browse(body)) == []
    assert "No topics yet" in _browse(body)


def test_the_individual_cards_explanation_still_wins(user_client, app_module,
                                                     monkeypatch):
    """#127's message is the more specific answer, and the sections existing
    does not make it less true — they are everyone's, and none of them holds a
    card of yours."""
    import settings_store

    monkeypatch.setattr(app_module, "current_settings",
                        lambda: dict(settings_store.DEFAULTS,
                                     individual_cards=True))
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None, alphabetical=False: in_other([]))
    body = _browse(user_client.get("/").get_data(as_text=True))
    assert "No topics of your own" in body
    assert HEADING.findall(body) == []


def test_a_dead_database_still_renders_the_page(client, app_module, monkeypatch):
    def boom(owner_id=None):
        raise RuntimeError("db down")

    monkeypatch.setattr(app_module, "get_topics_by_section", boom)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "No topics yet" in resp.get_data(as_text=True)


# --- /topics.json, which two different things read ----------------------


def test_topics_json_carries_both_shapes(client, app_module, monkeypatch):
    """`sections` for the browse tiles, `topics` for the move dialog's
    suggestions (#177). Dropping the flat list while adding the grouped one
    would have emptied that datalist and nothing else would have noticed."""
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None, alphabetical=False: in_other(TOPICS))
    monkeypatch.setattr(app_module, "get_topics", lambda owner_id=None: TOPICS)

    data = client.get("/topics.json").get_json()

    assert [s[0] for s in data["sections"]] == [CURRICULUM_SECTION, "Other"]
    assert data["sections"][1][1] == [list(t) for t in TOPICS]
    assert data["topics"] == [list(t) for t in TOPICS]


def test_topics_json_survives_a_dead_database(client, app_module, monkeypatch):
    def boom(owner_id=None):
        raise RuntimeError("db down")

    monkeypatch.setattr(app_module, "get_topics_by_section", boom)
    data = client.get("/topics.json").get_json()
    # Compared exactly, on purpose: the point is that nothing leaks through a
    # failed read. `icons` joined the payload in #223 and is empty for the same
    # reason the other two are — there are no topics to have icons for.
    assert data == {"topics": [], "sections": [], "icons": {}}


# --- the widget's copy of the markup ------------------------------------


def _refresh_source(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    body = client.get("/").get_data(as_text=True)
    return body.split("function refreshBrowseTopics()")[1] \
               .split("\n            function ")[0]


def test_the_widget_rebuild_reads_sections(client, app_module, monkeypatch):
    """It must consume the grouped shape, not the flat one — the flat list is
    still in the response and reaching for it would silently work while
    rendering the pre-#218 page."""
    refresh = _refresh_source(client, app_module, monkeypatch)
    assert "data.sections" in refresh
    assert "data.topics" not in refresh


def test_the_widget_rebuild_creates_section_headings(client, app_module,
                                                     monkeypatch):
    """Same trap #184 left a comment about: the template and this JavaScript
    render the same block, so a chat save must not quietly flatten it."""
    refresh = _refresh_source(client, app_module, monkeypatch)
    assert '"topic-section"' in refresh
    assert '"topic-tiles"' in refresh and '"topic-tile"' in refresh
    assert '" card"' in refresh and '" cards"' in refresh, \
        "the singular must survive the rebuild too"


def test_the_widget_rebuild_falls_back_to_the_hint_when_nothing_is_left(
        client, app_module, monkeypatch):
    """A deck can become empty between page load and refresh, and the JS has to
    reach the same answer the template does rather than drawing bare headings."""
    refresh = _refresh_source(client, app_module, monkeypatch)
    assert "No topics yet" in refresh
    # The emptiness test has to look *inside* the sections: a non-empty list of
    # empty sections is exactly the case the template calls "no topics".
    assert "some(" in refresh
