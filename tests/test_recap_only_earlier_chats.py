"""*Recap our last chats* only when there are earlier chats (kuantorflow#590).

A new signed-in learner saw the button at once, though there was nothing to
recap. Anton chose option 1 on 13 Oct 2026: the button means **earlier**
chats, so the conversation in progress does not count -- neither for showing
the button nor for what the recap reads.

* **The page** tells the widget how many saved conversations the learner has,
  and which one when there is only one (`chat._logged_chats()`); with none the
  button is rendered hidden.
* **The widget** shows it when a saved conversation other than the current one
  exists, or when this page started a new chat after one (`hasEarlierChats()`,
  run here in Node).
* **The recap** is sent the current `chat_id` and leaves that conversation out;
  nothing left is `RECAP_NOTHING_YET`, before any ceiling or model call.
"""

import json
import re
import shutil
import subprocess

import pytest

import chat
from conftest import TEST_USER_ID


@pytest.fixture()
def logs(chat_logs):
    """Write saved conversations for the signed-in test user."""
    folder = chat_logs / str(TEST_USER_ID)
    folder.mkdir(exist_ok=True)

    def write(*chat_ids):
        for chat_id in chat_ids:
            (folder / f"chat_{chat_id}.txt").write_text(
                f"User:\nhello from {chat_id}\n\nMykola:\nhi {chat_id}\n",
                encoding="utf-8")
    return write


def _page(client, monkeypatch):
    monkeypatch.setattr("chat.MYKOLA_AVAILABLE", True)
    return client.get("/").get_data(as_text=True)


def _tools_tag(body):
    found = re.search(r'<div class="mykola-tools"[^>]*>', body)
    assert found, "the recap button's container is missing"
    return found.group(0)


def _logged(body):
    found = re.search(r"var RECAP_LOGS = (\{.*?\});", body)
    assert found, "the page does not tell the widget about saved chats"
    return json.loads(found.group(1))


# --- the page ---------------------------------------------------------------

def test_a_new_learner_gets_the_button_hidden(user_client, monkeypatch, logs):
    body = _page(user_client, monkeypatch)

    assert " hidden" in _tools_tag(body)
    assert _logged(body) == {"count": 0, "only": None}


def test_one_saved_chat_is_named_and_left_to_the_widget(user_client, monkeypatch, logs):
    """It may be the conversation in progress, which only the widget knows."""
    logs("abc123")
    body = _page(user_client, monkeypatch)

    assert " hidden" in _tools_tag(body)
    assert _logged(body) == {"count": 1, "only": "abc123"}


def test_two_saved_chats_show_the_button(user_client, monkeypatch, logs):
    """At most one of them is the current one, so an earlier one exists."""
    logs("first", "second")
    body = _page(user_client, monkeypatch)

    assert " hidden" not in _tools_tag(body)
    assert _logged(body)["count"] == 2


def test_an_anonymous_visitor_still_gets_no_button(client, monkeypatch, logs):
    body = _page(client, monkeypatch)

    assert 'id="mykola-recap"' not in body
    assert _logged(body) == {"count": 0, "only": None}


def test_a_chat_id_is_written_as_safe_json(user_client, monkeypatch, chat_logs):
    """A file name reaches a script block, so it goes through `tojson`, which
    escapes the characters HTML would read (`&`, `'`, `<`, `>`)."""
    folder = chat_logs / str(TEST_USER_ID)
    folder.mkdir(exist_ok=True)
    (folder / "chat_a'b&c.txt").write_text("User:\nx\n", encoding="utf-8")
    body = _page(user_client, monkeypatch)

    assert "a'b&c" not in body.split("var RECAP_LOGS")[1].split(";")[0]
    assert _logged(body) == {"count": 1, "only": "a'b&c"}


# --- the widget's rule, run in Node -----------------------------------------

def _has_earlier(body, cases):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is not installed; the widget rule is checked in a browser")
    source = re.search(r"function hasEarlierChats\(.*?\n            \}", body, re.S)
    assert source, "hasEarlierChats() is missing from the widget"
    script = source.group(0) + "\nconsole.log(JSON.stringify(" + json.dumps(cases) + \
        ".map(function (c) { return hasEarlierChats(c[0], c[1], c[2]); })));"
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_the_widget_rule(user_client, monkeypatch, logs):
    body = _page(user_client, monkeypatch)
    none, one = {"count": 0, "only": None}, {"count": 1, "only": "abc"}
    two = {"count": 2, "only": None}

    assert _has_earlier(body, [
        [none, None, False],     # a brand-new learner
        [none, "new1", False],   # ... after their first message
        [none, "new2", True],    # ... and a New chat on the same page
        [one, "abc", False],     # the one saved chat is the current one
        [one, "other", False],   # another conversation is current
        [one, None, False],      # a fresh widget, the saved chat is earlier
        [two, "abc", False],     # two saved: one at least is earlier
    ]) == [False, False, True, False, True, True, True]


def test_the_widget_uses_the_rule_and_notices_a_new_chat(user_client, monkeypatch, logs):
    body = _page(user_client, monkeypatch)
    sync = body.split("function syncRecapButton()")[1].split("\n            }")[0]
    fresh = body.split("function startFreshChat(")[1].split("\n            }")[0]

    assert "hasEarlierChats(RECAP_LOGS, chatId, earlierHere)" in sync
    assert "recapAsked" in sync
    before = fresh.split("chatId = newChatId")[0]
    assert "if (chatId) earlierHere = true" in before


def test_the_recap_request_names_the_current_chat(user_client, monkeypatch, logs):
    body = _page(user_client, monkeypatch)
    request = body.split("function requestRecap()")[1].split("\n            }")[0]

    assert "chat_id: chatId" in request


# --- the recap leaves the current chat out ----------------------------------

class _Agent:
    def __init__(self):
        self.read = []

    def recap(self, logs, **kwargs):
        self.read.append(logs)
        return "Last time we talked."


@pytest.fixture()
def agent(app_module, monkeypatch):
    found = _Agent()
    monkeypatch.setattr("chat.MYKOLA_AVAILABLE", True)
    monkeypatch.setattr("chat.get_mykola", lambda: found)
    monkeypatch.setattr("chat._said_farewell_today", lambda: False)
    monkeypatch.setattr("utils.claim_action", lambda *a, **k: (True, 0))
    return found


def test_only_the_current_chat_is_nothing_yet(user_client, agent, logs):
    logs("abc")

    data = user_client.post("/mykola/recap",
                            json={"requested": True, "chat_id": "abc"}).get_json()

    assert data["notice"] == chat.RECAP_NOTHING_YET
    assert agent.read == []


def test_the_recap_reads_the_earlier_chats_only(user_client, agent, logs):
    logs("earlier", "current")

    data = user_client.post("/mykola/recap",
                            json={"requested": True, "chat_id": "current"}).get_json()

    assert data["recap"] == "Last time we talked."
    (read,) = agent.read
    assert "hello from earlier" in read and "hello from current" not in read


def test_a_request_with_no_chat_id_reads_them_all(user_client, agent, logs):
    """An open page from before this change sends none."""
    logs("earlier", "current")

    user_client.post("/mykola/recap", json={"requested": True})

    assert "hello from current" in agent.read[0]


def test_no_saved_chats_is_still_nothing_yet(user_client, agent, logs):
    data = user_client.post("/mykola/recap",
                            json={"requested": True, "chat_id": "abc"}).get_json()

    assert data["notice"] == chat.RECAP_NOTHING_YET
