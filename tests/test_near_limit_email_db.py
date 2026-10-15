"""The near-the-limit warning against a real MySQL (kuantorflow#594).

The warning reads the count `claim_action()` returns after its commit, and
`_account_today()` reads the account and the day's counters back. The offline
fakes agree with any SQL, so this runs real claims on a scratch database and
counts the emails: exactly one, at the claim that reaches 80%.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv


@pytest.fixture(autouse=True)
def _the_real_utils(real_utils):
    """A real scratch database, so the offline stubs would answer first
    (kuantorflow#436)."""


AUTO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(AUTO_ROOT / ".env")

KUANTORFLOW_PATH = Path(os.environ.get(
    "KUANTORFLOW_PATH", str(AUTO_ROOT.parent.parent / "kuantorflow")))
SCRIPT = KUANTORFLOW_PATH / "scripts" / "apply_schema.py"

SCRATCH_DB = "kuantorflow_near_limit_test"

pytestmark = [pytest.mark.db, pytest.mark.skipif(
    not (os.environ.get("RUN_DB_ROUNDTRIP") == "1"
         and os.environ.get("DB_HOST") in ("localhost", "127.0.0.1")
         and os.environ.get("DB_PASSWORD")
         and SCRIPT.exists()),
    reason="opt-in: set RUN_DB_ROUNDTRIP=1 with a local MySQL (DB_HOST=localhost) "
    "and DB_* configured; the test creates its own scratch database")]


def _execute(statements):
    import mysql.connector
    conn = mysql.connector.connect(
        user=os.environ.get("DB_USER", "kuantorflow"),
        password=os.environ["DB_PASSWORD"], host=os.environ["DB_HOST"])
    cursor = conn.cursor()
    for statement in statements:
        cursor.execute(statement)
    conn.commit()
    cursor.close()
    conn.close()


@pytest.fixture()
def scratch_db(monkeypatch):
    _execute([f"DROP DATABASE IF EXISTS {SCRATCH_DB}",
              f"CREATE DATABASE {SCRATCH_DB} CHARACTER SET utf8mb4"])
    subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True,
                   env=dict(os.environ, DB_NAME=SCRATCH_DB),
                   cwd=str(KUANTORFLOW_PATH), check=True)
    monkeypatch.setenv("DB_NAME", SCRATCH_DB)
    try:
        yield SCRATCH_DB
    finally:
        _execute([f"DROP DATABASE IF EXISTS {SCRATCH_DB}"])


@pytest.fixture()
def sent(monkeypatch):
    import notify
    calls = []
    monkeypatch.setattr(notify, "send_admin_email",
                        lambda kind, subject, body: calls.append((subject, body)) or "sent")
    monkeypatch.delenv("ADMIN_EMAILS", raising=False)
    monkeypatch.delenv("NOTIFY_LIMIT_PERCENT", raising=False)
    return calls


def test_real_claims_send_one_warning_at_80_percent(scratch_db, sent):
    import utils

    user_id, _, _ = utils.upsert_user("sub-594", "heavy.user@example.com")
    utils.claim_word_lookups(user_id, 7, 50, 10)
    answers = [utils.claim_pools([("user", utils.RECAP, user_id, 5),
                                  ("daily", utils.RECAP_ALL, utils.ALL_ACCOUNTS, 100)])
               for _ in range(6)]

    assert [a[0] for a in answers] == [True] * 5 + [False]
    assert len(sent) == 1
    subject, body = sent[0]
    assert subject == f"KuantorFlow: account #{user_id} at 80% of its recap limit"
    assert "4 of 5 recaps" in body
    assert "he***@example.com" in body and "heavy.user" not in body
    assert "word lookups: 7" in body


def test_the_account_and_its_counters_are_read_back(scratch_db):
    import utils

    user_id, _, _ = utils.upsert_user("sub-594b", "reader@example.com")
    utils.claim_action(utils.CHAT, user_id, 40, amount=3)
    utils.claim_action(utils.UPLOAD, user_id, 10)

    email, created_at, counters = utils._account_today(user_id)

    assert email == "reader@example.com" and created_at is not None
    assert counters == {utils.CHAT: 3, utils.UPLOAD: 1}
    assert utils._account_today(user_id + 999) is None
