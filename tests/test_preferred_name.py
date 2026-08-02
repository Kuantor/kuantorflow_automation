"""
Mykola remembers what to call you — the KuantorFlow half (ai_agent#62).

The tool lives in ai_agent; what is tested here is the saver KuantorFlow
injects into it: who may store a name, where it goes, and that the change is
visible to the very next message rather than only after signing in again.

The agent-side half (cleaning, clearing, the refusal becoming an in-character
answer) is `ai_agent/test_preferred_name.py`.
"""

import pytest
from flask import session

import utils
from conftest import TEST_USER_ID, TEST_USER_EMAIL


@pytest.fixture()
def stored_names(app_module, monkeypatch):
    """Capture set_preferred_name() instead of writing to MySQL."""
    calls = []

    def fake(user_id, name):
        calls.append((user_id, name))
        return True

    monkeypatch.setattr(app_module, "set_preferred_name", fake)
    return calls


def _signed_in(app_module, **extra):
    ctx = app_module.app.test_request_context("/mykola/chat")
    ctx.push()
    session["user"] = {"id": TEST_USER_ID, "email": TEST_USER_EMAIL, **extra}
    return ctx


# --- who may store a name -----------------------------------------------


def test_an_anonymous_learner_is_refused(app_module, stored_names):
    """Raised, not returned: the agent turns an exception into an error status
    Mykola relays, so he says he cannot remember it instead of pretending."""
    with app_module.app.test_request_context("/mykola/chat"):
        with pytest.raises(PermissionError) as excinfo:
            app_module._save_preferred_name_from_chat("Ann")
    assert "sign in" in str(excinfo.value).lower()
    assert stored_names == [], "nothing may be written for a visitor with no account"


def test_a_signed_in_learner_is_stored(app_module, stored_names):
    ctx = _signed_in(app_module)
    try:
        assert app_module._save_preferred_name_from_chat("Ann") == "Ann"
        assert stored_names == [(TEST_USER_ID, "Ann")]
    finally:
        ctx.pop()


def test_clearing_stores_none(app_module, stored_names):
    """'Use my real name again' must clear the column, not write the literal
    first name — otherwise a later Google name change is shadowed for ever."""
    ctx = _signed_in(app_module)
    try:
        app_module._save_preferred_name_from_chat(None)
        assert stored_names == [(TEST_USER_ID, None)]
    finally:
        ctx.pop()


def test_a_missing_account_is_reported_not_swallowed(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "set_preferred_name",
                        lambda user_id, name: False)
    ctx = _signed_in(app_module)
    try:
        with pytest.raises(RuntimeError):
            app_module._save_preferred_name_from_chat("Ann")
    finally:
        ctx.pop()


# --- the change is visible immediately ----------------------------------


def test_the_new_name_is_used_from_the_next_message(app_module, stored_names):
    """_current_first_name() reads the session, so the saver has to update it —
    otherwise the name would only take effect after signing in again."""
    ctx = _signed_in(app_module, given_name="Anna Maria")
    try:
        assert app_module._current_first_name() == "Anna Maria"
        app_module._save_preferred_name_from_chat("Ann")
        assert app_module._current_first_name() == "Ann"
    finally:
        ctx.pop()


def test_clearing_falls_back_to_the_account_name(app_module, stored_names):
    ctx = _signed_in(app_module, given_name="Anna Maria",
                     preferred_name="Ann")
    try:
        assert app_module._current_first_name() == "Ann"
        app_module._save_preferred_name_from_chat(None)
        assert app_module._current_first_name() == "Anna Maria"
    finally:
        ctx.pop()


def test_the_rest_of_the_session_survives(app_module, stored_names):
    """The saver rewrites session['user']; it must not drop what was there."""
    ctx = _signed_in(app_module, given_name="Anna Maria", email_verified=True)
    try:
        app_module._save_preferred_name_from_chat("Ann")
        assert session["user"]["email"] == TEST_USER_EMAIL
        assert session["user"]["email_verified"] is True
        assert session["user"]["id"] == TEST_USER_ID
    finally:
        ctx.pop()


