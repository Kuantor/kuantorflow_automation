"""Delete my account, with a keep-or-delete choice for the cards (#165).

The operation is irreversible — soft delete was considered and dropped (#159)
— so the tests care as much about what is *not* destroyed and about the order
of operations as about the happy path.

The order is the design: cards are resolved first, then the files, and the
users row goes last. `added_by_user_id` is ON DELETE RESTRICT (#89), so a path
that skipped the card step would fail loudly on the foreign key rather than
quietly cascading or anonymising against the user's wishes.
"""

import json

import pytest

import settings_store
import utils


DELETED_USER = 7


# --- resolving the cards ------------------------------------------------------

class FakeCursor:
    def __init__(self, rowcount=3):
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


@pytest.fixture()
def cursor(monkeypatch):
    cur = FakeCursor()
    monkeypatch.setattr(utils, "get_db_connection", lambda: FakeConn(cur))
    return cur


def test_keeping_cards_clears_the_owner(cursor):
    """'Keep' means they stay for everyone else, with no owner."""
    assert utils.resolve_user_cards(DELETED_USER, keep_cards=True) == 3
    query, params = cursor.queries[0]
    assert query == ("UPDATE flashcards SET added_by_user_id = NULL "
                     "WHERE added_by_user_id = %s")
    assert params == (DELETED_USER,)
    assert "DELETE" not in query


def test_deleting_cards_removes_them(cursor):
    assert utils.resolve_user_cards(DELETED_USER, keep_cards=False) == 3
    query, params = cursor.queries[0]
    assert query == "DELETE FROM flashcards WHERE added_by_user_id = %s"
    assert params == (DELETED_USER,)


def test_only_that_users_cards_are_touched(cursor):
    """Both branches are scoped by owner — never a bare UPDATE/DELETE."""
    utils.resolve_user_cards(DELETED_USER, keep_cards=True)
    utils.resolve_user_cards(DELETED_USER, keep_cards=False)
    for query, params in cursor.queries:
        assert "WHERE added_by_user_id = %s" in query
        assert params == (DELETED_USER,)


def test_deleting_the_user_row_is_scoped_by_id(cursor):
    assert utils.delete_user(DELETED_USER) is True
    query, params = cursor.queries[0]
    assert query == "DELETE FROM users WHERE id = %s"
    assert params == (DELETED_USER,)


def test_a_missing_user_row_reports_false(monkeypatch):
    cur = FakeCursor(rowcount=0)
    monkeypatch.setattr(utils, "get_db_connection", lambda: FakeConn(cur))
    assert utils.delete_user(DELETED_USER) is False


# --- the orchestration --------------------------------------------------------

@pytest.fixture()
def account(app_module, monkeypatch, chat_logs, settings_dir):
    """A signed-in user with cards, chat logs and a settings file on disk."""
    order = []

    def fake_resolve(user_id, keep_cards=True):
        order.append(("cards", user_id, keep_cards))
        return 5

    def fake_delete_user(user_id):
        order.append(("row", user_id))
        return True

    monkeypatch.setattr(app_module, "resolve_user_cards", fake_resolve)
    monkeypatch.setattr(app_module, "delete_user", fake_delete_user)

    log_dir = chat_logs / str(DELETED_USER)
    log_dir.mkdir(parents=True)
    (log_dir / "chat_2026-07-20_11-00-00_aaaa.txt").write_text("hi", encoding="utf-8")
    (log_dir / "user.txt").write_text("id: 7\n", encoding="utf-8")
    settings_store.save({"translator": "bing"}, DELETED_USER, "gone@example.com")

    return {"order": order, "log_dir": log_dir,
            "config": settings_dir / f"config-{DELETED_USER}.json"}


def test_everything_belonging_to_the_account_goes(app_module, account):
    result = app_module.delete_account(DELETED_USER, keep_cards=True)

    assert result["cards"] == 5
    assert not account["log_dir"].exists(), "chat transcripts go with the account"
    assert not account["config"].exists(), "so does the settings file"
    assert result["row"] is True


def test_the_users_row_goes_last(app_module, account):
    """While the row exists the account is coherent and the deletion can be
    retried; once it is gone, leftovers have nothing to attribute them to."""
    app_module.delete_account(DELETED_USER, keep_cards=True)
    steps = [step[0] for step in account["order"]]
    assert steps == ["cards", "row"], "cards must be resolved before the row"


