"""
Pictures on the topic tiles (kuantorflow#223).

A topic finds its icon by **name** — `static/img/topics/<slug>.webp` — so the
whole feature is a convention plus a directory listing. That makes two things
worth pinning down, and they pull in opposite directions:

* the slug rule, because it is the only thing joining a database row to a file
  on disk, and a silent mismatch shows up as a tile that simply has no picture;
* the **absence** of a file, because most topics have none. Everything in
  `Other` and anything a learner invents by looking a word up will never have
  one, so "no icon" is the common path, not the edge case, and it has to leave
  the tile exactly as #184 drew it.

The icon *directory* is stubbed in most tests rather than read from the real
checkout: a test that passed only because someone had committed a matching file
would be asserting the state of `static/`, not the behaviour of the code. Two
tests at the end do read the real directory, deliberately, to catch a name that
has drifted from its file.
"""

import re

import pytest

from conftest import CURRICULUM_SECTION, browse_panel, in_other

TOPICS = [("Work and careers", 20), ("Daily life and routines", 21)]


def _icons(app_module, monkeypatch, *slugs):
    """Pretend the icon directory holds exactly these slugs."""
    monkeypatch.setattr(app_module, "_topic_icon_slugs", lambda: set(slugs))


def _tiles(body):
    """Each **topic** tile as (classes, inner html), in render order.

    Scoped to the browse section since kuantorflow#253: the games panel reuses
    the same tile classes, deliberately, so an unscoped search over the page
    returns five activity tiles alongside the deck's.
    """
    return re.findall(r'<a class="(topic-tile[^"]*)"(.*?)</a>',
                      browse_panel(body), re.S)


# --- the slug rule ------------------------------------------------------


@pytest.mark.parametrize("name,slug", [
    ("Work and careers", "work_and_careers"),
    ("Daily life and routines", "daily_life_and_routines"),
    ("Social interaction and small talk", "social_interaction_and_small_talk"),
    ("Money and the economy", "money_and_the_economy"),
    # Punctuation and case are what a learner-invented topic will bring.
    ("Crime & Justice", "crime_justice"),
    ("IT", "it"),
    ("  padded  ", "padded"),
    ("Work/careers!", "work_careers"),
    ("", ""),
    (None, ""),
])
def test_the_slug_is_the_name_lower_cased_with_runs_collapsed(app_module,
                                                             name, slug):
    """The only thing joining a topics row to a file on disk. A change here
    silently unhooks every icon, so it is spelled out rather than sampled."""
    assert app_module.topic_slug(name) == slug


def test_a_topic_with_a_file_gets_a_static_url(app_module, monkeypatch, client):
    _icons(app_module, monkeypatch, "work_and_careers")
    with client.application.test_request_context():
        assert app_module.topic_icon("Work and careers") == \
            "/static/img/topics/work_and_careers.webp"


def test_a_topic_with_no_file_gets_none(app_module, monkeypatch, client):
    """None, not a placeholder path: the caller decides, and the tile keeps its
    flat colour rather than rendering a broken image."""
    _icons(app_module, monkeypatch, "work_and_careers")
    with client.application.test_request_context():
        assert app_module.topic_icon("Luck and chance") is None
        assert app_module.topic_icon("") is None


def test_a_missing_icon_directory_is_not_an_error(app_module, monkeypatch,
                                                  tmp_path, client):
    """A checkout with no icons committed must still render every tile."""
    monkeypatch.setattr(app_module, "TOPIC_ICON_DIR", tmp_path / "nope")
    # One cache keyed by directory since kuantorflow#253, shared with the game
    # icons, so it is emptied rather than set to None.
    monkeypatch.setattr(app_module._icon_slugs, "cache", {})
    with client.application.test_request_context():
        assert app_module.topic_icon("Work and careers") is None


# --- the tile -----------------------------------------------------------


def test_a_tile_with_an_icon_carries_the_image_and_the_modifier(
        client, app_module, monkeypatch):
    _icons(app_module, monkeypatch, "work_and_careers",
           "daily_life_and_routines")
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None, alphabetical=False: in_other(TOPICS))

    body = client.get("/").get_data(as_text=True)
    tiles = _tiles(body)

    assert len(tiles) == 2
    for classes, inner in tiles:
        assert "topic-tile--image" in classes, "the scrim hangs off this class"
        assert 'class="topic-tile-img"' in inner


