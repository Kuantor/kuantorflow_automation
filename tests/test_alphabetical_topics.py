"""Topics ordered by name, with a switch (kuantorflow#363).

`get_topics_by_section()` orders by `(section.position, topic.position,
topic.name)` — kuantorflow#215's rule. This setting drops the middle term, so
it says something only in a section that numbers its topics: today the B2–C1
shelf, which carries kuantorflow#203's curriculum order. `Other` looks the
same either way, every topic in it holding position 0 and already sorting by
name.

What is actually worth pinning is not the sort — MySQL does that — but that
**every surface asks for the same order**. Four of them list topics, they are
reached by different routes, and a page that read the database directly would
be the one page ordered differently from the rest. So each is asked, with the
switch on and off, whether the flag arrived.

The ordering itself is proved against real MySQL in test_topic_sections_db.py,
where the collation is the one production uses rather than a fixture's idea
of alphabetical.
"""

import json

import pytest
import settings_store

from conftest import in_other


@pytest.fixture()
def asked(app_module, monkeypatch):
    """Record how each read path asked for its topics."""
    calls = []

    def fake_sections(owner_id=None, alphabetical=False):
        calls.append(alphabetical)
        return in_other([("basics", 3), ("apples", 1)])

    monkeypatch.setattr(app_module, "get_topics_by_section", fake_sections)
    monkeypatch.setattr(app_module, "get_topics", lambda owner_id=None: ["apples"])
    return calls


# --- the setting -----------------------------------------------------------

def test_it_is_on_by_default():
    """The judgement in the ticket: a browse page is somewhere you look a
    topic up, and the stored order can only be used by someone who has already
    learnt it."""
    assert settings_store.DEFAULTS["alphabetical_topics"] is True


def test_it_round_trips_through_the_settings_endpoint(user_client):
    stored = user_client.post("/settings",
                              json={"alphabetical_topics": False}).get_json()

    assert stored["settings"]["alphabetical_topics"] is False
    assert user_client.post("/settings", json={"alphabetical_topics": True}) \
        .get_json()["settings"]["alphabetical_topics"] is True


# --- every surface asks for the same order ---------------------------------

SURFACES = ["/", "/topics.json", "/quiz"]


@pytest.mark.parametrize("url", SURFACES)
def test_each_page_asks_for_the_order_the_setting_names(url, user_client, asked):
    user_client.post("/settings", json={"alphabetical_topics": True})
    assert user_client.get(url).status_code == 200
    assert asked and all(asked), f"{url} did not ask for alphabetical topics"

    asked.clear()
    user_client.post("/settings", json={"alphabetical_topics": False})
    assert user_client.get(url).status_code == 200
    assert asked and not any(asked), f"{url} ignored the switch being off"


def test_mykolas_topic_list_asks_too(user_client, app_module, asked):
    """The fourth reader, and the one with no page of its own.

    Mykola is told what topics exist; told them in a different order from the
    page the learner is looking at, he answers "the topics are…" with a list
    that matches nothing on screen.
    """
    user_client.post("/settings", json={"alphabetical_topics": True})
    with app_module.app.test_request_context("/"):
        app_module._topics_for_chat()

    assert asked == [True]


def test_a_dead_database_still_renders_the_page(user_client, app_module,
                                                monkeypatch):
    """The switch must not turn a database error into a 500 — the index and
    the picker both swallow one deliberately."""
    def boom(owner_id=None, alphabetical=False):
        raise RuntimeError("no database")

    monkeypatch.setattr(app_module, "get_topics_by_section", boom)
    monkeypatch.setattr(app_module, "get_topics", lambda owner_id=None: [])

    assert user_client.get("/").status_code == 200
    assert user_client.get("/quiz").status_code == 200


# --- the popup -------------------------------------------------------------

def test_the_popup_offers_the_switch_checked(client):
    body = client.get("/").get_data(as_text=True)

    assert 'name="alphabetical_topics"' in body
    assert "Sort topics alphabetically" in body
    box = body[body.index('name="alphabetical_topics"'):]
    assert box[:120].count("checked"), "on by default, so it renders checked"


def test_the_switch_is_saved_and_the_stale_page_reloaded(client):
    """Two halves of one behaviour.

    The value has to travel with the save — the payload is a hand-written
    object, so a control can be added to the form and silently never sent —
    and the page has to reload, because the order it was rendered with is the
    thing that just changed. kuantorflow#127 already reloads for the same
    reason; this joins that condition rather than adding a second one.
    """
    body = client.get("/").get_data(as_text=True)

    assert "alphabetical_topics: settingsForm.alphabetical_topics.checked" in body
    assert '["individual_cards", "alphabetical_topics"]' in body
    assert "if (listChanged) window.location.reload();" in body
