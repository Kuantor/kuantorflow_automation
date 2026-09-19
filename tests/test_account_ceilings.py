"""Signing in raises a ceiling rather than removing it (kuantorflow#447).

Three paid actions had no per-account limit at all: Mykola chat, the
welcome-back recap, and the notes upload whose parse calls Claude. #164 and
#200 left it that way on purpose -- while the keyword gate was on, a signed-in
visitor was by construction somebody who had been handed a keyword and then
chosen to sign in. #199 removes the gate and the premise with it.

A Google account is a cost barrier rather than a bot barrier, so the exemption
was worth exactly what an account costs to obtain. These tests are that the
exemption is gone.

**The stub in `conftest.py` allows everything by default**, so each test here
patches `utils.claim_action` itself to say what the ceiling did -- which also
keeps them honest about *which* action was claimed.
"""

import pytest

import chat  # noqa: F401  (imported for the fixture's patch targets)


@pytest.fixture()
def mykola(app_module, monkeypatch):
    """Mykola available, with the model call replaced by a counter."""
    monkeypatch.setattr("chat.MYKOLA_AVAILABLE", True)
    calls = []
    monkeypatch.setattr("chat._agent_answer",
                        lambda q, h: calls.append(q) or
                        {"response": "Indeed.", "history": h, "sources": []})
    monkeypatch.setattr("utils.claim_anonymous_message", lambda limit: (True, 1))

    # `/mykola/chat/stream` asks for the agent *before* it asks the guards, so
    # without this it raises on a missing ai_agent checkout and never reaches
    # the claim this file is about.
    class _Agent:
        def stream_answer(self, *a, **k):
            yield {"delta": "Indeed."}

        def answer(self, *a, **k):
            return {"response": "Indeed.", "history": [], "sources": []}

    monkeypatch.setattr("chat.get_mykola", _Agent)
    return calls



def _refusing(monkeypatch, action):
    """Make one action's ceiling refuse, and record what was asked."""
    asked = []

    def claim(name, user_id, limit, amount=1):
        asked.append((name, user_id, limit, amount))
        return (False, limit) if name == action else (True, 0)

    monkeypatch.setattr("utils.claim_action", claim)
    return asked


def _allowing(monkeypatch):
    asked = []

    def claim(name, user_id, limit, amount=1):
        asked.append((name, user_id, limit, amount))
        return True, 0

    monkeypatch.setattr("utils.claim_action", claim)
    return asked


# --- the chat --------------------------------------------------------------

def test_a_signed_in_chat_is_claimed_against_the_account(user_client,
                                                         monkeypatch, mykola):
    asked = _allowing(monkeypatch)

    user_client.post("/mykola/chat", json={"question": "hello"})

    import utils
    import web
    assert (utils.CHAT, 7, web.CHAT_USER_DAILY, 1) in asked


def test_and_refused_once_the_account_has_spent_its_day(user_client,
                                                        monkeypatch, mykola):
    import utils
    import web
    _refusing(monkeypatch, utils.CHAT)

    r = user_client.post("/mykola/chat", json={"question": "hello"})

    assert r.status_code == 402
    assert web.CHAT_USER_LIMIT_PROMPT in r.get_json()["error"]


def test_the_refusal_does_not_offer_a_sign_in(user_client, monkeypatch, mykola):
    """They already did. #164's 402 carries `sign_in_required` so the widget
    can offer something; an account that has spent its own day has nothing to
    be offered, so the answer is tomorrow."""
    import utils
    _refusing(monkeypatch, utils.CHAT)

    r = user_client.post("/mykola/chat", json={"question": "hello"})

    assert r.get_json()["sign_in_required"] is False


@pytest.mark.parametrize("path", ["/mykola/chat", "/api/chat",
                                  "/mykola/chat/stream"])
def test_every_chat_route_claims_exactly_once(path, user_client, monkeypatch,
                                              mykola):
    """Three endpoints, one allowance. They share `_mykola_chat_inputs()`
    precisely so a second one cannot acquire its own set of these rules --
    and so a streamed message does not cost two."""
    import utils
    asked = _allowing(monkeypatch)

    try:
        user_client.post(path, json={"question": "hello"})
    except Exception:
        # The SSE route reaches for the real agent once the guards have let it
        # through, and this suite has no ai_agent checkout. That is downstream
        # of the claim, which is the whole of what this test is about: the
        # count below is taken either way.
        pass

    chats = [a for a in asked if a[0] == utils.CHAT]
    assert len(chats) == 1, "claimed %d times on %s" % (len(chats), path)