def test_a_tile_without_an_icon_has_no_image_at_all(client, app_module,
                                                    monkeypatch):
    """Not an empty src, not a placeholder — no element. A broken-image icon on
    every topic in `Other` would be worse than the plain tile."""
    _icons(app_module, monkeypatch, "work_and_careers")
    monkeypatch.setattr(
        app_module, "get_topics_by_section",
        lambda owner_id=None, alphabetical=False: in_other([("Work and careers", 20),
                                        ("luck and chance", 1)]))

    tiles = _tiles(client.get("/").get_data(as_text=True))
    plain = [inner for classes, inner in tiles
             if "topic-tile--image" not in classes]

    assert len(tiles) == 2 and len(plain) == 1
    assert "topic-tile-img" not in plain[0]
    assert "<img" not in plain[0]


def test_the_image_is_decorative(client, app_module, monkeypatch):
    """An empty alt, on purpose: the topic's name is already on the tile as
    text, so describing the picture would only repeat it to a screen reader."""
    _icons(app_module, monkeypatch, "work_and_careers")
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None, alphabetical=False: in_other([("Work and careers", 20)]))

    body = client.get("/").get_data(as_text=True)
    img = re.search(r'<img class="topic-tile-img"[^>]*>', body).group(0)
    assert 'alt=""' in img
    assert 'loading="lazy"' in img, "18 icons should not block first paint"


def test_the_caption_still_follows_the_image(client, app_module, monkeypatch):
    """Order in the markup is what puts the caption above the scrim. Reversed,
    the name would be painted under it and vanish."""
    _icons(app_module, monkeypatch, "work_and_careers")
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None, alphabetical=False: in_other([("Work and careers", 20)]))

    inner = _tiles(client.get("/").get_data(as_text=True))[0][1]
    assert inner.index("topic-tile-img") < inner.index("topic-tile-name")


# --- /topics.json and the widget ----------------------------------------


def test_topics_json_carries_an_icon_map(client, app_module, monkeypatch):
    """A `name -> url` map, not a third element in each pair. The pair is what
    `get_topics_by_section()` returns and what the move dialog reads; widening
    it would push presentation into the database layer."""
    _icons(app_module, monkeypatch, "work_and_careers")
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None, alphabetical=False: in_other(TOPICS))
    monkeypatch.setattr(app_module, "get_topics", lambda owner_id=None: TOPICS)

    data = client.get("/topics.json").get_json()

    assert data["icons"] == {
        "Work and careers": "/static/img/topics/work_and_careers.webp"}
    assert data["sections"][1][1] == [list(t) for t in TOPICS], \
        "the pairs are unchanged"


def test_a_topic_with_no_icon_is_absent_from_the_map(client, app_module,
                                                      monkeypatch):
    """Absent rather than mapped to null, so the JavaScript's `if (iconUrl)`
    reads the same either way and no tile gets an <img> with a null src."""
    _icons(app_module, monkeypatch)
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None, alphabetical=False: in_other(TOPICS))

    assert client.get("/topics.json").get_json()["icons"] == {}


def test_the_widget_rebuild_uses_the_map_rather_than_guessing(client, app_module,
                                                              monkeypatch):
    """The slug rule lives in Python. Re-deriving it in JavaScript is how the two
    would drift apart, and the symptom would be silently missing pictures."""
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    body = client.get("/").get_data(as_text=True)
    refresh = body.split("function refreshBrowseTopics()")[1] \
                  .split("\n            function ")[0]

    assert "data.icons" in refresh
    assert "topic-tile--image" in refresh
    assert "topic-tile-img" in refresh
    assert "toLowerCase" not in refresh, "it is re-deriving the slug"
    assert ".webp" not in refresh, "it is building the path itself"


# --- the real directory, deliberately -----------------------------------


def test_every_seeded_topic_has_an_icon_file():
    """Read from the checkout on purpose. The eighteen seeded topics (#203) are
    the ones with pictures, and a topic renamed without renaming its file loses
    its icon silently — no error, no log line, just a plain tile."""
    import app as app_mod

    try:
        import seed_words
    except ImportError:
        pytest.skip("seed_words.py is not on the checked-out branch (#203)")

    have = app_mod._topic_icon_slugs()
    missing = [name for name in seed_words.SEED_WORDS
               if app_mod.topic_slug(name) not in have]
    assert missing == []


def test_no_icon_file_is_orphaned():
    """The other direction: a file whose topic no longer exists is dead weight
    on every page load, since the set is committed to the repo."""
    import app as app_mod

    try:
        import seed_words
    except ImportError:
        pytest.skip("seed_words.py is not on the checked-out branch (#203)")

    expected = {app_mod.topic_slug(name) for name in seed_words.SEED_WORDS}
    orphans = sorted(app_mod._topic_icon_slugs() - expected)
    assert orphans == []
