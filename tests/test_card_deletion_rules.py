"""A user may delete only their own cards (kuantorflow#162).

Until this landed, POST /flashcards/<topic>/delete/<id> had no identity check
at all — anyone past the keyword gate could delete any card, with the
confirmation popup as the only guard. So these tests are as much about the
hole as about the feature, and the important ones drive the *route*: greying
the cross is presentation, and a hand-made POST goes straight past it.
"""

import pytest

import utils
from conftest import TEST_USER_EMAIL, TEST_USER_ID


ADMIN = "admin@example.com"
OTHER_USER_ID = 99


# --- the conditional DELETE ---------------------------------------------------

class FakeCursor:
    def __init__(self, word_row=("resilient",), rowcount=1):
        self.word_row = word_row
        self.rowcount = rowcount
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((" ".join(query.split()), params))

    def fetchone(self):
        return self.word_row

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


def _fake_db(monkeypatch, cursor):
    conn = FakeConn(cursor)
    monkeypatch.setattr(utils, "get_db_connection", lambda: conn)
    return conn


def _delete_query(cursor):
    return next(q for q, _ in cursor.queries if q.startswith("DELETE"))


def _delete_params(cursor):
    return next(p for q, p in cursor.queries if q.startswith("DELETE"))


def test_a_non_admin_delete_is_conditional_on_ownership(monkeypatch):
    """One statement, so nothing can change hands between check and delete."""
    cursor = FakeCursor()
    _fake_db(monkeypatch, cursor)
    assert utils.delete_flashcard(7, owner_id=TEST_USER_ID) == ("resilient",
                                                                "deleted")
    assert _delete_query(cursor) == \
        "DELETE FROM flashcards WHERE id = %s AND added_by_user_id = %s"
    assert _delete_params(cursor) == (7, TEST_USER_ID)


def test_an_admin_delete_is_unconditional(monkeypatch):
    cursor = FakeCursor()
    _fake_db(monkeypatch, cursor)
    assert utils.delete_flashcard(7, admin=True) == ("resilient", "deleted")
    assert _delete_query(cursor) == "DELETE FROM flashcards WHERE id = %s"
    assert _delete_params(cursor) == (7,)


def test_zero_rows_affected_reads_as_denied(monkeypatch):
    """The card exists but the conditional DELETE matched nothing."""
    cursor = FakeCursor(rowcount=0)
    conn = _fake_db(monkeypatch, cursor)
    assert utils.delete_flashcard(7, owner_id=TEST_USER_ID) == ("resilient",
                                                                "denied")
    assert conn.committed is False


def test_a_missing_card_is_missing_not_denied(monkeypatch):
    cursor = FakeCursor(word_row=None)
    _fake_db(monkeypatch, cursor)
    assert utils.delete_flashcard(7, owner_id=TEST_USER_ID) == (None, "missing")
    assert not any(q.startswith("DELETE") for q, _ in cursor.queries)


def test_an_unowned_card_cannot_be_claimed_by_a_regular_user(monkeypatch):
    """`= NULL` never matches, so cards from before #89 are admin-only. The
    SQL has to carry the user's real id, not None, for that to hold."""
    cursor = FakeCursor(rowcount=0)
    _fake_db(monkeypatch, cursor)
    word, outcome = utils.delete_flashcard(7, owner_id=TEST_USER_ID)
    assert outcome == "denied"
    assert _delete_params(cursor) == (7, TEST_USER_ID)


# --- the route enforces it ----------------------------------------------------

class DeleteCalls(list):
    """Captured delete_flashcard() calls; `outcome` is what the stub returns."""

    def __init__(self):
        super().__init__()
        self.outcome = ("resilient", "deleted")


@pytest.fixture()
def deletes(app_module, monkeypatch):
    """Capture delete_flashcard() calls; the outcome is set per test."""
    calls = DeleteCalls()

    def fake_delete(card_id, owner_id=None, admin=False):
        calls.append({"card_id": card_id, "owner_id": owner_id, "admin": admin})
        return calls.outcome

    monkeypatch.setattr(app_module, "delete_flashcard", fake_delete)
    return calls


@pytest.fixture()
def admin_client(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "ADMIN_EMAILS",
                        app_module._admin_emails(ADMIN))
    with client.session_transaction() as sess:
        sess["user"] = {"id": 1, "name": "Admin", "email": ADMIN,
                        "email_verified": True}
    return client


def _post(c, card_id=7):
    return c.post(f"/flashcards/vocab/delete/{card_id}", follow_redirects=True)


def test_a_signed_in_user_deletes_their_own_card(user_client, deletes):
    body = _post(user_client).get_data(as_text=True)
    assert deletes[0] == {"card_id": 7, "owner_id": TEST_USER_ID, "admin": False}
    assert "Deleted card" in body


def test_the_route_refuses_someone_elses_card(user_client, deletes, app_module):
    """The database reports zero rows; the route must say so rather than
    pretending the card was deleted."""
    deletes.outcome = ("resilient", "denied")
    body = _post(user_client).get_data(as_text=True)
    assert app_module.DELETE_NOT_YOURS in body
    assert "Deleted card" not in body


def test_a_forged_post_for_another_users_card_is_refused(user_client, deletes,
                                                         app_module):
    """The UI never offers this — it is a hand-made POST, which is exactly what
    template-side greying cannot stop. The user's own id goes into the SQL, so
    the card id being someone else's changes nothing."""
    deletes.outcome = ("someone-elses", "denied")
    body = _post(user_client, card_id=4242).get_data(as_text=True)
    assert deletes[0]["owner_id"] == TEST_USER_ID
    assert deletes[0]["admin"] is False
    assert app_module.DELETE_NOT_YOURS in body