def test_an_anonymous_message_is_not_claimed_against_an_account(client,
                                                                monkeypatch,
                                                                mykola):
    """They meet #164's allowances instead, which is a different question and
    a different row."""
    import utils
    asked = _allowing(monkeypatch)

    client.post("/mykola/chat", json={"question": "hello"})

    assert not [a for a in asked if a[0] == utils.CHAT]


# --- the recap -------------------------------------------------------------

def test_a_recap_is_claimed_against_the_account(user_client, monkeypatch,
                                                mykola):
    import utils
    import web
    asked = _allowing(monkeypatch)
    monkeypatch.setattr("chat._said_farewell_today", lambda: False)
    monkeypatch.setattr("chat._read_user_logs", lambda **k: "some history")

    user_client.post("/mykola/recap", json={})

    assert (utils.RECAP, 7, web.RECAP_USER_DAILY, 1) in asked


def test_a_refused_recap_is_silence_rather_than_an_error(user_client,
                                                         monkeypatch, mykola):
    """Every other thing that can go wrong here answers `{"recap": None}` and
    the widget keeps its normal greeting. A ceiling is not more interesting to
    a learner than an older agent or an empty history."""
    import utils
    _refusing(monkeypatch, utils.RECAP)
    monkeypatch.setattr("chat._said_farewell_today", lambda: False)
    monkeypatch.setattr("chat._read_user_logs", lambda **k: "some history")

    r = user_client.post("/mykola/recap", json={})

    assert r.status_code == 200
    assert r.get_json() == {"recap": None}


def test_a_farewell_costs_no_recap(user_client, monkeypatch, mykola):
    """The ordering that is easy to get wrong, and that I did get wrong first.

    `_said_farewell_today()` answers deterministically with no model call, so
    claiming before it would spend a slot on a sentence the model never wrote.
    Every guard sits after the free refusals and immediately before the call
    it pays for.
    """
    import utils
    asked = _allowing(monkeypatch)
    monkeypatch.setattr("chat._said_farewell_today", lambda: True)

    r = user_client.post("/mykola/recap", json={})

    assert "rest" in (r.get_json()["recap"] or ""), "not the farewell answer"
    assert not [a for a in asked if a[0] == utils.RECAP], (
        "a deterministic answer spent a recap slot")


def test_an_anonymous_visitor_is_not_claimed_a_recap(client, monkeypatch,
                                                     mykola):
    """They never get one at all, so there is nothing to count."""
    import utils
    asked = _allowing(monkeypatch)

    client.post("/mykola/recap", json={})

    assert not [a for a in asked if a[0] == utils.RECAP]


# --- the notes upload ------------------------------------------------------

def _upload(client, name="notes.txt", body=b"brittle - krykhkyi"):
    import io
    return client.post("/", data={"action": "upload_notes", "topic": "vocab",
                                  "notes_file": (io.BytesIO(body), name)},
                       content_type="multipart/form-data")


def test_an_upload_is_claimed_against_the_account(user_client, monkeypatch):
    import utils
    import web
    asked = _allowing(monkeypatch)

    _upload(user_client)

    assert (utils.UPLOAD, 7, web.UPLOAD_USER_DAILY, 1) in asked


def test_a_refused_upload_never_reads_the_file(user_client, monkeypatch):
    """#200's own argument: which file calls Claude cannot be known without
    parsing it, and parsing is the thing being paid for. So a refusal past the
    ceiling has to land before `file.read()`, exactly where #125's does."""
    import utils
    import web
    _refusing(monkeypatch, utils.UPLOAD)
    parsed = []
    monkeypatch.setattr("parsers.parse_notes_preview",
                        lambda *a, **k: parsed.append(a) or ([], ""))

    body = _upload(user_client).get_data(as_text=True)

    assert not parsed, "the file was parsed after the ceiling refused it"
    assert web.UPLOAD_USER_LIMIT_PROMPT in body


def test_an_anonymous_upload_is_refused_before_the_ceiling_is_asked(
        client, monkeypatch):
    """#125 refuses it for having no account at all, which is the cheaper and
    more informative answer -- and means an anonymous flood cannot even reach
    the counter."""
    import utils
    asked = _allowing(monkeypatch)

    _upload(client)

    assert not [a for a in asked if a[0] == utils.UPLOAD]
