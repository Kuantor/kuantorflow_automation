"""The session cookie's protective flags (kuantorflow#274).

The cookie carries the keyword gate pass and the signed-in Google identity, so
what matters is not that three config keys hold three values but that the
*header the browser receives* asks for the protection. The last test is
therefore the one worth keeping if the others ever become tedious.
"""

import pytest


def test_secure_httponly_and_samesite_are_configured(app_module):
    config = app_module.app.config
    assert config["SESSION_COOKIE_SECURE"] is True
    assert config["SESSION_COOKIE_HTTPONLY"] is True
    assert config["SESSION_COOKIE_SAMESITE"] == "Lax"


def test_samesite_is_not_strict(app_module):
    """Strict would break Google sign-in, so this is a rule, not a preference.

    Authlib keeps the OAuth state and nonce in this session, and the callback is
    a top-level GET navigation from accounts.google.com. Under Strict the
    browser withholds the cookie on exactly that navigation, the state is gone
    when Authlib checks it, and sign-in fails with a silent redirect.
    """
    assert app_module.app.config["SESSION_COOKIE_SAMESITE"] != "Strict"


@pytest.mark.parametrize("raw, expected", [
    ("0", False), ("false", False), ("False", False), ("no", False),
    ("off", False), ("", False), (" 0 ", False),
    ("1", True), ("true", True), ("yes", True), ("anything", True),
])
def test_bool_env_reads_the_environment(app_module, monkeypatch, raw, expected):
    monkeypatch.setenv("KF_TEST_FLAG", raw)
    assert app_module._bool_env("KF_TEST_FLAG", not expected) is expected


def test_bool_env_unset_keeps_the_default(app_module, monkeypatch):
    monkeypatch.delenv("KF_TEST_FLAG", raising=False)
    assert app_module._bool_env("KF_TEST_FLAG", True) is True
    assert app_module._bool_env("KF_TEST_FLAG", False) is False


def test_the_session_cookie_is_sent_with_all_three_attributes(fresh_client,
                                                              monkeypatch):
    """What the browser is actually told, which is the only thing that
    protects anybody.

    It used to enter the keyword, because that was the first thing in the app
    that wrote a session. kuantorflow#199 removed the gate, so this drives
    #164's anonymous message counter instead -- now the first thing an
    anonymous visitor does that writes one. The model call is replaced by a
    stub: the point here is the cookie, and a real message costs Opus tokens.

    This matters **more** now rather than less. With the gate gone this cookie
    is the app's entire authentication state, and `is_admin()` reads
    `email_verified` from inside it -- so the signature and these three flags
    are all that stand between a visitor and an admin session (#445).
    """
    monkeypatch.setattr("chat.MYKOLA_AVAILABLE", True)
    monkeypatch.setattr("chat._agent_answer",
                        lambda q, h: {"response": "Indeed.", "history": h,
                                      "sources": []})
    monkeypatch.setattr("utils.claim_anonymous_message", lambda limit: (True, 1))

    response = fresh_client.post("/mykola/chat", json={"question": "hello"})

    assert response.status_code == 200
    cookie = response.headers["Set-Cookie"]
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie
