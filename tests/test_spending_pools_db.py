"""Anonymous traffic cannot spend what a signed-in learner draws on (#456).

Three paid features bounded their spending three different ways, and no two
agreed. Generation was **inverted** from the other two: the only one with a row
counting everybody, and the only one *without* a row counting anonymous traffic
on its own. So anonymous texts exhausted the pool an account drew from -- while
lookups and chat had no ceiling on the total bill at all.

Measured before the fix, with the numbers shrunk: twelve anonymous texts and
the thirteenth request, from an account that had spent none of its own ten, was
refused with `scope: daily`. The same twelve anonymous *lookups* left that
account untouched. Same situation, opposite outcome.

Three pools each now -- yours, everybody-anonymous's, everybody's -- so neither
column has a gap. The `:all` row is what bounds the bill, and it matters most
for chat: `ai_agent` answers with `claude-opus-5` where every call this repo
makes itself uses Haiku, so one message costs roughly thirty times one
generated text.

Against a real database, because the whole mechanism is one conditional UPDATE
and the offline fakes agree with any clause.
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

SCRATCH_DB = "kuantorflow_pools_test"

# No such account: the table has no foreign key to `users` on purpose, so an
# id nobody owns is a valid row and using one says so.
LEARNER = 987654321

pytestmark = pytest.mark.db


def _prerequisites_met():
    return (
        os.environ.get("RUN_DB_ROUNDTRIP") == "1"
        and os.environ.get("DB_HOST") in ("localhost", "127.0.0.1")
        and os.environ.get("DB_PASSWORD")
        and SCRIPT.exists()
    )


requires_local_db = pytest.mark.skipif(
    not _prerequisites_met(),
    reason="opt-in: set RUN_DB_ROUNDTRIP=1 with a local MySQL (DB_HOST=localhost) "
    "and DB_* configured; the test creates its own scratch database",
)


def _connect(database=None):
    import mysql.connector
    return mysql.connector.connect(
        user=os.environ.get("DB_USER", "kuantorflow"),
        password=os.environ["DB_PASSWORD"],
        host=os.environ["DB_HOST"],
        database=database,
    )


def _execute(statements, database=None):
    conn = _connect(database)
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


def _rows():
    conn = _connect(SCRATCH_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, action, used FROM action_usage "
                   "WHERE day = CURDATE() ORDER BY user_id, action")
    found = cursor.fetchall()
    cursor.close()
    conn.close()
    return found



# --- the asymmetry, and that it is gone -------------------------------------

USER, SHARED = 10, 12          # shrunk so twelve anonymous calls exhaust one


ANON, SHARED_WIDE = 4, 10      # anonymous strictly below everybody's


@requires_local_db
@pytest.mark.parametrize("claim", ["claim_text_generation",
                                   "claim_word_lookup",
                                   "claim_chat_message"])
def test_anonymous_traffic_can_only_take_its_share_of_the_shared_pool(
        scratch_db, claim):
    """The mechanism, and it is narrower than "anonymous cannot starve you".

    Anonymous visitors claim their own row **and** everybody's, so they do
    spend the shared pool -- that is what a bill ceiling is for. What stops
    them emptying it is that their own ceiling is **smaller**: once it is
    reached they are refused, and the shared row stops advancing with them.

    So the gap between the two is the whole protection, which is why
    `ANONYMOUS_DAILY_LIMIT` is below `CHAT_ALL_DAILY` rather than equal to it.
    Setting them equal is this ticket's own bug wearing a new hat -- and the
    first version of this test held the shared pool wide open, which made it
    pass against the unfixed code.
    """
    import utils
    take = getattr(utils, claim)
    kwargs = {"anon_limit": ANON, "all_limit": SHARED_WIDE}

    for _ in range(ANON * 2):                    # twice the anonymous ceiling
        take(None, 1000, **kwargs)

    shared = [r for r in _rows() if r[1].endswith(":all")]
    assert shared and shared[0][2] == ANON, (
        "anonymous traffic took %s of the shared pool, not %d"
        % (shared, ANON))

    allowed, scope, _ = take(LEARNER, 1000, **kwargs)
    assert allowed is True, "%s refused an account with %s" % (claim, scope)


@requires_local_db
def test_an_account_still_meets_its_own_ceiling(scratch_db):
    """The other half. A pool nobody can exhaust is not a ceiling."""
    import utils

    for _ in range(USER):
        utils.claim_text_generation(LEARNER, USER, 1000, anon_limit=1000)

    allowed, scope, used = utils.claim_text_generation(
        LEARNER, USER, 1000, anon_limit=1000)

    assert (allowed, scope, used) == (False, "user", USER)


@requires_local_db
def test_everybody_meets_the_shared_ceiling(scratch_db):
    """What bounds the bill. Without it the total is "however many accounts
    somebody cares to create, times the per-account ceiling" -- and a Google
    account is a cost barrier rather than a bot barrier (#447)."""
    import utils

    for n in range(SHARED):
        assert utils.claim_chat_message(
            LEARNER + n, 1000, 1000, SHARED)[0] is True, "refused at %d" % n

    allowed, scope, used = utils.claim_chat_message(
        LEARNER + 999, 1000, 1000, SHARED)

    assert (allowed, scope, used) == (False, "daily", SHARED)


@requires_local_db
def test_the_account_row_is_claimed_before_the_shared_one(scratch_db):
    """#237's argument, carried over: a learner can spend one of their own on
    a day the whole site is exhausted, rather than burning a site-wide slot
    for somebody already over their personal limit."""
    import utils

    utils.claim_chat_message(LEARNER, 1, 1000, 1000)     # account row now full
    allowed, scope, _ = utils.claim_chat_message(LEARNER, 1, 1000, 1000)

    assert (allowed, scope) == (False, "user")
    shared = [r for r in _rows() if r[1] == "chat:all"]
    assert shared == [(0, "chat:all", 1)], (
        "the shared pool was charged for a refusal, or twice: %s" % shared)


@requires_local_db
def test_a_ceiling_of_zero_is_off_and_the_others_still_apply(scratch_db):
    """0 disables one pool without disabling the rest, which is how a
    deployment tunes these one at a time."""
    import utils

    for _ in range(4):
        utils.claim_word_lookup(LEARNER, 0, 0, 3)        # own ceiling off

    allowed, scope, _ = utils.claim_word_lookup(LEARNER, 0, 0, 3)

    assert (allowed, scope) == (False, "daily"), "the shared pool was skipped"
