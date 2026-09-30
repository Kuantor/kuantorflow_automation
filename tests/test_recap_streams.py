"""The recap is streamed, and fast thinking reaches it (kuantorflow#495).

Found in testing #495's button: every message of Mykola's is typed out except
the recap, which arrived as one JSON string -- and ai_agent's `recap()` took no
`fast`, so `_agent_kwargs()` (which passes a setting only where the method
accepts it) never sent the learner's *Fast thinking* to it.

Now the button's request (`requested` and `stream`) is answered with the chat
stream's events when the agent has `stream_recap()`: `delta`s, then one `done`
carrying `recap`, `notice` and `retry`. Everything decided before the model
call -- the farewell, nothing to recap, the ceiling -- stays plain JSON.
"""

import json

import pytest

import chat


class _Agent:
    """Records what the recap was asked with; streams `parts`."""

    def __init__(self, parts=("Last time ", "we worked on ", "'reluctant'."),
                 fail_after=None):
        self.parts, self.fail_after, self.calls = list(parts), fail_after, []

    def recap(self, logs, user_name=None, hidden_languages=None,
              away_hours=None, fast=False):
        self.calls.append(("recap", fast))
        return "".join(self.parts)

    def stream_recap(self, logs, user_name=None, hidden_languages=None,
                     away_hours=None, fast=False):
        self.calls.append(("stream_recap", fast))
        for i, part in enumerate(self.parts):
            if self.fail_after is not None and i == self.fail_after:
                raise RuntimeError("the API went away")
            yield part


@pytest.fixture()
def recap_ready(app_module, monkeypatch):
    """A signed-in learner with history, allowed a recap, fast thinking off."""
    monkeypatch.setattr("chat.MYKOLA_AVAILABLE", True)
    monkeypatch.setattr("chat._said_farewell_today", lambda: False)
    monkeypatch.setattr("chat._read_user_logs", lambda **k: "some history")
    monkeypatch.setattr("utils.claim_action", lambda *a, **k: (True, 0))
    import web
    real = web.current_settings
    settings = {"mykola_fast_thinking": False}
    monkeypatch.setattr("web.current_settings", lambda: {**real(), **settings})

    def use(agent):
        monkeypatch.setattr("chat.get_mykola", lambda: agent)
        return agent
    use.settings = settings
    return use


def _events(resp):
    assert resp.mimetype == "text/event-stream", resp.mimetype
    frames = resp.get_data(as_text=True).split("\n\n")
    return [json.loads(f[len("data: "):]) for f in frames if f.strip()]


def test_the_button_gets_the_recap_as_it_is_written(user_client, recap_ready):
    agent = recap_ready(_Agent())
    r = user_client.post("/mykola/recap", json={"requested": True, "stream": True})
    events = _events(r)
    assert [e["text"] for e in events if e["type"] == "delta"] == \
        ["Last time ", "we worked on ", "'reluctant'."]
    assert events[-1] == {"type": "done",
                          "recap": "Last time we worked on 'reluctant'.",
                          "notice": None, "retry": False}
    assert [c[0] for c in agent.calls] == ["stream_recap"], "one model call"


@pytest.mark.parametrize("stream", [True, False])
def test_fast_thinking_reaches_the_recap(user_client, recap_ready, stream):
    """The other half of the report: the setting was never sent, because the
    agent's recap did not accept it. Streamed or whole, it is sent now."""
    agent = recap_ready(_Agent())
    recap_ready.settings["mykola_fast_thinking"] = True
    r = user_client.post("/mykola/recap",
                         json={"requested": True, "stream": stream})
    r.get_data()   # drain the stream, which is where the call happens
    assert agent.calls and agent.calls[0][1] is True, agent.calls


def test_fast_thinking_off_sends_nothing(user_client, recap_ready):
    agent = recap_ready(_Agent())
    user_client.post("/mykola/recap",
                     json={"requested": True, "stream": True}).get_data()
    assert agent.calls == [("stream_recap", False)]


def test_a_failure_halfway_ends_in_the_failure_sentence(user_client, recap_ready):
    """The status is 200 once the stream opens, so a failure can only be the
    closing event. It is RECAP_FAILED with `retry` -- the widget replaces the
    half-typed text with it and brings the button back."""
    recap_ready(_Agent(fail_after=1))
    events = _events(user_client.post("/mykola/recap",
                                      json={"requested": True, "stream": True}))
    assert events[-1] == {"type": "done", "recap": None,
                          "notice": chat.RECAP_FAILED, "retry": True}


def test_an_empty_recap_is_a_failure_not_a_blank(user_client, recap_ready):
    """A refused recap streams nothing at all."""
    recap_ready(_Agent(parts=()))
    events = _events(user_client.post("/mykola/recap",
                                      json={"requested": True, "stream": True}))
    assert events == [{"type": "done", "recap": None,
                       "notice": chat.RECAP_FAILED, "retry": True}]


def test_a_failed_whole_recap_asks_to_be_retried(user_client, recap_ready):
    agent = recap_ready(_Agent())

    def down(*a, **k):
        raise RuntimeError("down")
    agent.recap = down
    data = user_client.post("/mykola/recap", json={"requested": True}).get_json()
    assert data == {"recap": None, "notice": chat.RECAP_FAILED, "retry": True}


def test_an_answer_is_not_a_retry(user_client, recap_ready):
    """Only the failure brings the button back; a recap given is the end."""
    recap_ready(_Agent())
    data = user_client.post("/mykola/recap", json={"requested": True}).get_json()
    assert data["recap"] and data["retry"] is False


def test_a_widget_that_did_not_ask_for_a_stream_gets_json(user_client,
                                                          recap_ready):
    """A page opened before the deploy sends `requested` alone and reads
    JSON; streaming it would break the one request it makes."""
    agent = recap_ready(_Agent())
    r = user_client.post("/mykola/recap", json={"requested": True})
    assert r.mimetype == "application/json"
    assert r.get_json()["recap"] == "Last time we worked on 'reluctant'."
    assert [c[0] for c in agent.calls] == ["recap"]


def test_an_agent_that_cannot_stream_answers_whole(user_client, recap_ready):
    """kuantorflow and ai_agent deploy in either order."""
    class _Old:
        def recap(self, logs, **k):
            return "An older recap."
    recap_ready(_Old())
    r = user_client.post("/mykola/recap",
                         json={"requested": True, "stream": True})
    assert r.mimetype == "application/json"
    assert r.get_json()["recap"] == "An older recap."


def test_the_ceiling_is_still_claimed_before_the_stream(user_client,
                                                        recap_ready,
                                                        monkeypatch):
    """A refusal has to be decided before the first byte, and it stays JSON."""
    import utils
    agent = recap_ready(_Agent())
    monkeypatch.setattr("utils.claim_action", lambda name, *a, **k:
                        (False, 5) if name == utils.RECAP else (True, 0))
    r = user_client.post("/mykola/recap",
                         json={"requested": True, "stream": True})
    assert r.mimetype == "application/json"
    assert r.get_json() == {"recap": None, "notice": chat.RECAP_LIMIT_REACHED}
    assert agent.calls == [], "refused, and the model was called anyway"
