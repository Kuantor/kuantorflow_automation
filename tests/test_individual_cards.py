"""
'Use only individual cards' (kuantorflow#127).

A per-user view filter: when it is on, the topic list, the topic page, the card
deck, the quiz and the widget's chip refresh all show only the cards this user
added (#89 records who). Nothing is deleted, nothing changes about who may
write, and everyone else still sees the filtered-out cards.

The trap this setting is built around is NULL. `added_by_user_id = 5` is never
true for an unowned card, which is what correctly hides pre-#89 rows from an
individual view — and is also why "no filter" has to be a *missing clause*
rather than an owner of None, which would hide every card instead of none.
"""

import json

import pytest

import settings_store
import utils
from conftest import TEST_USER_ID

STORED_CARD = {
    "id": 1, "word": "resilient", "pos": "adjective",
    "explanation_en": "able to recover quickly", "examples_en": [],
    "translation_ukr": "стійкий", "examples_ukr": [],
    "translation_rus": "упругий", "examples_rus": [], "topic": "character",
    "added_by_user_id": TEST_USER_ID,
}


@pytest.fixture()
def individual(app_module, monkeypatch):
    """Turn the setting on for whoever the request is signed in as."""
    def prefs():
        stored = dict(settings_store.DEFAULTS)
        stored["individual_cards"] = True
        return stored
    monkeypatch.setattr(app_module, "current_settings", prefs)


def _capture_owner(app_module, monkeypatch, cards=None):
    """Record the owner each read is asked for."""
    seen = []

    def fake_cards(topic, owner_id=None):
        seen.append(owner_id)
        return list(cards if cards is not None else [dict(STORED_CARD)])

    def fake_topics(owner_id=None):
        seen.append(owner_id)
        return [("character", 1)]

    monkeypatch.setattr(app_module, "get_flashcards_by_topic", fake_cards)
    monkeypatch.setattr(app_module, "get_topics", fake_topics)
    return seen


# --- the setting --------------------------------------------------------


def test_the_setting_exists_and_is_off_by_default():
    """Off by design: the deck is shared, and a learner who has added nothing
    would otherwise open an empty site."""
    assert settings_store.DEFAULTS["individual_cards"] is False


def test_it_is_a_boolean_setting():
    assert "individual_cards" in settings_store.BOOLEAN_KEYS


def test_a_junk_value_falls_back_to_the_default(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_store, "SETTINGS_DIR", tmp_path)
    stored = settings_store.save({"individual_cards": "yes please"}, user_id=7)
    assert stored["individual_cards"] is False


def test_it_round_trips_through_the_settings_route(user_client):
    resp = user_client.post("/settings",
                            data=json.dumps({"individual_cards": True}),
                            content_type="application/json")
    assert resp.status_code == 200
    assert resp.get_json()["settings"]["individual_cards"] is True


# --- which owner the reads are asked for --------------------------------


def test_off_by_default_every_read_is_unfiltered(user_client, app_module,
                                                 monkeypatch):
    seen = _capture_owner(app_module, monkeypatch)
    user_client.get("/")
    user_client.get("/flashcards/character")
    assert seen == [None, None], "None means the shared deck, not 'owned by nobody'"


@pytest.mark.parametrize("path", ["/", "/flashcards/character",
                                  "/deck/character", "/quiz/character",
                                  "/topics.json"])
def test_every_read_path_is_filtered_when_on(user_client, app_module,
                                             monkeypatch, individual, path):
    seen = _capture_owner(app_module, monkeypatch)
    assert user_client.get(path).status_code == 200
    assert seen and all(owner == TEST_USER_ID for owner in seen), \
        f"{path} did not filter by owner"


def test_an_anonymous_visitor_is_never_filtered(client, app_module,
                                                monkeypatch, individual):
    """They share config-default.json, which #102 makes read-only for them —
    a filter left on there would hide the site from every anonymous visitor
    with no way to turn it back off."""
    seen = _capture_owner(app_module, monkeypatch)
    client.get("/")
    assert seen == [None]


def test_the_filter_does_not_change_who_may_write(user_client, app_module,
                                                  monkeypatch, individual,
                                                  saved):
    """It is a view filter — #125's rule about writing is untouched."""
    resp = user_client.post("/cards/add", data={
        "word": "resilient", "pos": "adjective", "topic": "character"})
    assert resp.status_code == 200
    assert saved.owner_ids == [TEST_USER_ID]


# --- what the SQL actually asks for -------------------------------------

class FakeCursor:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((" ".join(query.split()), params))

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, **kwargs):
        return self._cursor

    def close(self):
        pass


def _fake_db(monkeypatch, rows=()):
    cursor = FakeCursor(rows)
    monkeypatch.setattr(utils, "get_db_connection", lambda: FakeConn(cursor))
    return cursor


def test_no_owner_means_no_clause_at_all(monkeypatch):
    """The whole deck — not 'cards owned by NULL', which matches nothing."""
    cursor = _fake_db(monkeypatch)
    utils.get_flashcards_by_topic("character")
    query, params = cursor.queries[0]
    assert "added_by_user_id" not in query
    assert params == ("character",)


