"""One message to Mykola is capped in length (kuantorflow#564).

The 1 MB request cap bounds the question *and* the history together, so on
its own it let one pasted message of close to a megabyte through -- sent to
Opus and counted as a single message against ceilings that count messages,
not tokens. #564 caps the message itself.

Pinned here:

* **exactly the limit is answered, one character over is refused**, with the
  sentence, on all three routes (the widget's POST, `/api/chat`, the stream);
* **a refused message spends nothing**: no claim against the day's messages,
  anonymous or account, and nothing reaches the model;
* the cap counts **characters, not bytes**, so Ukrainian gets the same
  allowance as English;
* the refusal is **logged** (length only, never the text);
* the widget's input carries `maxlength` **from the same constant**, and 0
  turns the cap off everywhere.
"""

import pytest

import chat
import web

ROUTES = ["/mykola/chat", "/api/chat", "/mykola/chat/stream"]


@pytest.fixture()
def mykola(app_module, monkeypatch):
    """Mykola available; every claim and every model call is recorded."""
    monkeypatch.setattr("chat.MYKOLA_AVAILABLE", True)
    seen = {"model": [], "claims": [], "anonymous": 0}

    def answer(question, history):
        seen["model"].append(question)
        return {"response": "Indeed.", "history": history, "sources": []}

    def claim_action(name, user_id, limit, amount=1):
        seen["claims"].append(name)
        return True, 0

    def claim_anonymous(limit):
        seen["anonymous"] += 1
        return True, 1

    monkeypatch.setattr("chat._agent_answer", answer)
    monkeypatch.setattr("utils.claim_action", claim_action)
    monkeypatch.setattr("utils.claim_anonymous_message", claim_anonymous)

    class _Agent:
        def stream_answer(self, question, history, **kwargs):
            seen["model"].append(question)
            yield "text", "Indeed."
            yield "done", {"response": "Indeed.", "history": [], "sources": []}

    monkeypatch.setattr("chat.get_mykola", _Agent)
    return seen


def _limit():
    return web.MAX_CHAT_MESSAGE_CHARS


# --- the server -----------------------------------------------------------

def test_the_cap_is_on_by_default():
    assert _limit() == 2000


@pytest.mark.parametrize("path", ROUTES)
def test_a_message_of_exactly_the_limit_is_answered(user_client, mykola, path):
    r = user_client.post(path, json={"question": "a" * _limit()})

    assert r.status_code == 200
    assert mykola["model"] == ["a" * _limit()]


@pytest.mark.parametrize("path", ROUTES)
def test_one_character_over_is_refused_with_the_sentence(user_client, mykola,
                                                         path):
    r = user_client.post(path, json={"question": "a" * (_limit() + 1)})

    assert r.status_code == 400
    assert r.get_json()["error"] == \
        "Please keep a message to Mykola under 2,000 characters."
    assert mykola["model"] == [], "nothing reaches the model"


def test_a_refused_message_spends_nothing_for_an_account(user_client, mykola):
    user_client.post("/mykola/chat", json={"question": "a" * (_limit() + 1)})

    assert mykola["claims"] == [], "no account or shared claim"


def test_a_refused_message_spends_nothing_for_a_visitor(client, mykola):
    client.post("/mykola/chat", json={"question": "a" * (_limit() + 1)})

    assert mykola["anonymous"] == 0
    assert mykola["claims"] == []


def test_the_cap_counts_characters_not_bytes(user_client, mykola):
    """2,000 Cyrillic letters are 4,000 bytes in UTF-8 and still pass."""
    ukrainian = "ї" * _limit()
    assert len(ukrainian.encode("utf-8")) == 2 * _limit()

    r = user_client.post("/mykola/chat", json={"question": ukrainian})

    assert r.status_code == 200


def test_surrounding_spaces_do_not_count(user_client, mykola):
    """The question is stripped before it is measured, as before it is sent."""
    r = user_client.post("/mykola/chat",
                         json={"question": "   " + "a" * _limit() + "   "})

    assert r.status_code == 200


def test_the_refusal_is_logged_without_the_text(user_client, mykola,
                                                action_logs):
    user_client.post("/mykola/chat",
                     json={"question": "secret " + "a" * _limit()})

    log = (action_logs / "mykola.log").read_text(encoding="utf-8")
    line = next(l for l in log.splitlines() if "LIMIT" in l and "kind=length" in l)
    assert "feature=chat" in line
    assert f"chars={_limit() + 7}" in line and f"limit={_limit()}" in line
    assert "secret" not in log


def test_zero_turns_the_cap_off(user_client, mykola, monkeypatch):
    monkeypatch.setattr(web, "MAX_CHAT_MESSAGE_CHARS", 0)

    r = user_client.post("/mykola/chat", json={"question": "a" * 5000})

    assert r.status_code == 200


# --- the widget -----------------------------------------------------------

def _page(client):
    return client.get("/").get_data(as_text=True)


def test_the_input_carries_the_same_limit(user_client, mykola):
    html = _page(user_client)

    assert f'maxlength="{_limit()}"' in html
    assert 'id="mykola-count"' in html


def test_the_input_follows_the_constant(user_client, mykola, monkeypatch):
    """Derived, not a second literal: change the constant and the page
    follows."""
    monkeypatch.setattr(web, "MAX_CHAT_MESSAGE_CHARS", 1234)

    assert 'maxlength="1234"' in _page(user_client)


def test_no_cap_means_no_maxlength(user_client, mykola, monkeypatch):
    monkeypatch.setattr(web, "MAX_CHAT_MESSAGE_CHARS", 0)

    assert "maxlength=" not in _page(user_client).split('id="mykola-input"')[1][:200]


def test_the_counter_appears_only_near_the_limit(user_client, mykola):
    """From 90% of the cap; and it is refreshed when the box is cleared after
    sending, or it would go on showing the last message's count."""
    html = _page(user_client)
    script = html[html.index("function syncCount()"):]

    assert "used < max * 0.9" in script
    assert 'input.value = "";\n                syncCount();' in html


def test_the_guide_states_the_limit(app_module):
    guide = web.USER_GUIDE.read_text(encoding="utf-8")

    assert f"up to **{_limit():,} characters**" in guide
