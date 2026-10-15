"""Email the admin when an account signs in for the first time (kuantorflow#592).

Built on the mailer (#591). What must hold:

* **only on an account's first sign-in**: `utils.upsert_user()` reports a new
  row (MySQL's rowcount 1) apart from an update (2) or an unchanged row (0),
  and the Google callback sends for a new row only;
* **never for an admin address** (`ADMIN_EMAILS`);
* the email names the account by **id and a masked address**
  (`notify.mask_email()`, shared with #593 and #594), never the full one;
* **a mailer that fails, or a count that fails, never costs the sign-in.**

`notify.send_admin_email` is replaced by a recorder; the real-MySQL side of
the rowcount is in `test_new_account_email_db.py`.
"""

import re
import types
from pathlib import Path

import pytest

from conftest import KUANTORFLOW_PATH

import notify
import utils

EMAIL = "anna.kowalska@example.com"
CLAIMS = {"sub": "110169484474386276334", "email": EMAIL,
          "name": "Anna Maria Kowalska", "given_name": "Anna Maria",
          "family_name": "Kowalska", "email_verified": True}


@pytest.fixture()
def sent(monkeypatch):
    """Every notice the app asks for, as (kind, subject, body)."""
    calls = []
    monkeypatch.setattr(notify, "send_admin_email",
                        lambda kind, subject, body: calls.append((kind, subject, body)) or "sent")
    return calls


@pytest.fixture()
def sign_in(client, monkeypatch):
    """Sign in through the Google callback with `upsert_user` answering
    (user_id, preferred_name, created); returns the response."""
    def _sign_in(created=True, user_id=13, claims=CLAIMS, count=14):
        monkeypatch.setattr("web.GOOGLE_AUTH_AVAILABLE", True)
        monkeypatch.setattr("web.oauth", types.SimpleNamespace(
            google=types.SimpleNamespace(
                authorize_access_token=lambda: {"userinfo": dict(claims)})))
        monkeypatch.setattr("utils.upsert_user",
                            lambda *a, **k: (user_id, None, created))
        monkeypatch.setattr("utils.count_users",
                            count if callable(count) else (lambda: count))
        return client.get("/auth/google/callback")
    return _sign_in


@pytest.fixture()
def no_admins(monkeypatch):
    monkeypatch.setattr("web.ADMIN_EMAILS", frozenset())


# --- when -------------------------------------------------------------------

def test_a_first_sign_in_sends_one_notice(sign_in, sent, no_admins):
    assert sign_in(created=True).status_code == 302

    assert len(sent) == 1
    kind, subject, _ = sent[0]
    assert kind == notify.KIND_NEW_ACCOUNT
    assert subject == "KuantorFlow: new account #13"


def test_a_returning_sign_in_sends_none(sign_in, sent, no_admins):
    sign_in(created=False)

    assert sent == []


def test_an_admins_first_sign_in_sends_none(sign_in, sent, monkeypatch):
    monkeypatch.setattr("web.ADMIN_EMAILS", frozenset({EMAIL}))

    sign_in(created=True, claims=dict(CLAIMS, email=EMAIL.upper()))

    assert sent == []


def test_a_sign_in_the_database_could_not_record_sends_none(client, sent, monkeypatch,
                                                            no_admins):
    """No row, no account: `_record_sign_in` answers (None, None, False)."""
    monkeypatch.setattr("web.GOOGLE_AUTH_AVAILABLE", True)
    monkeypatch.setattr("web.oauth", types.SimpleNamespace(
        google=types.SimpleNamespace(authorize_access_token=lambda: {"userinfo": CLAIMS})))

    def boom(*a, **k):
        raise RuntimeError("db unreachable")
    monkeypatch.setattr("utils.upsert_user", boom)

    assert client.get("/auth/google/callback").status_code == 302
    assert sent == []


# --- what it says -----------------------------------------------------------