def test_the_change_is_logged(app_module, stored_names, action_logs):
    ctx = _signed_in(app_module)
    try:
        app_module._save_preferred_name_from_chat("Ann")
    finally:
        ctx.pop()
    log = (action_logs / "cards.log").read_text(encoding="utf-8")
    assert "PREFERRED-NAME" in log and "preferred=Ann" in log


def test_clearing_is_logged_as_cleared(app_module, stored_names, action_logs):
    ctx = _signed_in(app_module)
    try:
        app_module._save_preferred_name_from_chat(None)
    finally:
        ctx.pop()
    assert "(cleared)" in (action_logs / "cards.log").read_text(encoding="utf-8")


# --- injection into the agent -------------------------------------------


def test_the_saver_is_injected_when_the_agent_accepts_it(app_module,
                                                         monkeypatch):
    captured = {}

    class FakeAgent:
        def __init__(self, card_saver=None, name_saver=None):
            captured["card_saver"] = card_saver
            captured["name_saver"] = name_saver

    # raising=False: ai_agent is not importable in this venv, so app.py
    # never bound the name (MYKOLA_AVAILABLE is False here).
    monkeypatch.setattr(app_module, "MykolaAgent", FakeAgent, raising=False)
    monkeypatch.setattr(app_module, "_mykola_agent", None, raising=False)
    app_module.get_mykola()
    assert captured["name_saver"] is app_module._save_preferred_name_from_chat
    assert captured["card_saver"] is app_module._save_card_from_chat


def test_an_older_agent_without_the_argument_still_works(app_module,
                                                         monkeypatch):
    """The two repos deploy in either order, so KuantorFlow must not pass an
    argument an installed ai_agent has never heard of."""
    built = {}

    class OlderAgent:
        def __init__(self, card_saver=None):
            built["card_saver"] = card_saver

    monkeypatch.setattr(app_module, "MykolaAgent", OlderAgent, raising=False)
    monkeypatch.setattr(app_module, "_mykola_agent", None, raising=False)
    app_module.get_mykola()          # must not raise TypeError
    assert built["card_saver"] is app_module._save_card_from_chat


# --- the stored side ----------------------------------------------------


class FakeCursor:
    def __init__(self, rowcount=1):
        self.rowcount = rowcount
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((" ".join(query.split()), params))

    def close(self):
        pass


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def cursor(self, **kwargs):
        return self._cursor

    def commit(self):
        self.committed = True

    def close(self):
        pass


def test_the_update_writes_the_column(monkeypatch):
    cursor = FakeCursor()
    monkeypatch.setattr(utils, "get_db_connection", lambda: FakeConn(cursor))
    assert utils.set_preferred_name(7, "Ann") is True
    query, params = cursor.queries[0]
    assert query == "UPDATE users SET preferred_name = %s WHERE id = %s"
    assert params == ("Ann", 7)


def test_clearing_binds_null(monkeypatch):
    cursor = FakeCursor()
    monkeypatch.setattr(utils, "get_db_connection", lambda: FakeConn(cursor))
    utils.set_preferred_name(7, None)
    assert cursor.queries[0][1] == (None, 7)


def test_no_rows_updated_is_reported(monkeypatch):
    cursor = FakeCursor(rowcount=0)
    monkeypatch.setattr(utils, "get_db_connection", lambda: FakeConn(cursor))
    assert utils.set_preferred_name(999, "Ann") is False


def test_no_account_never_reaches_the_database(monkeypatch):
    def boom():
        raise AssertionError("must not connect for a visitor with no account")
    monkeypatch.setattr(utils, "get_db_connection", boom)
    assert utils.set_preferred_name(None, "Ann") is False
