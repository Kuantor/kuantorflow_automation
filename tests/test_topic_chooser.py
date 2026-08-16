"""The topic chooser on the two save panels (kuantorflow#292).

*Look up a word* and *Upload notes* used to take a topic as bare text, so
filing a card meant remembering what your topics are called and spelling one
correctly — and a typo does not fail, it makes a second topic one letter from
the right one. Both fields are now the control the move dialog has always had:
a free-text input with a `<datalist>` of existing topics.

Not to be confused with the **topic picker** (kuantorflow#250,
`test_topic_picker.py`), which ticks several topics for a game round. This is a
chooser for one destination.

Three things carry the design and each is a way it could go quietly wrong:

* the options are **rendered with the page**, from the same `sections` the
  tiles were drawn from, so they cannot disagree with what the learner can see
  — including under `individual_cards` (#127), where suggesting a hidden
  topic's name would leak exactly what the setting hides;
* the two fields **share one list**, because two copies drift;
* and a card saved from a Mykola chat can create a topic, so the shipped
  refresh rewrites the options **only when the names differ** — most chat saves
  land in a topic that already exists, and replacing the list for nothing swaps
  it out from under an open dropdown.

The server contract is deliberately untouched: the field is still `name=topic`,
an unknown name is still created by `_get_or_create_topic()`, and an empty one
still means `general`. Those are asserted here as *unchanged*, since the whole
point is that only the control changed.
"""

import re

import pytest

from conftest import CURRICULUM_SECTION, browse_panel, in_other

TOPICS = [("Work and careers", 20), ("basics", 12), ("solo", 1)]

FIELDS = ("word-topic", "notes-topic")


def _options(body):
    """The datalist's options, in render order."""
    match = re.search(r'<datalist id="topic-options">(.*?)</datalist>', body, re.S)
    assert match, "no shared topic list on the page"
    return re.findall(r'<option value="([^"]*)"', match.group(1))


def _field(body, field_id):
    match = re.search(rf'<input[^>]*id="{field_id}"[^>]*>', body, re.S)
    assert match, f"no {field_id} field"
    return " ".join(match.group(0).split())


@pytest.fixture()
def topics(app_module, monkeypatch):
    grouped = [(CURRICULUM_SECTION, [("Work and careers", 20)]),
               ("Other", [("basics", 12), ("solo", 1)])]
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None: grouped)
    return grouped


# --- the control --------------------------------------------------------


@pytest.mark.parametrize("field_id", FIELDS)
def test_both_fields_are_choosers(client, topics, field_id):
    """The move dialog's control, down to the placeholder: an existing topic
    from the dropdown, or a new name typed in."""
    field = _field(client.get("/").get_data(as_text=True), field_id)
    assert 'list="topic-options"' in field
    assert 'placeholder="an existing topic, or a new name"' in field
    assert 'autocomplete="off"' in field, \
        "browser form history would compete with the suggestions"


@pytest.mark.parametrize("field_id", FIELDS)
def test_the_field_is_still_free_text_named_topic(client, topics, field_id):
    """Nothing server-side changed. A `<select>` would have been the other way
    to build this and would have made a new topic unreachable from here."""
    field = _field(client.get("/").get_data(as_text=True), field_id)
    assert 'type="text"' in field and 'name="topic"' in field
    assert "required" not in field, "an empty topic still means `general`"


def test_the_two_fields_share_one_list(client, topics):
    """A datalist can be referenced by any number of inputs. Two copies of the
    same options would drift the moment either was touched."""
    body = client.get("/").get_data(as_text=True)
    assert body.count('<datalist id="topic-options">') == 1
    assert body.count('list="topic-options"') == 2


def test_the_hint_is_said_once_under_the_lookup_panel(client, topics):
    """kuantorflow#292: the move dialog's sentence, minus its second half about
    moving. Upload notes is directly below with the same control, and repeating
    the line there is noise rather than help."""
    body = client.get("/").get_data(as_text=True)
    hint = "Typing a topic that does not exist yet creates it."
    assert body.count(hint) == 1

    lookup = body.index("<h2>Look up a word")
    upload = body.index("<h2>Upload notes")
    assert lookup < body.index(hint) < upload
    assert "Moving the last card out of a topic" not in body, \
        "the move dialog's second sentence does not apply here"


# --- what is in the list ------------------------------------------------


def test_the_options_are_the_topics_the_tiles_show(client, topics):
    """Rendered from the same `sections` the tiles were drawn from — one query,
    one answer, and no way for the two to disagree."""
    body = client.get("/").get_data(as_text=True)
    assert _options(body) == ["Work and careers", "basics", "solo"]
    # Through `browse_panel()` (#290), because the games panel between the deck
    # and the datalist reuses `.topic-tile-name` — an unscoped search compares
    # the options against five activities as well.
    assert re.findall(r'topic-tile-name">([^<]+)<',
                      browse_panel(body)) == _options(body)


