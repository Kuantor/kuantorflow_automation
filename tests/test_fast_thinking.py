"""Mykola's fast thinking, as an opt-in setting (ai_agent#50).

One switch over two levers, because the wait has two halves: `effort` decides
how long Claude deliberates before any text exists, and a note in the prompt
decides how much he then writes. Measured over six short questions, two runs
each, against the real API — medians to the first word and to the last:

    off (today)                     3.17s  ->  7.04s, ~520 characters
    effort=medium alone             1.75s  ->  5.65s, ~518 characters
    effort=medium + the note        0.98s  ->  1.98s, ~63 characters

Note what the middle row says: `effort` does not shorten the reply. That is
why one switch moves two things — either alone leaves half the wait behind.

**Off by default**, unlike the typewriter: this one really does change the
answer, and shorter is not automatically better for somebody learning English.
"""

import inspect
import json

import pytest

import settings_store


# --- the setting ------------------------------------------------------------

def test_it_is_off_by_default():
    """A trade, not a free win — so it waits to be asked for."""
    assert settings_store.DEFAULTS["mykola_fast_thinking"] is False


@pytest.mark.parametrize("value,expected", [
    (True, True), (False, False),
    ("yes", False), ("", False), (1, False), (None, False),   # keeps the default
])
def test_it_is_validated_like_every_other_switch(value, expected):
    assert settings_store.sanitize(
        {"mykola_fast_thinking": value})["mykola_fast_thinking"] is expected


def test_turning_it_on_is_stored(user_client, settings_dir):
    resp = user_client.post("/settings", json={"mykola_fast_thinking": True})
    assert resp.status_code == 200
    assert resp.get_json()["settings"]["mykola_fast_thinking"] is True
    stored = json.loads(next(settings_dir.glob("config-7.json"))
                        .read_text(encoding="utf-8"))
    assert stored["mykola_fast_thinking"] is True


# --- the popup --------------------------------------------------------------

def test_the_popup_offers_it(user_client):
    body = user_client.get("/").get_data(as_text=True)
    assert 'name="mykola_fast_thinking"' in body
    assert "Enable Mykola&rsquo;s fast thinking" in body
    assert "mykola_fast_thinking: settingsForm.mykola_fast_thinking.checked" in body, \
        "the checkbox is rendered but never saved"


def test_the_hint_says_what_is_traded(user_client):
    """The label promises speed; the hint has to admit the cost, or somebody
    turns it on and quietly gets a worse teacher."""
    body = user_client.get("/").get_data(as_text=True)
    hint = body.split('name="mykola_fast_thinking"', 1)[1][:900]
    assert "short" in hint.lower()


# --- reaching the agent -----------------------------------------------------

def new_agent(question, history=None, user_name=None, hidden_languages=None,
              fast=False):
    """An installed ai_agent that understands fast thinking."""


def old_agent(question, history=None, user_name=None, hidden_languages=None):
    """One that predates it (ai_agent#50) — the repos deploy in either order."""


def test_it_is_passed_when_on(app_module, user_client, settings_dir):
    user_client.post("/settings", json={"mykola_fast_thinking": True})
    with app_module.app.test_request_context() as ctx:
        ctx.session["user"] = {"id": 7, "email": "test.user@example.com",
                               "name": "Test User"}
        assert app_module._agent_kwargs(new_agent).get("fast") is True


def test_it_is_not_passed_when_off(app_module):
    with app_module.app.test_request_context():
        assert "fast" not in app_module._agent_kwargs(new_agent)


def test_an_older_agent_never_hears_about_it(app_module, user_client,
                                             settings_dir):
    """Feature-detected by signature, like every other agent kwarg: an agent
    that does not take `fast` must not be handed it, or every chat message
    raises TypeError until both repos are deployed."""
    user_client.post("/settings", json={"mykola_fast_thinking": True})
    assert "fast" not in inspect.signature(old_agent).parameters
    with app_module.app.test_request_context() as ctx:
        ctx.session["user"] = {"id": 7, "email": "test.user@example.com",
                               "name": "Test User"}
        assert "fast" not in app_module._agent_kwargs(old_agent)
