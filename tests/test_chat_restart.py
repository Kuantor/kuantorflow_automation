"""Automatic chat restart after a break (ai_agent#54).

A conversation left untouched for longer than `restart_chat_interval` hours
is restarted when the learner comes back: Mykola reviews their last three
exchanges, a new chat-log file is opened, and the widget is handed its id and
his recap. 0 hours means "never restart".
"""

import json
import os
import time
import types
from datetime import datetime, timedelta

import pytest

import settings_store
from conftest import TEST_USER_ID


# --- the setting ------------------------------------------------------------

def test_default_interval_is_two_hours():
    assert settings_store.DEFAULTS["restart_chat_interval"] == 2


@pytest.mark.parametrize("value,expected", [
    (1, 1), (24, 24), (0, 0), (5, 5),           # the slider's range, plus never
    ("7", 7), (6.0, 6),                          # JSON round-trips
    (25, 2), (-1, 2), (2.5, 2),                  # out of range / not whole
    (True, 2), ("later", 2), (None, 2),          # nonsense falls back
])
def test_interval_is_validated(value, expected):
    assert settings_store.sanitize(
        {"restart_chat_interval": value})["restart_chat_interval"] == expected


def test_never_restart_is_saved_as_zero(user_client, settings_dir):
    resp = user_client.post("/settings", json={"restart_chat_interval": 0})
    assert resp.status_code == 200
    assert resp.get_json()["settings"]["restart_chat_interval"] == 0
    stored = json.loads(next(settings_dir.glob("config-7.json"))
                        .read_text(encoding="utf-8"))
    assert stored["restart_chat_interval"] == 0


# --- the endpoint -----------------------------------------------------------

def _mykola(app_module, monkeypatch, recap="Welcome back!", records=None):
    """Force the widget on and stub the agent's recap()."""
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)

    def fake_recap(past_conversations, user_name=None, hidden_languages=None,
                   away_hours=None):
        if records is not None:
            records.append({"text": past_conversations, "away_hours": away_hours})
        if isinstance(recap, Exception):
            raise recap
        return recap

    monkeypatch.setattr(app_module, "get_mykola",
                        lambda: types.SimpleNamespace(recap=fake_recap))


def _check(client, hours_ago=None):
    body = {}
    if hours_ago is not None:
        moment = datetime.now() - timedelta(hours=hours_ago)
        body["last_message_at"] = moment.timestamp() * 1000
    return client.post("/mykola/restart-check", json=body).get_json()


def test_no_restart_within_the_interval(client, app_module, monkeypatch):
    _mykola(app_module, monkeypatch)
    data = _check(client, hours_ago=0.5)      # default threshold is 2 hours
    assert data["restart"] is False
    assert data["away_hours"] == pytest.approx(0.5, abs=0.05)


def test_restart_after_the_interval(client, app_module, monkeypatch):
    _mykola(app_module, monkeypatch)
    data = _check(client, hours_ago=5)
    assert data["restart"] is True
    assert data["chat_id"]                     # the widget adopts this id
    assert data["away_hours"] == pytest.approx(5, abs=0.05)


def test_zero_interval_never_restarts(client, app_module, monkeypatch):
    _mykola(app_module, monkeypatch)
    monkeypatch.setattr(app_module, "current_settings",
                        lambda: dict(settings_store.DEFAULTS,
                                     restart_chat_interval=0))
    data = _check(client, hours_ago=100)
    assert data == {"restart": False, "reason": "disabled"}


def test_without_any_history_there_is_nothing_to_restart(client, app_module,
                                                         monkeypatch):
    _mykola(app_module, monkeypatch)
    assert _check(client)["reason"] == "no history"