def test_the_card_choice_is_passed_through(app_module, account):
    app_module.delete_account(DELETED_USER, keep_cards=False)
    assert account["order"][0] == ("cards", DELETED_USER, False)


def test_a_user_with_no_files_still_deletes(app_module, monkeypatch, chat_logs,
                                            settings_dir):
    """Never saved settings, never chatted — not a failure."""
    monkeypatch.setattr(app_module, "resolve_user_cards", lambda *a, **k: 0)
    monkeypatch.setattr(app_module, "delete_user", lambda uid: True)
    result = app_module.delete_account(99, keep_cards=True)
    assert result["row"] is True
    assert result["settings"] is False and result["logs"] is False


# --- the route ----------------------------------------------------------------

@pytest.fixture()
def deletions(app_module, monkeypatch):
    calls = []
    monkeypatch.setattr(app_module, "delete_account",
                        lambda user_id, keep_cards=True: calls.append(
                            (user_id, keep_cards)) or {
                                "cards": 5, "kept": keep_cards, "logs": True,
                                "settings": True, "row": True})
    return calls


def test_a_signed_in_user_can_delete_their_account(user_client, deletions):
    from conftest import TEST_USER_ID

    body = user_client.post("/account/delete", data={"cards": "keep"},
                            follow_redirects=True).get_data(as_text=True)
    assert deletions == [(TEST_USER_ID, True)]
    assert "account was deleted" in body


def test_the_delete_choice_is_honoured(user_client, deletions):
    user_client.post("/account/delete", data={"cards": "delete"})
    assert deletions[0][1] is False, "'delete' must not be read as 'keep'"


def test_a_missing_or_junk_choice_keeps_the_cards(user_client, deletions):
    """The safer of the two options is what a malformed request falls back to
    — the destructive one has to be asked for explicitly."""
    from conftest import TEST_USER_EMAIL, TEST_USER_ID

    user_client.post("/account/delete", data={})
    # the first deletion signed this client out, so sign in again for the second
    with user_client.session_transaction() as sess:
        sess["user"] = {"id": TEST_USER_ID, "email": TEST_USER_EMAIL}
    user_client.post("/account/delete", data={"cards": "nonsense"})
    assert [keep for _, keep in deletions] == [True, True]


def test_the_session_identity_is_cleared(user_client, deletions):
    user_client.post("/account/delete", data={"cards": "keep"})
    with user_client.session_transaction() as sess:
        assert "user" not in sess


def test_the_gate_pass_survives(user_client, deletions):
    """The keyword gate is about the site, not the account — a deleted user
    lands back inside it as an anonymous visitor. Clearing it is Reset Auth's
    job (#98), not this one."""
    user_client.post("/account/delete", data={"cards": "keep"})
    with user_client.session_transaction() as sess:
        assert sess.get("access_granted") is True


def test_an_anonymous_visitor_has_no_account_to_delete(client, deletions,
                                                       app_module):
    r = client.post("/account/delete", data={"cards": "delete"})
    assert r.status_code == 403
    assert app_module.SIGN_IN_TO_DELETE_ACCOUNT in r.get_json()["error"]
    assert deletions == [], "the database must not be touched"


def test_a_sign_in_with_no_users_row_is_refused(client, deletions):
    """id None (#148) — there is no account record to remove."""
    with client.session_transaction() as sess:
        sess["user"] = {"id": None, "email": "nobody@example.com"}
    assert client.post("/account/delete", data={"cards": "keep"}).status_code == 403
    assert deletions == []


def test_a_failure_removes_nothing_and_says_so(user_client, app_module,
                                               monkeypatch):
    def boom(user_id, keep_cards=True):
        raise RuntimeError("database down")

    monkeypatch.setattr(app_module, "delete_account", boom)
    body = user_client.post("/account/delete", data={"cards": "keep"},
                            follow_redirects=True).get_data(as_text=True)
    assert "nothing was removed" in body
    with user_client.session_transaction() as sess:
        assert "user" in sess, "a failed deletion must not sign the user out"


def test_delete_rejects_get(user_client):
    assert user_client.get("/account/delete").status_code == 405


# --- logging (#30) ------------------------------------------------------------