def test_a_hidden_topic_is_not_suggested(client, app_module, monkeypatch):
    """#127 hides other people's topics from this page. A chooser that
    suggested them would hand back the very names the setting exists to keep
    out of sight — and the leak would be silent, since nothing else on the page
    would show them."""
    import settings_store

    monkeypatch.setattr(app_module, "current_settings",
                        lambda: dict(settings_store.DEFAULTS,
                                     individual_cards=True))
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None: in_other([("mine", 2)]))

    assert _options(client.get("/").get_data(as_text=True)) == ["mine"]


def test_an_empty_deck_leaves_an_empty_list_not_a_missing_one(client, app_module,
                                                              monkeypatch):
    """The field still has to work, and a datalist with no options is a plain
    text box — which is exactly right when there is nothing to suggest."""
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None: in_other([]))
    body = client.get("/").get_data(as_text=True)
    assert _options(body) == []
    assert 'list="topic-options"' in _field(body, "word-topic")


def test_a_dead_database_still_renders_both_panels(client, app_module,
                                                    monkeypatch):
    """`sections` falls back to `[]` when the database is unreachable, and the
    save panels are the last thing that should disappear then — looking a word
    up is how a learner would find out anything is wrong."""
    def boom(owner_id=None):
        raise RuntimeError("db down")

    monkeypatch.setattr(app_module, "get_topics_by_section", boom)
    body = client.get("/").get_data(as_text=True)
    assert _options(body) == []
    for field_id in FIELDS:
        assert 'list="topic-options"' in _field(body, field_id)


def test_a_topic_name_with_quotes_survives_the_option(client, app_module,
                                                       monkeypatch):
    """The value is a topic name somebody typed, so it can hold anything an
    attribute cannot."""
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None: [('Ann\'s "shelf"', [])] +
                                              in_other([('Ann\'s "shelf"', 1)]))
    body = client.get("/").get_data(as_text=True)
    assert _options(body) == ["Ann&#39;s &#34;shelf&#34;"]
    assert "<option value=\"Ann's" not in body


def test_the_list_sits_outside_the_block_a_chat_save_rebuilds(client, topics):
    """`refreshBrowseTopics()` empties `#browse-topics` and builds it again
    (#53). A datalist in there would be deleted by the first chat save, and the
    two fields would silently lose their suggestions."""
    body = client.get("/").get_data(as_text=True)
    browse_end = body.index("</div>", body.index('id="browse-topics"'))
    assert body.index("<datalist") > browse_end


# --- keeping it current after a chat save -------------------------------


def _refresh_source(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    body = client.get("/").get_data(as_text=True)
    return body.split("function refreshTopicOptions(")[1] \
               .split("\n            function ")[0]


def test_the_rebuild_updates_the_options(client, app_module, monkeypatch):
    """Mykola can create a topic mid-conversation (ai_agent#62), and the
    chooser two panels down would be offering a list without it.

    Called *before* the empty-deck early return, since a deck emptied between
    page load and refresh is an answer about the options too."""
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    body = client.get("/").get_data(as_text=True)
    rebuild = body.split("function refreshBrowseTopics()")[1] \
                  .split("\n            function ")[0]

    assert "refreshTopicOptions(sections)" in rebuild
    assert rebuild.index("refreshTopicOptions(sections)") < \
        rebuild.index("No topics yet")


def test_the_options_are_left_alone_when_the_topics_have_not_changed(
        client, app_module, monkeypatch):
    """The other half of the rule, and the reason it is a rule: most chat saves
    add a card to a topic that already exists. Rewriting the options then would
    replace the list under a dropdown the learner may have open, for nothing."""
    refresh = _refresh_source(client, app_module, monkeypatch)
    assert "shown.length === names.length" in refresh
    assert "every(" in refresh, "a length check alone misses a rename"
    # The comparison has to be the gate, not a note taken on the way past: it
    # is only worth anything if it can stop the rewrite.
    assert refresh.index("shown.length === names.length") < \
        refresh.index("removeChild")


def test_the_rebuild_reads_the_same_shape_the_page_rendered(
        client, app_module, monkeypatch):
    """Sections, not the flat `topics` list that is also in the response: the
    server rendered the options in section order, and rebuilding them in
    another order would reshuffle the dropdown on an unrelated chat save."""
    refresh = _refresh_source(client, app_module, monkeypatch)
    assert "section[1]" in refresh
    assert "data.topics" not in refresh


def test_the_rebuild_is_harmless_on_pages_without_the_list(
        client, app_module, monkeypatch):
    """The widget is on every page; the chooser is on one."""
    refresh = _refresh_source(client, app_module, monkeypatch)
    assert 'getElementById("topic-options")' in refresh
    assert "if (!list) return;" in refresh