def test_no_restart_when_mykola_is_unavailable(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", False)
    assert _check(client, hours_ago=99)["restart"] is False


def test_a_future_client_stamp_is_ignored(client, app_module, monkeypatch):
    """A clock-skewed browser must not fake 'no break' or a huge one."""
    _mykola(app_module, monkeypatch)
    assert _check(client, hours_ago=-5)["reason"] == "no history"


# --- what the restart reviews and writes ------------------------------------

EXCHANGES = "".join(
    f"[2026-07-20 1{i}:00:00]\nUser:\nquestion {i}\n\nMykola:\nanswer {i}\n"
    for i in range(1, 6)
)


def _user_log(chat_logs, text=EXCHANGES, hours_ago=5):
    """Give the signed-in user one old chat log (in the autouse temp log dir).

    Keyed on the user id since kuantorflow#174, matching user_client."""
    user_dir = chat_logs / str(TEST_USER_ID)
    user_dir.mkdir(parents=True, exist_ok=True)
    path = user_dir / "chat_2026-07-20_11-00-00_aaaa.txt"
    path.write_text(text, encoding="utf-8")
    old = time.time() - hours_ago * 3600
    os.utime(path, (old, old))
    return user_dir


def test_only_the_last_three_exchanges_are_reviewed(user_client, app_module,
                                                    monkeypatch, chat_logs):
    records = []
    _mykola(app_module, monkeypatch, records=records)
    _user_log(chat_logs)
    assert _check(user_client)["restart"] is True
    reviewed = records[0]["text"]
    assert "question 3" in reviewed and "question 5" in reviewed
    assert "question 2" not in reviewed, "only the last three exchanges"
    assert records[0]["away_hours"] == pytest.approx(5, abs=0.1)


def test_the_restart_opens_a_new_log_file(user_client, app_module, monkeypatch,
                                          chat_logs):
    _mykola(app_module, monkeypatch, recap="Good to see you again!")
    user_dir = _user_log(chat_logs)
    data = _check(user_client)

    new_log = user_dir / f"chat_{data['chat_id']}.txt"
    assert new_log.exists(), "a restarted chat gets its own log file"
    text = new_log.read_text(encoding="utf-8")
    assert "Chat restarted automatically" in text
    assert "Good to see you again!" in text
    assert data["recap"] == "Good to see you again!"


def test_the_break_is_measured_from_the_newest_log(user_client, app_module,
                                                   monkeypatch, chat_logs):
    """A signed-in learner who wrote from another device an hour ago is not
    restarted, whatever this browser's stale stamp says."""
    _mykola(app_module, monkeypatch)
    _user_log(chat_logs, hours_ago=1)
    assert _check(user_client, hours_ago=48)["restart"] is False


def test_a_failing_recap_still_restarts(user_client, app_module, monkeypatch,
                                        chat_logs):
    _mykola(app_module, monkeypatch, recap=RuntimeError("Anthropic is down"))
    _user_log(chat_logs)
    data = _check(user_client)
    assert data["restart"] is True and data["recap"] is None


def test_anonymous_visitors_restart_without_a_recap(client, app_module,
                                                    monkeypatch):
    """They have no per-user logs, so there is nothing for Mykola to review —
    the conversation still starts fresh."""
    _mykola(app_module, monkeypatch)
    data = _check(client, hours_ago=5)
    assert data["restart"] is True and data["recap"] is None


def test_away_hours_is_only_sent_to_agents_that_accept_it(user_client, app_module,
                                                          monkeypatch, chat_logs):
    """Feature detection (the repos deploy in any order): an older ai_agent
    whose recap() has no away_hours must still be callable."""
    seen = {}

    def old_recap(past_conversations, user_name=None, hidden_languages=None):
        seen["called"] = True
        return "recap from an older agent"

    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    monkeypatch.setattr(app_module, "get_mykola",
                        lambda: types.SimpleNamespace(recap=old_recap))
    _user_log(chat_logs)
    data = _check(user_client)
    assert seen.get("called") and data["recap"] == "recap from an older agent"


# --- the Settings control ---------------------------------------------------

def test_settings_popup_has_the_slider_and_never_checkbox(client):
    body = client.get("/").get_data(as_text=True)
    assert 'type="range"' in body and 'name="restart_chat_interval"' in body
    assert 'min="1"' in body and 'max="24"' in body
    assert "Never restart chat automatically" in body
    assert 'name="restart_never"' in body
    assert "function updateRestartState()" in body
    assert "restartSlider.disabled = restartNever.checked" in body


def test_never_checkbox_is_checked_and_slider_disabled_at_zero(user_client,
                                                               app_module,
                                                               monkeypatch):
    monkeypatch.setattr(app_module, "current_settings",
                        lambda: dict(settings_store.DEFAULTS,
                                     restart_chat_interval=0))
    body = user_client.get("/").get_data(as_text=True)
    slider = body.split('name="restart_chat_interval"')[1].split(">")[0]
    assert "disabled" in slider
    never = body.split('name="restart_never"')[1].split(">")[0]
    assert "checked" in never


def test_slider_shows_the_stored_hours(user_client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "current_settings",
                        lambda: dict(settings_store.DEFAULTS,
                                     restart_chat_interval=9))
    body = user_client.get("/").get_data(as_text=True)
    slider = body.split('name="restart_chat_interval"')[1].split(">")[0]
    assert 'value="9"' in slider and "disabled" not in slider
    assert "9 h</output>" in body


def test_widget_asks_the_server_on_load(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    body = client.get("/").get_data(as_text=True)
    assert "function maybeRestartChat()" in body
    assert "/mykola/restart-check" in body
    assert "if (hasConversation()) maybeRestartChat();" in body
    assert "last_message_at: lastMessageAt" in body
