"""Mykola's answer, delivered as it is written (ai_agent#50).

The agent has streamed from the Anthropic API since it was written; what was
missing was carrying those fragments past the HTTP boundary, so the learner
watched a spinner while finished text sat in a Python variable.

What these tests hold onto is the part that is easy to lose: **the words are
not the whole answer**. The sources, the history and — the one that matters —
which cards were saved are only known when the last round finishes, so the
stream has to end with an event carrying them, and a client that renders
deltas and ignores the rest would silently stop refreshing the deck.
"""

import json

import pytest


class StubAgent:
    """An agent that streams, in the shape `stream_answer()` really yields."""

    def __init__(self, deltas=("Hello", ", ", "friend."), saved_cards=(), boom=False):
        self.deltas = list(deltas)
        self.saved_cards = list(saved_cards)
        self.boom = boom
        self.asked = []

    def stream_answer(self, question, history=None, **kwargs):
        self.asked.append(question)
        for delta in self.deltas:
            yield "text", delta
        if self.boom:
            raise RuntimeError("the model fell over mid-answer")
        yield "done", {
            "response": "".join(self.deltas),
            "sources": [{"file": "grammar.md", "heading": "Articles"}],
            "history": list(history or []) + [{"role": "assistant", "content": "x"}],
            "saved_cards": self.saved_cards,
        }


class OldAgent:
    """An ai_agent from before #50 — it answers, but it cannot stream."""

    def answer(self, question, history=None, **kwargs):
        return {"response": "Indeed.", "sources": [], "history": [],
                "saved_cards": []}


@pytest.fixture()
def streaming(app_module, monkeypatch, chat_logs):
    agent = StubAgent()
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    monkeypatch.setattr(app_module, "get_mykola", lambda: agent)
    monkeypatch.setattr(app_module, "claim_anonymous_message",
                        lambda limit: (True, 1))
    return agent


def events(response):
    """The SSE frames of a response, parsed back into dicts."""
    body = response.get_data(as_text=True)
    return [json.loads(chunk[len("data: "):])
            for chunk in body.split("\n\n") if chunk.strip()]


def ask(client, text="what does brittle mean?"):
    return client.post("/mykola/chat/stream", json={"question": text})


# --- the stream itself ------------------------------------------------------

def test_the_words_arrive_as_separate_events(client, streaming):
    frames = events(ask(client))
    deltas = [f["text"] for f in frames if f["type"] == "delta"]
    assert deltas == ["Hello", ", ", "friend."], "the reply arrived in one piece"


def test_the_last_event_carries_what_the_words_cannot(client, streaming):
    streaming.saved_cards = [{"word": "brittle"}]
    done = [f for f in events(ask(client)) if f["type"] == "done"]
    assert len(done) == 1
    assert done[0]["response"] == "Hello, friend."
    assert done[0]["sources"] == [{"file": "grammar.md", "heading": "Articles"}]
    assert done[0]["saved_cards"] == [{"word": "brittle"}]
    assert done[0]["history"]
    assert done[0]["chat_id"], "the widget needs the id to keep one conversation"


def test_it_is_served_as_a_stream_and_asks_not_to_be_buffered(client, streaming):
    response = ask(client)
    assert response.mimetype == "text/event-stream"
    # A buffering proxy would hold every fragment and deliver the reply in one
    # piece at the end — this feature, silently undone, with nothing in the
    # code to see.
    assert response.headers.get("X-Accel-Buffering") == "no"
    assert response.headers.get("Cache-Control") == "no-cache"


def test_the_exchange_is_still_logged(user_client, streaming, chat_logs):
    """A streamed answer is logged exactly as a whole one is — and an
    anonymous conversation is still not written down (#163), which is why
    this signs in first."""
    # Read the body: a streamed response does its work *as the client reads
    # it*, so a test that only checks the status code runs no generator at all
    # and would pass here whatever the endpoint did.
    events(ask(user_client, "what does resign mean?"))
    written = [p for p in chat_logs.rglob("*") if p.is_file()]
    assert written, "no chat log was written"
    text = written[0].read_text(encoding="utf-8")
    assert "what does resign mean?" in text
    assert "Hello, friend." in text, "the assembled answer was not logged"


def test_an_anonymous_conversation_is_still_not_written_down(client, streaming,
                                                             chat_logs):
    events(ask(client))
    assert not [p for p in chat_logs.rglob("*") if p.is_file()]


# --- degrading, rather than breaking ----------------------------------------

def test_an_agent_that_cannot_stream_gives_a_404(client, app_module, monkeypatch):
    """The two repos deploy in either order, so a kuantorflow that has been
    pulled and an ai_agent that has not must fall back to yesterday's
    behaviour. 404 is what tells the widget to use the JSON endpoint."""
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    monkeypatch.setattr(app_module, "get_mykola", lambda: OldAgent())
    assert ask(client).status_code == 404


def test_a_failure_mid_answer_is_an_event_not_a_status(client, app_module,
                                                       monkeypatch, chat_logs):
    """Once the first byte is out the status is 200 for good — so a failure
    after that point can only be said in an event."""
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    monkeypatch.setattr(app_module, "get_mykola",
                        lambda: StubAgent(boom=True))
    monkeypatch.setattr(app_module, "claim_anonymous_message",
                        lambda limit: (True, 1))
    response = ask(client)
    assert response.status_code == 200
    frames = events(response)
    assert [f["type"] for f in frames][-1] == "error"
    assert frames[-1]["error"]


# --- the rules that decide whether a message is answered at all -------------

def test_an_empty_question_is_refused_as_json(client, streaming):
    response = client.post("/mykola/chat/stream", json={"question": "   "})
    assert response.status_code == 400
    assert response.mimetype == "application/json"


def test_a_blocked_visitor_is_refused(client, app_module, monkeypatch, streaming):
    monkeypatch.setattr(app_module, "is_blocked", lambda: True)
    assert ask(client).status_code == 403


def test_the_anonymous_allowance_still_counts_down(client, app_module,
                                                   monkeypatch, streaming):
    """The counter lives in the session, and a session write after the first
    byte never reaches the browser — so the claim has to happen before the
    stream opens, or free messages become unlimited."""
    monkeypatch.setattr(app_module, "ANONYMOUS_MESSAGE_LIMIT", 2)
    assert ask(client).status_code == 200
    assert ask(client).status_code == 200
    refused = ask(client)
    assert refused.status_code == 402
    assert refused.get_json()["sign_in_required"] is True
    assert len(streaming.asked) == 2, "a refused message still reached the model"


# --- the widget ------------------------------------------------------------

def test_the_widget_streams_and_keeps_a_way_back(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    body = client.get("/").get_data(as_text=True)
    assert "/mykola/chat/stream" in body
    assert "/mykola/chat" in body, "no fallback for a server that cannot stream"
    assert "getReader" in body