def test_an_owner_adds_an_equality_clause(monkeypatch):
    cursor = _fake_db(monkeypatch)
    utils.get_flashcards_by_topic("character", owner_id=TEST_USER_ID)
    query, params = cursor.queries[0]
    assert "added_by_user_id = %s" in query
    assert params == ("character", TEST_USER_ID)
    # Equality, not inequality: '!= other' would silently drop unowned rows,
    # which is the NULL trap this setting lives closest to.
    assert "!=" not in query


def test_topics_are_counted_per_owner(monkeypatch):
    cursor = _fake_db(monkeypatch, rows=[("character", 1)])
    utils.get_topics(owner_id=TEST_USER_ID)
    query, params = cursor.queries[0]
    assert "added_by_user_id = %s" in query
    assert params == (TEST_USER_ID,)
    # Grouped by the topics row rather than by the string (kuantorflow#207),
    # but still counting *cards* — which is what keeps this setting about
    # ownership of cards and not about who created the topic.
    assert "GROUP BY t.id, t.name" in query
    assert "f.added_by_user_id = %s" in query, \
        "the filter is on the card's owner, qualified now that topics is joined"
    assert "created_by_user_id" not in query, \
        "a topic's creator must never filter a view"


def test_topics_unfiltered_by_default(monkeypatch):
    cursor = _fake_db(monkeypatch, rows=[("character", 1)])
    utils.get_topics()
    query, params = cursor.queries[0]
    assert "added_by_user_id" not in query
    assert params == ()


def test_the_owner_clause_is_bound_never_interpolated(monkeypatch):
    """The id comes from the session, but it still travels as a parameter."""
    cursor = _fake_db(monkeypatch)
    utils.get_flashcards_by_topic("character", owner_id=TEST_USER_ID)
    query, params = cursor.queries[0]
    assert str(TEST_USER_ID) not in query
    assert TEST_USER_ID in params


# --- what the user sees -------------------------------------------------


def test_someone_elses_card_disappears(user_client, app_module, monkeypatch,
                                       individual):
    """The filter is applied in SQL, so the page simply has nothing to show —
    this checks the page copes rather than rendering a stray card."""
    monkeypatch.setattr(app_module, "get_flashcards_by_topic",
                        lambda topic, owner_id=None: [])
    body = user_client.get("/flashcards/character").get_data(as_text=True)
    assert "resilient" not in body


def test_an_empty_topic_page_says_why(user_client, app_module, monkeypatch,
                                      individual):
    """'No flashcards saved under this topic yet' would send the user looking
    for a bug — the cards are there, they are just not theirs."""
    monkeypatch.setattr(app_module, "get_flashcards_by_topic",
                        lambda topic, owner_id=None: [])
    body = user_client.get("/flashcards/character").get_data(as_text=True)
    assert "individual cards" in body.lower()
    assert "No cards of your own" in body


def test_an_empty_topic_list_says_why(user_client, app_module, monkeypatch,
                                      individual):
    monkeypatch.setattr(app_module, "get_topics", lambda owner_id=None: [])
    body = user_client.get("/").get_data(as_text=True)
    assert "No topics of your own" in body


def test_an_empty_deck_says_why(user_client, app_module, monkeypatch,
                                individual):
    monkeypatch.setattr(app_module, "get_flashcards_by_topic",
                        lambda topic, owner_id=None: [])
    body = user_client.get("/deck/character").get_data(as_text=True)
    assert "No cards of your own" in body


def test_an_empty_quiz_names_the_filter_as_well(user_client, app_module,
                                                monkeypatch, individual):
    """The quiz has two reasons to be empty — no translations, or the filter —
    so naming only the first would mislead."""
    monkeypatch.setattr(app_module, "get_flashcards_by_topic",
                        lambda topic, owner_id=None: [])
    body = user_client.get("/quiz/character").get_data(as_text=True)
    assert "nothing to quiz on" in body
    assert "individual cards" in body.lower()


def test_the_ordinary_empty_message_is_unchanged_when_off(user_client,
                                                          app_module,
                                                          monkeypatch):
    monkeypatch.setattr(app_module, "get_flashcards_by_topic",
                        lambda topic, owner_id=None: [])
    body = user_client.get("/flashcards/character").get_data(as_text=True)
    assert "No flashcards saved under this topic yet" in body


def test_the_checkbox_is_in_the_settings_popup(user_client):
    body = user_client.get("/").get_data(as_text=True)
    assert 'name="individual_cards"' in body
    assert "Use only individual cards" in body


def test_the_checkbox_is_disabled_for_an_anonymous_visitor(client):
    """There is no account to filter by, and the default config is shared."""
    body = client.get("/").get_data(as_text=True)
    marker = body[body.index('name="individual_cards"'):]
    marker = marker[:marker.index(">")]
    assert "disabled" in marker