def test_the_body_names_the_account_by_id_and_masked_address(sign_in, sent, no_admins):
    sign_in()
    body = sent[0][2]

    assert "#13" in body
    assert notify.mask_email(EMAIL) in body
    assert EMAIL not in body and "kowalska" not in body.lower()


def test_the_body_has_the_first_name_the_time_and_the_count(sign_in, sent, no_admins):
    sign_in(count=14)
    body = sent[0][2]

    assert "Anna" in body and "Maria" not in body
    assert re.search(r"\d{1,2} \w{3} \d{4}, \d{2}:\d{2}", body), body
    assert "Kyiv" in body
    assert "14" in body


def test_the_body_says_how_to_block_it(sign_in, sent, no_admins):
    sign_in()
    body = sent[0][2]

    assert "maintenance/block_user.py --list" in body
    assert "--reason" in body


def test_no_name_claim_is_no_name_line(sign_in, sent, no_admins):
    sign_in(claims={"sub": "s", "email": EMAIL})

    assert len(sent) == 1 and "Name" not in sent[0][2]


# --- never in the way -------------------------------------------------------

def test_a_failing_mailer_still_signs_the_person_in(sign_in, client, monkeypatch,
                                                    no_admins):
    def boom(*a):
        raise RuntimeError("mailer exploded")
    monkeypatch.setattr(notify, "send_admin_email", boom)

    assert sign_in().status_code == 302
    with client.session_transaction() as sess:
        assert sess["user"]["id"] == 13
        assert sess["user"]["email"] == EMAIL


def test_a_failing_count_still_sends(sign_in, sent, no_admins):
    def boom():
        raise RuntimeError("db unreachable")

    assert sign_in(count=boom).status_code == 302
    assert len(sent) == 1 and "#13" in sent[0][2]


# --- upsert_user reports a new row ------------------------------------------

class _Cursor:
    def __init__(self, rowcount):
        self.rowcount, self.lastrowid = rowcount, 42

    def execute(self, sql, params=None):
        pass

    def fetchone(self):
        return (None,)

    def close(self):
        pass


@pytest.mark.parametrize("rowcount,created", [(1, True), (2, False), (0, False)])
def test_upsert_user_says_whether_the_row_is_new(monkeypatch, rowcount, created):
    """MySQL's answer to INSERT ... ON DUPLICATE KEY UPDATE: 1 inserted,
    2 updated, 0 an existing row left as it was."""
    cursor = _Cursor(rowcount)
    conn = types.SimpleNamespace(cursor=lambda: cursor, commit=lambda: None,
                                 close=lambda: None)
    monkeypatch.setattr(utils, "get_db_connection", lambda: conn)

    assert utils.upsert_user("sub-1", "a@example.com") == (42, None, created)


# --- mask_email -------------------------------------------------------------

@pytest.mark.parametrize("email,masked", [
    ("anton.k@gmail.com", "an***@gmail.com"),
    ("ab@gmail.com", "a***@gmail.com"),
    ("a@gmail.com", "***@gmail.com"),
    ("not-an-address", "***"),
    ("", "***"),
    (None, "***"),
    ("  Anna@Example.com ", "an***@example.com"),
])
def test_mask_email(email, masked):
    assert notify.mask_email(email) == masked


def test_a_masked_address_never_shows_the_whole_local_part():
    for local in ("a", "ab", "abc", "abcdef"):
        masked = notify.mask_email(local + "@x.test")
        assert not masked.startswith(local + "@") and not masked.startswith(local + "*")


# --- the guide says so ------------------------------------------------------

def test_the_privacy_section_says_the_owner_is_emailed():
    guide = (Path(KUANTORFLOW_PATH) / "docs" / "user-guide.md").read_text(encoding="utf-8")
    start = guide.index("## Privacy: what the site keeps")
    privacy = guide[start:guide.index("\n## ", start + 3)]

    assert "first sign in" in privacy.lower()
    assert notify.mask_email("anton.k@gmail.com") in privacy