def test_an_admin_deletes_any_card(admin_client, deletes):
    body = _post(admin_client).get_data(as_text=True)
    assert deletes[0]["admin"] is True
    assert "Deleted card" in body


def test_an_anonymous_visitor_never_reaches_the_database(client, deletes,
                                                         app_module):
    """No identity at all, so #125's prompt rather than #162's message — and
    the delete is not even attempted."""
    body = _post(client).get_data(as_text=True)
    assert deletes == [], "an anonymous delete must not reach the database"
    assert app_module.DELETE_SIGN_IN_PROMPT in body
    assert app_module.DELETE_NOT_YOURS not in body


def test_a_sign_in_without_a_users_row_is_treated_as_anonymous(client, deletes,
                                                               app_module):
    """id None (#148) means nothing can be theirs."""
    with client.session_transaction() as sess:
        sess["user"] = {"id": None, "name": "Test User",
                        "email": TEST_USER_EMAIL}
    body = _post(client).get_data(as_text=True)
    assert deletes == []
    assert app_module.DELETE_SIGN_IN_PROMPT in body


def test_a_missing_card_still_reads_as_missing(user_client, deletes):
    deletes.outcome = (None, "missing")
    body = _post(user_client).get_data(as_text=True)
    assert "Card not found" in body


# --- logging (#30) ------------------------------------------------------------

def _denied(action_logs):
    path = action_logs / "cards.log"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return [ln for ln in lines if " DELETE-DENIED " in ln]


def test_a_refusal_is_logged(user_client, deletes, action_logs):
    deletes.outcome = ("resilient", "denied")
    _post(user_client)
    line = _denied(action_logs)[0]
    assert "id=7" in line
    assert "reason='not owner'" in line
    assert f"user={TEST_USER_EMAIL}" in line


def test_an_anonymous_refusal_is_logged_with_its_own_reason(client, deletes,
                                                            action_logs):
    _post(client)
    line = _denied(action_logs)[0]
    assert "reason=anonymous" in line and "user=anonymous" in line


def test_a_successful_delete_logs_nothing_denied(user_client, deletes,
                                                 action_logs):
    _post(user_client)
    assert _denied(action_logs) == []


# --- the cross in the UI ------------------------------------------------------

CARD = {
    "id": 1, "word": "resilient", "pos": "adjective", "topic": "vocab",
    "explanation_en": "able to recover", "examples_en": [],
    "translation_ukr": "стійкий", "examples_ukr": [],
    "translation_rus": None, "examples_rus": [], "added_by_user_id": None,
}


def _page(c, app_module, monkeypatch, owner):
    monkeypatch.setattr(app_module, "get_flashcards_by_topic",
                        lambda topic: [dict(CARD, added_by_user_id=owner)])
    return c.get("/flashcards/vocab").get_data(as_text=True)


def _cross(body):
    """The delete button's markup."""
    start = body.index('class="card-delete"')
    return body[start:body.index("</button>", start)]


def test_your_own_card_keeps_a_live_cross(user_client, app_module, monkeypatch):
    cross = _cross(_page(user_client, app_module, monkeypatch, TEST_USER_ID))
    assert "aria-disabled" not in cross
    assert "title=" not in cross


def test_someone_elses_card_is_greyed_with_the_message(user_client, app_module,
                                                       monkeypatch):
    cross = _cross(_page(user_client, app_module, monkeypatch, OTHER_USER_ID))
    assert 'aria-disabled="true"' in cross
    assert "This card was created by admin or another user." in cross


def test_an_unowned_card_is_greyed_for_a_regular_user(user_client, app_module,
                                                      monkeypatch):
    cross = _cross(_page(user_client, app_module, monkeypatch, None))
    assert 'aria-disabled="true"' in cross


def test_the_admin_sees_a_live_cross_on_every_card(admin_client, app_module,
                                                   monkeypatch):
    for owner in (None, OTHER_USER_ID, TEST_USER_ID):
        cross = _cross(_page(admin_client, app_module, monkeypatch, owner))
        assert "aria-disabled" not in cross, f"owner={owner}"


def test_anonymous_visitors_get_the_sign_in_wording(client, app_module,
                                                    monkeypatch):
    cross = _cross(_page(client, app_module, monkeypatch, TEST_USER_ID))
    assert 'aria-disabled="true"' in cross
    assert "Sign in with Google" in cross
    assert "created by admin or another user" not in cross


def test_the_disabled_attribute_is_not_used(user_client, app_module,
                                            monkeypatch):
    """`disabled` makes the button inert, and hover/tooltip behaviour on inert
    controls varies by browser. aria-disabled keeps it hoverable everywhere."""
    cross = _cross(_page(user_client, app_module, monkeypatch, OTHER_USER_ID))
    assert " disabled" not in cross and "disabled>" not in cross


def test_a_greyed_cross_explains_itself_on_tap(user_client, app_module,
                                               monkeypatch):
    """Touch devices have no hover, so the title tooltip never shows there."""
    body = _page(user_client, app_module, monkeypatch, OTHER_USER_ID)
    assert 'id="delete-refused-modal"' in body
    assert 'aria-disabled") === "true"' in body, \
        "the click handler must branch on the greyed state"
    assert "refusedOverlay.hidden = false" in body
    assert 'id="delete-refused-ok"' in body


def test_the_greyed_cross_never_shows_the_red_hover(client):
    css = client.get("/static/css/style.css").get_data(as_text=True)
    assert '.card-delete[aria-disabled="true"]:hover' in css, \
        "the red hover state must be suppressed for a cross you cannot use"
