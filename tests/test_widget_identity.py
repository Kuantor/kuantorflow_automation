"""Mykola's widget must not replay another identity's conversation (#170).

The widget keeps its whole thread in localStorage. Nothing on the server was
leaking it — the transcript was replayed by the browser, because the stored
state carried no record of who it belonged to. It is now stamped with an
opaque per-identity token and restored only on a match, which is the only
thing that covers a sign-out the browser never sees: a session expiring,
another tab, or an identity dropped server-side.
"""

import re

from conftest import TEST_USER_EMAIL, TEST_USER_ID


def _token(app_module, user=None):
    """The identity token this session would be stamped with."""
    with app_module.app.test_request_context("/"):
        from flask import session

        if user is not None:
            session["user"] = user
        return app_module._identity_token()


def _widget(resp_client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    return resp_client.get("/").get_data(as_text=True)


# --- the token itself ---------------------------------------------------------

def test_anonymous_visitors_get_no_token(app_module):
    assert _token(app_module) is None


def test_a_signed_in_user_gets_an_opaque_token(app_module):
    token = _token(app_module, {"email": TEST_USER_EMAIL, "name": "Test User"})
    assert re.fullmatch(r"[0-9a-f]{16}", token or ""), \
        "the stamp must be a short hex digest"


def test_the_token_reveals_nothing_about_the_user(app_module):
    """It lands in localStorage, which survives sign-out and is readable by
    anything on the origin — so it must not be the email or the id."""
    user = {"id": 7, "email": TEST_USER_EMAIL, "name": "Test User"}
    token = _token(app_module, user)
    assert TEST_USER_EMAIL not in token
    assert TEST_USER_EMAIL.split("@")[0] not in token
    assert "test" not in token and "user" not in token


def test_different_users_get_different_tokens(app_module):
    one = _token(app_module, {"id": 7, "email": "one@example.com"})
    two = _token(app_module, {"id": 8, "email": "two@example.com"})
    assert one != two


def test_the_same_user_gets_a_stable_token(app_module):
    user = {"id": 7, "email": TEST_USER_EMAIL}
    assert _token(app_module, user) == _token(app_module, dict(user))


def test_the_id_identifies_the_user_when_present(app_module):
    """Keyed on the id where there is one (#148), so the token survives an
    email change the way the users row does."""
    same_id = _token(app_module, {"id": 7, "email": "before@example.com"})
    renamed = _token(app_module, {"id": 7, "email": "after@example.com"})
    assert same_id == renamed


def test_an_email_only_session_still_gets_a_token(app_module):
    """A sign-in whose users row could not be written has id None (#148); it
    still needs a stamp, or its thread would be treated as anonymous."""
    assert _token(app_module, {"id": None, "email": TEST_USER_EMAIL}) is not None


# --- what the page hands the widget -------------------------------------------

def test_the_page_declares_null_for_anonymous(client, app_module, monkeypatch):
    body = _widget(client, app_module, monkeypatch)
    assert "var MYKOLA_IDENTITY = null;" in body


def test_the_page_declares_the_token_when_signed_in(user_client, app_module,
                                                    monkeypatch):
    body = _widget(user_client, app_module, monkeypatch)
    # The whole identity the fixture signs in as, not just its email: the
    # token follows the user id where there is one, and user_client has
    # carried one since kuantorflow#89 added it.
    token = _token(app_module, {"id": TEST_USER_ID, "name": "Test User",
                                "email": TEST_USER_EMAIL})
    assert f'var MYKOLA_IDENTITY = "{token}";' in body


def test_the_stored_state_is_stamped(client, app_module, monkeypatch):
    body = _widget(client, app_module, monkeypatch)
    saved_state = body.split("function saveWidgetState()")[1] \
                      .split("\n            function ")[0]
    assert "identity: MYKOLA_IDENTITY" in saved_state


def test_a_mismatched_thread_is_dropped_on_load(client, app_module, monkeypatch):
    body = _widget(client, app_module, monkeypatch)
    load_state = body.split("function loadWidgetState()")[1] \
                     .split("\n            function ")[0]
    assert "!== MYKOLA_IDENTITY" in load_state, \
        "the stored thread must be checked against the current identity"
    assert "removeItem(WIDGET_STORAGE_KEY)" in load_state, \
        "a mismatched thread must be cleared, not just ignored"
    assert "return null" in load_state


def test_an_unstamped_thread_is_dropped_rather_than_read_as_anonymous(
        client, app_module, monkeypatch):
    """The case that made the bug survive its own fix: a thread written before
    the stamp existed has no `identity` key, and `state.identity || null`
    turns that into the same null an anonymous visitor carries. The two must
    be told apart, or the signed-in transcript stays on screen for exactly the
    anonymous visitor a sign-out just created."""
    body = _widget(client, app_module, monkeypatch)
    load_state = body.split("function loadWidgetState()")[1] \
                     .split("\n            function ")[0]
    assert 'hasOwnProperty.call(state, "identity")' in load_state, \
        "an absent identity key must be distinguished from an explicit null"
    assert "state.identity || null" not in load_state, \
        "|| null collapses the unstamped case into the anonymous one"


def test_the_greeting_is_still_anonymous_for_a_signed_out_visitor(
        client, app_module, monkeypatch):
    """The server-rendered greeting was never the problem — this locks in that
    it stays nameless, since it is what a dropped thread falls back to."""
    body = _widget(client, app_module, monkeypatch)
    # tojson escapes the apostrophe, hence the '
    assert 'var GREETING = "Good day! I\\u0027m Mykola' in body


def test_the_greeting_still_names_a_signed_in_visitor(user_client, app_module,
                                                      monkeypatch):
    body = _widget(user_client, app_module, monkeypatch)
    assert 'var GREETING = "Good day, Test User!' in body
