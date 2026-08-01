"""Persisted identities: the users table and sign-in (kuantorflow#148).

A Google sign-in now writes a row keyed on the OIDC subject, and the session
carries the user's id plus the name claims Mykola addresses them by.
"""

import types

import pytest
from flask import session

import utils


def _google(app_module, monkeypatch, info):
    """Force Google auth on and stub the token exchange with these claims."""
    monkeypatch.setattr(app_module, "GOOGLE_AUTH_AVAILABLE", True)
    fake = types.SimpleNamespace(
        google=types.SimpleNamespace(
            authorize_access_token=lambda: {"userinfo": info}))
    monkeypatch.setattr(app_module, "oauth", fake)


CLAIMS = {
    "sub": "110169484474386276334",
    "email": "anna@example.com",
    "name": "Anna Maria Kowalska",
    "given_name": "Anna Maria",
    "family_name": "Kowalska",
    "picture": "https://example.com/a.jpg",
}


# --- what a sign-in records -------------------------------------------------

def test_sign_in_records_the_user(client, app_module, monkeypatch):
    recorded = {}

    def fake_upsert(google_sub, email, **claims):
        recorded.update(sub=google_sub, email=email, **claims)
        return 7, None

    _google(app_module, monkeypatch, CLAIMS)
    monkeypatch.setattr(app_module, "upsert_user", fake_upsert)

    resp = client.get("/auth/google/callback")
    assert resp.status_code == 302
    assert recorded == {
        "sub": "110169484474386276334",
        "email": "anna@example.com",
        "display_name": "Anna Maria Kowalska",
        "given_name": "Anna Maria",
        "family_name": "Kowalska",
    }
    with client.session_transaction() as sess:
        assert sess["user"]["id"] == 7
        assert sess["user"]["given_name"] == "Anna Maria"
        assert sess["user"]["preferred_name"] is None


def test_sign_in_survives_a_dead_database(client, app_module, monkeypatch):
    """A failed upsert must never cost the user their login."""
    def boom(*a, **k):
        raise RuntimeError("db unreachable")

    _google(app_module, monkeypatch, CLAIMS)
    monkeypatch.setattr(app_module, "upsert_user", boom)

    resp = client.get("/auth/google/callback")
    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert sess["user"]["id"] is None          # readers must tolerate this
        assert sess["user"]["email"] == "anna@example.com"


def test_placeholder_name_is_never_stored(client, app_module, monkeypatch):
    """'there' is a rendering placeholder, not somebody's name."""
    recorded = {}
    _google(app_module, monkeypatch, {"sub": "s", "email": "nameless@example.com"})
    monkeypatch.setattr(app_module, "upsert_user",
                        lambda sub, email, **c: recorded.update(c) or (1, None))

    client.get("/auth/google/callback")
    assert recorded == {"display_name": None, "given_name": None,
                        "family_name": None}
    with client.session_transaction() as sess:
        assert sess["user"]["name"] == "there"     # display only


def test_blank_claims_become_null(client, app_module, monkeypatch):
    recorded = {}
    _google(app_module, monkeypatch,
            {"sub": "s", "email": "x@example.com", "name": "  ",
             "given_name": "", "family_name": "   "})
    monkeypatch.setattr(app_module, "upsert_user",
                        lambda sub, email, **c: recorded.update(c) or (1, None))

    client.get("/auth/google/callback")
    assert set(recorded.values()) == {None}


def test_sign_in_without_a_subject_is_not_recorded(client, app_module, monkeypatch):
    """`sub` is mandatory in OIDC — if it is missing something is wrong, but
    the visitor should still get in rather than see an error."""
    called = []
    _google(app_module, monkeypatch, {"email": "x@example.com", "name": "X"})
    monkeypatch.setattr(app_module, "upsert_user",
                        lambda *a, **k: called.append(1) or (1, None))

    resp = client.get("/auth/google/callback")
    assert resp.status_code == 302 and called == []
    with client.session_transaction() as sess:
        assert sess["user"]["id"] is None


# --- what Mykola calls them -------------------------------------------------

@pytest.mark.parametrize("user,expected", [
    ({"preferred_name": "Ann", "given_name": "Anna Maria",
      "name": "Anna Maria Kowalska"}, "Ann"),          # their own choice wins
    ({"given_name": "Anna Maria", "name": "Anna Maria Kowalska"}, "Anna Maria"),
    ({"name": "Anna Maria Kowalska"}, "Anna"),          # fallback: first word
    ({"preferred_name": "  ", "given_name": "Anna"}, "Anna"),  # blanks skipped
    ({"name": "there"}, "there"),                       # the placeholder
    ({}, None),
])
def test_first_name_resolution_order(app_module, user, expected):
    with app_module.app.test_request_context():
        session["user"] = user
        assert app_module._current_first_name() == expected


def test_anonymous_visitor_has_no_first_name(app_module):
    with app_module.app.test_request_context():
        assert app_module._current_first_name() is None


# --- the query itself -------------------------------------------------------

class _Cursor:
    def __init__(self):
        self.statements = []
        self.lastrowid = 42

    def execute(self, sql, params=None):
        self.statements.append((" ".join(sql.split()), params))

    def fetchone(self):
        return ("Ann",)

    def close(self):
        pass


def test_upsert_never_overwrites_the_preferred_name(monkeypatch):
    """preferred_name is the user's own choice (#148 / ai_agent#62) — a Google
    sign-in supplies no such claim and must leave it alone."""
    cursor = _Cursor()
    conn = types.SimpleNamespace(cursor=lambda: cursor, commit=lambda: None,
                                 close=lambda: None)
    monkeypatch.setattr(utils, "get_db_connection", lambda: conn)

    user_id, preferred = utils.upsert_user("sub-1", "a@example.com", "A B", "A", "B")

    assert (user_id, preferred) == (42, "Ann")
    upsert = cursor.statements[0][0]
    assert "ON DUPLICATE KEY UPDATE" in upsert
    assert "preferred_name" not in upsert, "sign-in must not touch preferred_name"
    # without LAST_INSERT_ID(id) an update leaves lastrowid at 0 and the caller
    # would put a bogus id in the session
    assert "id = LAST_INSERT_ID(id)" in upsert
    assert "last_seen_at = NOW()" in upsert


def test_upsert_is_keyed_on_the_google_subject(monkeypatch):
    """Not on the email — an email change must update the row, not fork it."""
    cursor = _Cursor()
    conn = types.SimpleNamespace(cursor=lambda: cursor, commit=lambda: None,
                                 close=lambda: None)
    monkeypatch.setattr(utils, "get_db_connection", lambda: conn)

    utils.upsert_user("sub-1", "a@example.com")
    insert, params = cursor.statements[0]
    assert insert.index("google_sub") < insert.index("email")
    assert params[0] == "sub-1"
    assert "email = VALUES(email)" in insert, "an email change must update the row"
