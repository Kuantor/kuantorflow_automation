"""How much of Mykola an anonymous visitor gets (kuantorflow#164).

Two limits: a per-session allowance they meet first, and a daily ceiling
across all anonymous visitors that actually bounds the Anthropic bill. Both
are checked before the model is called, so a refused message costs nothing.
"""

import pytest


@pytest.fixture()
def mykola(app_module, monkeypatch):
    """Mykola available, with the model call replaced by a counter."""
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    calls = []
    monkeypatch.setattr(app_module, "_agent_answer",
                        lambda q, h: calls.append(q) or
                        {"response": "Indeed.", "history": h, "sources": []})
    # the daily ceiling is exercised on its own below; keep the DB out of it
    monkeypatch.setattr(app_module, "claim_anonymous_message",
                        lambda limit: (True, 1))
    return calls


def _ask(client, text="what does brittle mean?"):
    return client.post("/mykola/chat", json={"question": text})


# --- the per-session allowance ----------------------------------------------

def test_anonymous_visitor_is_allowed_up_to_the_limit(client, app_module,
                                                      monkeypatch, mykola):
    monkeypatch.setattr(app_module, "ANONYMOUS_MESSAGE_LIMIT", 3)
    for i in range(3):
        assert _ask(client).status_code == 200, f"message {i + 1} refused"
    assert len(mykola) == 3


def test_the_next_message_is_refused_without_calling_the_model(client, app_module,
                                                               monkeypatch, mykola):
    """The whole point: a refused message must cost nothing."""
    monkeypatch.setattr(app_module, "ANONYMOUS_MESSAGE_LIMIT", 2)
    _ask(client), _ask(client)
    assert len(mykola) == 2

    resp = _ask(client)
    assert resp.status_code == 402
    body = resp.get_json()
    assert body["sign_in_required"] is True
    assert "Sign in" in body["error"]
    assert len(mykola) == 2, "the model must not be called for a refused message"


def test_a_refused_message_does_not_consume_more_quota(client, app_module,
                                                       monkeypatch, mykola):
    monkeypatch.setattr(app_module, "ANONYMOUS_MESSAGE_LIMIT", 1)
    _ask(client)
    for _ in range(3):
        _ask(client)
    with client.session_transaction() as sess:
        assert sess["anon_messages"] == 1


def test_a_signed_in_visitor_is_never_limited(user_client, app_module,
                                              monkeypatch, mykola):
    monkeypatch.setattr(app_module, "ANONYMOUS_MESSAGE_LIMIT", 1)
    for _ in range(5):
        assert _ask(user_client).status_code == 200
    assert len(mykola) == 5
    with user_client.session_transaction() as sess:
        assert "anon_messages" not in sess


def test_zero_disables_the_session_limit(client, app_module, monkeypatch, mykola):
    monkeypatch.setattr(app_module, "ANONYMOUS_MESSAGE_LIMIT", 0)
    for _ in range(6):
        assert _ask(client).status_code == 200


# --- the daily ceiling ------------------------------------------------------

def test_daily_ceiling_refuses_with_its_own_message(client, app_module,
                                                    monkeypatch, mykola):
    monkeypatch.setattr(app_module, "claim_anonymous_message",
                        lambda limit: (False, 200))
    resp = _ask(client)
    assert resp.status_code == 402
    body = resp.get_json()
    assert body["sign_in_required"] is True
    assert "come back tomorrow" in body["error"]
    assert mykola == [], "the model must not be called once the day is spent"


def test_the_daily_ceiling_ignores_signed_in_visitors(user_client, app_module,
                                                      monkeypatch, mykola):
    def fail(limit):
        raise AssertionError("signed-in traffic must not touch the day's count")
    monkeypatch.setattr(app_module, "claim_anonymous_message", fail)
    assert _ask(user_client).status_code == 200


def test_a_dead_database_does_not_silence_mykola(client, app_module,
                                                 monkeypatch, mykola):
    """Fail open: an unreachable database must not stop everyone chatting."""
    def boom(limit):
        raise RuntimeError("db unreachable")
    monkeypatch.setattr(app_module, "claim_anonymous_message", boom)
    assert _ask(client).status_code == 200
    assert len(mykola) == 1


def test_the_refusal_is_logged(client, app_module, monkeypatch, mykola, action_logs):
    monkeypatch.setattr(app_module, "ANONYMOUS_MESSAGE_LIMIT", 1)
    _ask(client)
    _ask(client)
    lines = (action_logs / "dict.log").read_text(encoding="utf-8")
    assert "LIMIT kind=session used=1 limit=1" in lines


# --- the widget -------------------------------------------------------------

def test_widget_offers_sign_in_when_the_allowance_runs_out(client, app_module,
                                                           monkeypatch):
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    body = client.get("/").get_data(as_text=True)
    assert 'id="mykola-signin-required"' in body
    assert "function showSignInRequired()" in body
    # The offer is wired to whatever renders a chat error. Since ai_agent#50
    # that is one function shared by the streamed and whole-answer paths, so
    # this asserts the wiring rather than the line it used to live on — the
    # refusal reaches the learner the same way however the answer travelled.
    assert "if (data && data.sign_in_required) showSignInRequired();" in body


def test_signed_in_widget_has_no_sign_in_offer(user_client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    body = user_client.get("/").get_data(as_text=True)
    assert 'id="mykola-signin-required"' not in body
