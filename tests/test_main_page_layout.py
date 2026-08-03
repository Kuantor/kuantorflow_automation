"""The main page reordered, topics as tiles, and the database check moved
into Settings (kuantorflow#184).

Three changes with one thread between them: the page should lead with what a
returning learner came for. Browsing was below two forms they only need when
adding something new; the topics were pills, which have nowhere to put the
picture #185 will give them; and a whole section was spent on a diagnostic.

The tile shape and the panel order are ordinary presentation, so they are
checked in the rendered page. The database check is different — moving it into
a popup that opens on *every* page is what made a redirect the wrong answer,
and that is a route change worth pinning.
"""

import re

import pytest


TOPICS = [("basics", 12), ("it-vocab", 5), ("solo", 1)]


@pytest.fixture()
def topics(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "get_topics", lambda owner_id=None: TOPICS)
    return TOPICS


def _panels(body):
    """The main page's section headings, in the order they are rendered."""
    return [re.sub(r"\s*\(.*", "", h).strip()
            for h in re.findall(r"<h2>(.*?)</h2>", body, flags=re.S)]


# --- the order of the page ---------------------------------------------------

def test_browsing_comes_before_looking_up(client, topics):
    body = client.get("/").get_data(as_text=True)
    assert _panels(body) == ["Browse flashcards", "Look up a word",
                             "Upload notes"]


def test_browsing_comes_straight_after_the_welcome_caption(client, topics):
    """Nothing is inserted between the title and the deck."""
    body = client.get("/").get_data(as_text=True)
    between = body.split("Welcome to KuantorFlow")[1].split("Browse flashcards")[0]
    assert "<h2>" not in between, between[:400]


def test_the_database_section_is_gone(client, topics):
    """A diagnostic does not deserve a section of the main page."""
    body = client.get("/").get_data(as_text=True)
    assert "<h2>Database</h2>" not in body
    assert 'value="test_db"' not in body, "the old form must not linger"


# --- the tiles ---------------------------------------------------------------

def test_each_topic_is_a_tile_linking_to_it(client, topics):
    body = client.get("/").get_data(as_text=True)
    assert 'class="topic-tiles"' in body
    for topic, _ in TOPICS:
        assert f'href="/flashcards/{topic.replace("-", "-")}"' in body \
            or f"/flashcards/{topic}" in body, topic
    assert body.count('class="topic-tile"') == len(TOPICS)


def test_a_tile_carries_the_name_and_the_count(client, topics):
    body = client.get("/").get_data(as_text=True)
    assert '<span class="topic-tile-name">basics</span>' in body
    assert "12 cards" in body


def test_one_card_is_not_one_cards(client, topics):
    """The count is read aloud on the tile, so it has to be grammatical."""
    body = client.get("/").get_data(as_text=True)
    assert "1 card<" in body and "1 cards" not in body


def test_the_pill_markup_is_gone(client, topics):
    """A leftover `chip` class would still be styled as a pill by any cached
    stylesheet, and would not be square."""
    body = client.get("/").get_data(as_text=True)
    assert 'class="chip"' not in body
    assert 'class="topic-chips"' not in body


def test_the_empty_states_are_unchanged(client, app_module, monkeypatch):
    """The tiles replaced the chips; they did not replace the explanations
    for having none (#127)."""
    monkeypatch.setattr(app_module, "get_topics", lambda owner_id=None: [])
    body = client.get("/").get_data(as_text=True)
    assert "No topics yet" in body
    assert 'class="topic-tiles"' not in body


def test_the_widget_rebuilds_tiles_not_chips(client, app_module, monkeypatch):
    """Mykola refreshes this section in place after saving a card from chat
    (ai_agent#53). It builds the markup in JavaScript, so it has to be changed
    alongside the template or a chat save quietly restores the old pills."""
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    body = client.get("/").get_data(as_text=True)
    refresh = body.split("function refreshBrowseTopics()")[1] \
                  .split("\n            function ")[0]
    assert '"topic-tiles"' in refresh and '"topic-tile"' in refresh
    assert '"chip"' not in refresh and '"topic-chips"' not in refresh
    assert '" card"' in refresh and '" cards"' in refresh, \
        "the singular must survive the rebuild too"


# --- the database check, now in Settings -------------------------------------

def _button(body):
    start = body.index('id="test-db-btn"')
    return body[body.rindex("<button", 0, start):body.index("</button>", start)]


def test_the_button_is_in_the_settings_popup(client):
    body = client.get("/").get_data(as_text=True)
    modal = body.split('id="settings-modal"')[1].split("</form>")[0]
    assert 'id="test-db-btn"' in modal
    assert "Test DB Connection" in modal


def test_the_button_never_submits_the_settings_form(client):
    """It sits inside `#settings-form`, so a default-type button would save
    the settings as a side effect of asking about the database."""
    assert 'type="button"' in _button(client.get("/").get_data(as_text=True))


def test_the_button_works_for_anonymous_visitors(client):
    """Read-only settings (#102) freeze the *settings*; this changes nothing,
    so it stays usable — the same reasoning as Reset Auth."""
    assert "disabled" not in _button(client.get("/").get_data(as_text=True))


def test_the_button_is_on_every_page_not_just_the_index(client, app_module,
                                                        monkeypatch):
    monkeypatch.setattr(app_module, "get_flashcards_by_topic",
                        lambda topic, owner_id=None: [])
    body = client.get("/flashcards/basics").get_data(as_text=True)
    assert 'id="test-db-btn"' in body


def test_a_reachable_database_answers_ok(client, app_module, monkeypatch):
    class FakeConn:
        def close(self):
            pass
    monkeypatch.setattr(app_module, "get_db_connection", FakeConn)
    resp = client.post("/db/test")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}


def test_an_unreachable_database_answers_why(client, app_module, monkeypatch):
    """A failure is an answer to the question that was asked, not a server
    error — so it is still a 200 and the popup can show the reason."""
    def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(app_module, "get_db_connection", boom)
    resp = client.post("/db/test")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is False
    assert "db down" in body["error"]


def test_the_check_never_redirects(client, app_module, monkeypatch):
    """The whole reason it is JSON: the popup opens on every page, and a
    redirect would drop the visitor onto the index from wherever they were."""
    def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(app_module, "get_db_connection", boom)
    for stub in (boom, lambda: type("C", (), {"close": lambda self: None})()):
        monkeypatch.setattr(app_module, "get_db_connection", stub)
        assert client.post("/db/test").status_code == 200


def test_the_check_rejects_get(client):
    assert client.get("/db/test").status_code == 405