def _account_lines(action_logs):
    path = action_logs / "cards.log"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return [ln for ln in lines if " ACCOUNT-DELETE " in ln]


def test_the_deletion_is_logged(user_client, deletions, action_logs):
    from conftest import TEST_USER_ID

    user_client.post("/account/delete", data={"cards": "delete"})
    line = _account_lines(action_logs)[0]
    assert f"id={TEST_USER_ID}" in line
    assert "cards=5" in line
    assert "choice=deleted" in line


def test_the_log_line_carries_no_email(user_client, deletions, action_logs):
    """The point of the operation is removing the identifier — writing it into
    a fresh line would undo part of what the user just asked for."""
    line = None
    user_client.post("/account/delete", data={"cards": "keep"})
    line = _account_lines(action_logs)[0]
    assert "@" not in line, line


# --- the UI -------------------------------------------------------------------

def test_a_signed_in_user_sees_the_control(user_client):
    body = user_client.get("/").get_data(as_text=True)
    assert 'id="delete-account-btn"' in body
    assert 'id="delete-account-modal"' in body


def test_anonymous_visitors_do_not(client):
    body = client.get("/").get_data(as_text=True)
    assert 'id="delete-account-btn"' not in body


def test_the_dialog_spells_out_the_consequences(user_client):
    body = user_client.get("/").get_data(as_text=True)
    assert "cannot be undone" in body
    for consequence in ("account record", "conversation with Mykola", "settings"):
        assert consequence in body
    # the card choice, with the non-destructive option preselected
    assert 'name="cards" value="keep" checked' in body
    assert 'name="cards" value="delete"' in body


def test_the_dialog_uses_the_danger_styling(user_client):
    body = user_client.get("/").get_data(as_text=True)
    dialog = body.split('id="delete-account-modal"')[1].split("</div>")[0:6]
    assert 'class="danger"' in "".join(dialog)


def test_the_browser_state_is_cleared_on_submit(user_client):
    """The account is going, so this browser's own leftovers go too."""
    body = user_client.get("/").get_data(as_text=True)
    handler = body.split('getElementById("delete-account-form")')[1][:400]
    assert "kf_mykola_widget_state_v1" in handler


# --- the admin account cannot delete itself (#165) ----------------------------

ADMIN = "admin@example.com"


@pytest.fixture()
def admin_client(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "ADMIN_EMAILS",
                        app_module._admin_emails(ADMIN))
    with client.session_transaction() as sess:
        sess["user"] = {"id": 1, "name": "Admin", "email": ADMIN,
                        "email_verified": True}
    return client


def test_the_admin_account_cannot_be_deleted(admin_client, deletions,
                                             app_module):
    """Enforced by the route — greying the button is presentation, and a
    hand-made POST goes straight past it (#162)."""
    r = admin_client.post("/account/delete", data={"cards": "delete"})
    assert r.status_code == 403
    assert "Admin account cannot be deleted" in r.get_json()["error"]
    assert deletions == [], "nothing may be touched"


def test_the_refusal_says_how_to_actually_do_it(app_module):
    """A dead end is worse than a signpost: admin-ness lives in ADMIN_EMAILS
    (#158), so that is the way out."""
    assert "ADMIN_EMAILS" in app_module.ADMIN_ACCOUNT_UNDELETABLE


def test_the_admins_control_is_greyed_with_the_reason(admin_client):
    body = admin_client.get("/").get_data(as_text=True)
    control = body.split('id="delete-account-btn"')[1].split("</button>")[0]
    assert 'aria-disabled="true"' in control
    assert "Admin account cannot be deleted" in control


def test_a_regular_user_keeps_a_live_control(user_client):
    body = user_client.get("/").get_data(as_text=True)
    control = body.split('id="delete-account-btn"')[1].split("</button>")[0]
    assert "aria-disabled" not in control


def test_the_greyed_control_explains_itself_on_tap(admin_client):
    """Touch devices never see the title tooltip."""
    body = admin_client.get("/").get_data(as_text=True)
    assert 'id="delete-account-refused-modal"' in body
    assert 'aria-disabled") === "true"' in body
    assert 'id="delete-account-refused-ok"' in body


def test_the_greyed_control_has_no_hover_state(client):
    css = client.get("/static/css/style.css").get_data(as_text=True)
    assert '.settings-reset[aria-disabled="true"]:hover' in css
