"""The admin identity (kuantorflow#158).

ADMIN_EMAILS in .env decides who is an administrator. Nothing uses the
privilege yet — #126 (blocking) and #162 (deleting any card) are what will
ask — so these tests pin the resolution itself, which is the part that has to
be right before anything is built on it.

The check fails closed: not signed in, no verified claim, or not listed all
mean "not admin".
"""

import pytest
from flask import render_template_string, session


ADMIN = "admin@example.com"


def _signed_in(app_module, user):
    """Resolve is_admin() for a request carrying this session identity."""
    with app_module.app.test_request_context("/"):
        if user is not None:
            session["user"] = user
        return app_module.is_admin()


def _admin_session(email=ADMIN, **overrides):
    user = {"id": 1, "name": "Admin", "email": email, "email_verified": True}
    user.update(overrides)
    return user


@pytest.fixture()
def admins(app_module, monkeypatch):
    """Configure ADMIN_EMAILS for the test."""
    def configure(raw):
        monkeypatch.setattr(app_module, "ADMIN_EMAILS",
                            app_module._admin_emails(raw))
    configure(ADMIN)
    return configure


# --- parsing the setting ------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("admin@example.com", {"admin@example.com"}),
    ("one@example.com,two@example.com", {"one@example.com", "two@example.com"}),
    ("  one@example.com ,\ttwo@example.com  ", {"one@example.com",
                                                "two@example.com"}),
    ("Admin@Example.COM", {"admin@example.com"}),
    ("", set()),
    ("   ", set()),
    (",,  ,", set()),
])
def test_admin_emails_parsing(app_module, raw, expected):
    assert set(app_module._admin_emails(raw)) == expected


def test_an_unset_variable_yields_no_admins(app_module, monkeypatch):
    """Unset must mean 'no admin', never a crash and never 'everyone'."""
    monkeypatch.delenv("ADMIN_EMAILS", raising=False)
    assert set(app_module._admin_emails()) == set()


# --- who is an admin ----------------------------------------------------------

def test_a_listed_verified_user_is_an_admin(app_module, admins):
    assert _signed_in(app_module, _admin_session()) is True


def test_an_unlisted_user_is_not(app_module, admins):
    assert _signed_in(app_module, _admin_session(email="someone@example.com")) \
        is False


def test_an_anonymous_visitor_is_never_an_admin(app_module, admins):
    assert _signed_in(app_module, None) is False


def test_case_and_whitespace_in_the_session_email_do_not_matter(app_module,
                                                                admins):
    assert _signed_in(app_module, _admin_session(email="  Admin@Example.COM ")) \
        is True


def test_no_admins_configured_means_nobody_is_an_admin(app_module, admins):
    admins("")
    assert _signed_in(app_module, _admin_session()) is False


def test_one_of_several_configured_admins_matches(app_module, admins):
    admins("first@example.com, admin@example.com")
    assert _signed_in(app_module, _admin_session()) is True


# --- the verified-email requirement -------------------------------------------

def test_an_unverified_address_never_matches(app_module, admins):
    """The point of the claim: holding a listed address is not enough if
    Google has not verified it."""
    assert _signed_in(app_module, _admin_session(email_verified=False)) is False


def test_a_session_without_the_claim_is_not_an_admin(app_module, admins):
    """Sessions predating #158 carry no `email_verified`. Failing closed means
    the owner signs in once more rather than silently gaining the privilege —
    or silently keeping it if the address was later unverified."""
    user = _admin_session()
    del user["email_verified"]
    assert _signed_in(app_module, user) is False


@pytest.mark.parametrize("claim, expected", [
    (True, True),
    (False, False),
    ("true", True),
    ("True", True),
    ("false", False),
    ("", False),
    (None, False),
    ("yes", False),
])
def test_the_verified_claim_is_read_strictly(app_module, claim, expected):
    """`bool("false")` is True, so the claim must be compared, not trusted for
    truthiness — some userinfo responses send it as a string."""
    assert app_module._email_verified({"email_verified": claim}) is expected


def test_a_missing_claim_is_not_verified(app_module):
    assert app_module._email_verified({}) is False


@pytest.mark.parametrize("claim, stored", [(True, True), ("true", True),
                                           (False, False), ("false", False)])
def test_the_sign_in_stores_the_claim(client, app_module, monkeypatch, claim,
                                      stored):
    """is_admin() reads the session, so the callback has to put it there."""
    import types

    monkeypatch.setattr(app_module, "GOOGLE_AUTH_AVAILABLE", True)
    monkeypatch.setattr(app_module, "upsert_user",
                        lambda *a, **k: (1, None))
    info = {"sub": "s1", "email": ADMIN, "name": "Admin",
            "email_verified": claim}
    monkeypatch.setattr(app_module, "oauth", types.SimpleNamespace(
        google=types.SimpleNamespace(
            authorize_access_token=lambda: {"userinfo": info})))

    assert client.get("/auth/google/callback").status_code == 302
    with client.session_transaction() as sess:
        assert sess["user"]["email_verified"] is stored


# --- templates ----------------------------------------------------------------

def test_is_admin_is_available_to_templates(app_module, admins):
    with app_module.app.test_request_context("/"):
        session["user"] = _admin_session()
        assert render_template_string("{{ is_admin }}") == "True"


def test_templates_see_false_for_everyone_else(app_module, admins):
    with app_module.app.test_request_context("/"):
        assert render_template_string("{{ is_admin }}") == "False"


def test_a_rendered_page_carries_the_flag(client, app_module, admins):
    """Through the real context processor on a real page, not just directly."""
    with client.session_transaction() as sess:
        sess["user"] = _admin_session()
    assert client.get("/").status_code == 200
    with app_module.app.test_request_context("/"):
        session["user"] = _admin_session()
        assert app_module.inject_auth()["is_admin"] is True
