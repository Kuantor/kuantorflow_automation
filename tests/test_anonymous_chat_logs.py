"""An anonymous conversation is not written down (kuantorflow#163).

The widget tells a visitor who declines to sign in that "nothing is kept
under your name". That held only in a lawyer's reading: their chat went to
the shared `mykola_logs/` root rather than a per-user folder, but both sides
of it sat on the server all the same — 39 such files in the checkout when
this was found.

Nothing ever read them. `_user_log_files()` returns [] whenever the resolved
directory is the shared root, so the welcome-back recap (ai_agent#30) and the
chat restart (ai_agent#54) skipped them. They were write-only, which is what
made deleting the write the cheap fix rather than a trade.

These tests are about a *promise*, so they assert on the whole directory tree
rather than on one expected filename: the criterion is that nothing appears
anywhere under mykola_logs/, not that a particular file is missing.
"""

import time
import types
from datetime import datetime, timedelta

import pytest

from conftest import TEST_USER_ID


@pytest.fixture()
def mykola(app_module, monkeypatch):
    """Mykola available, with the model call replaced by a canned answer."""
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    monkeypatch.setattr(
        app_module, "_agent_answer",
        lambda q, h: {"response": "Indeed, madam.", "history": h, "sources": []})
    monkeypatch.setattr(app_module, "claim_anonymous_message",
                        lambda limit: (True, 1))
    monkeypatch.setattr(app_module, "get_mykola",
                        lambda: types.SimpleNamespace(
                            recap=lambda *a, **k: "Welcome back!"))
    return app_module


def _ask(client, text="what does brittle mean?"):
    return client.post("/mykola/chat", json={"question": text})


def _files(chat_logs):
    """Every file anywhere under the log root, relative and sorted."""
    return sorted(str(p.relative_to(chat_logs))
                  for p in chat_logs.rglob("*") if p.is_file())


def _restart(client, hours_ago=5):
    """Ask the widget's restart question with a stale client timestamp.

    The timestamp is the part that matters here: `_last_chat_activity()` reads
    the user's own logs and finds nothing for an anonymous visitor, but the
    browser sends the moment of its own last message, so an anonymous chat can
    reach the restart path — and, before #163, drop a marker file in the
    shared root on the way.
    """
    moment = datetime.now() - timedelta(hours=hours_ago)
    return client.post("/mykola/restart-check",
                       json={"last_message_at": moment.timestamp() * 1000}
                       ).get_json()


# --- the anonymous visitor ---------------------------------------------------

def test_an_anonymous_chat_writes_nothing(client, mykola, chat_logs):
    assert _ask(client).status_code == 200
    assert _files(chat_logs) == []


def test_a_whole_anonymous_conversation_writes_nothing(client, mykola,
                                                       chat_logs):
    """Several messages, in case only the first one were skipped."""
    for text in ("hello", "what does brittle mean?", "and resilient?"):
        assert _ask(client, text).status_code == 200
    assert _files(chat_logs) == []


def test_an_anonymous_restart_writes_no_marker(client, mykola, chat_logs):
    """The restart opens the new conversation's log file (ai_agent#54) — for
    an anonymous visitor there is no conversation to open."""
    data = _restart(client)
    assert data["restart"] is True, "the restart itself still happens"
    assert data["chat_id"], "the widget is still handed a fresh id"
    assert _files(chat_logs) == []


def test_an_anonymous_restart_gets_no_recap(client, mykola, chat_logs):
    """Nothing to review: their previous chats were never written down."""
    assert _restart(client)["recap"] is None


# --- the signed-in user, unchanged -------------------------------------------

def test_a_signed_in_chat_is_still_logged(user_client, mykola, chat_logs):
    _ask(user_client)
    chats = list((chat_logs / str(TEST_USER_ID)).glob("chat_*.txt"))
    assert len(chats) == 1, _files(chat_logs)
    body = chats[0].read_text(encoding="utf-8")
    assert "what does brittle mean?" in body and "Indeed, madam." in body


def test_a_signed_in_restart_still_opens_a_log(user_client, mykola, chat_logs):
    """The counterpart of the anonymous case: for someone with an account the
    marker is exactly the record they were promised."""
    user_dir = chat_logs / str(TEST_USER_ID)
    user_dir.mkdir(parents=True, exist_ok=True)
    old = user_dir / "chat_2026-07-20_11-00-00_aaaa.txt"
    old.write_text("[2026-07-20 11:00:00]\nUser:\nq\n\nMykola:\na\n",
                   encoding="utf-8")
    stale = time.time() - 5 * 3600
    import os
    os.utime(old, (stale, stale))

    data = _restart(user_client)
    assert data["restart"] is True
    started = user_dir / f"chat_{data['chat_id']}.txt"
    assert started.is_file(), "the restarted conversation must open its log"
    assert "Chat restarted automatically" in started.read_text(encoding="utf-8")


# --- the rule itself ---------------------------------------------------------

def test_the_shared_root_is_never_a_destination(app_module, chat_logs):
    """`_chat_log_path()` is the single place that decides, so both writers
    inherit the rule rather than each remembering it."""
    with app_module.app.test_request_context("/mykola/chat"):
        assert app_module._chat_log_path("abcd") is None

    with app_module.app.test_request_context("/mykola/chat") as ctx:
        ctx.session["user"] = {"id": TEST_USER_ID, "name": "Test User",
                               "email": "test.user@gmail.com"}
        path = app_module._chat_log_path("abcd")
    assert path is not None
    assert path.parent == chat_logs / str(TEST_USER_ID), path


def test_the_widget_still_makes_the_promise(client, mykola):
    """The sentence this issue exists to make true. If it is ever reworded to
    say chats *are* kept, this test should be the thing that argues back."""
    body = client.get("/").get_data(as_text=True)
    assert "nothing is kept under your name" in body
