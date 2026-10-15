"""Email the admin when a learner reaches 80% of a daily limit (kuantorflow#594).

A red flag for blocking (#126), built on the mailer (#591). Every per-account
ceiling is claimed through `utils.claim_pools()` with scope `user`, so that is
the one place the warning lives. What must hold:

* **exactly the claim that crosses the threshold** sends it -- the claims
  before and after it the same day do not, and a batch claim that jumps over
  it does;
* the threshold is **derived**: `ceil(percent x limit)`, from the limit the
  claim was given and `NOTIFY_LIMIT_PERCENT` (default 80; 0 turns it off);
* **not for an admin account**, not for a refused claim, not for the shared
  pools;
* the body names the account by id and **masked** address, with the count and
  the limit and the block commands;
* **nothing about it can change the claim's answer.**

`utils.claim_action` is scripted to report each claim's count; the account
lookup and the mailer are stubbed. The real-MySQL side is in
`test_near_limit_email_db.py`.
"""

import re
from datetime import datetime
from pathlib import Path

import pytest

from conftest import KUANTORFLOW_PATH

import notify

EMAIL = "heavy.user@example.com"


@pytest.fixture()
def u(real_utils, monkeypatch):
    """The real `claim_pools`, over a scripted `claim_action` and account."""
    real_utils._counts = {}

    def claim_action(action, user_id, limit, amount=1):
        used = real_utils._counts.get((action, user_id), 0)
        if used + amount > limit:
            return False, used
        real_utils._counts[(action, user_id)] = used + amount
        return True, used + amount

    monkeypatch.setattr(real_utils, "claim_action", claim_action)
    monkeypatch.setattr(real_utils, "_account_today", lambda user_id: (
        EMAIL, datetime(2026, 10, 3, 9, 30),
        {action: used for (action, uid), used in real_utils._counts.items()
         if uid == user_id}))
    monkeypatch.delenv("NOTIFY_LIMIT_PERCENT", raising=False)
    monkeypatch.delenv("ADMIN_EMAILS", raising=False)
    return real_utils


@pytest.fixture()
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(notify, "send_admin_email",
                        lambda kind, subject, body: calls.append((kind, subject, body)) or "sent")
    return calls


def _chat(u, times, limit=40, user_id=13):
    results = []
    for _ in range(times):
        results.append(u.claim_pools([("user", u.CHAT, user_id, limit),
                                      ("daily", u.CHAT_ALL, u.ALL_ACCOUNTS, 1000)]))
    return results


# --- when -------------------------------------------------------------------

def test_the_claim_that_reaches_80_percent_sends_one_warning(u, sent):
    _chat(u, 31)
    assert sent == []

    _chat(u, 1)                     # the 32nd of 40
    assert len(sent) == 1
    kind, subject, _ = sent[0]
    assert kind == notify.KIND_NEAR_LIMIT
    assert subject == "KuantorFlow: account #13 at 80% of its chat limit"


def test_the_claims_after_it_send_none(u, sent):
    _chat(u, 40)

    assert len(sent) == 1


def test_a_refused_claim_sends_none(u, sent):
    _chat(u, 45)                    # 40 allowed, 5 refused

    assert len(sent) == 1


def test_a_batch_that_jumps_the_threshold_sends_one(u, sent):
    """#406's topic builder claims many lookups at once: 30 then 20 of 50."""
    u.claim_pools([("user", u.LOOKUP, 13, 50)], amount=30)
    assert sent == []

    u.claim_pools([("user", u.LOOKUP, 13, 50)], amount=20)
    assert len(sent) == 1 and "lookup" in sent[0][1]


@pytest.mark.parametrize("limit,threshold", [(40, 32), (50, 40), (10, 8), (5, 4), (1, 1)])
def test_the_threshold_follows_the_limit(u, sent, limit, threshold):
    _chat(u, threshold - 1, limit=limit)
    assert sent == []
    _chat(u, 1, limit=limit)
    assert len(sent) == 1


def test_the_percent_is_a_setting(u, sent, monkeypatch):
    monkeypatch.setenv("NOTIFY_LIMIT_PERCENT", "50")

    _chat(u, 19)
    assert sent == []
    _chat(u, 1)
    assert len(sent) == 1 and "50%" in sent[0][1]


@pytest.mark.parametrize("value", ["0", "", "nonsense"])
def test_zero_turns_it_off_and_nonsense_keeps_80(u, sent, monkeypatch, value):
    monkeypatch.setenv("NOTIFY_LIMIT_PERCENT", value)

    _chat(u, 32)

    assert len(sent) == (0 if value == "0" else 1)


def test_each_learner_and_each_activity_is_warned_once(u, sent):
    _chat(u, 32, user_id=13)
    _chat(u, 32, user_id=14)
    for _ in range(4):
        u.claim_pools([("user", u.RECAP, 13, 5)])

    assert [s[1] for s in sent] == [
        "KuantorFlow: account #13 at 80% of its chat limit",
        "KuantorFlow: account #14 at 80% of its chat limit",
        "KuantorFlow: account #13 at 80% of its recap limit",
    ]


def test_an_admin_account_is_not_warned(u, sent, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "someone@else.test, " + EMAIL.upper())

    _chat(u, 40)

    assert sent == []


def test_the_shared_pools_send_none(u, sent):
    for _ in range(40):
        u.claim_pools([("anonymous", u.CHAT_ANON, u.ALL_ACCOUNTS, 40),
                       ("daily", u.CHAT_ALL, u.ALL_ACCOUNTS, 40)])

    assert sent == []


def test_the_real_claimers_reach_it(u, sent):
    """chat, lookups and texts go through their own wrappers, which build the
    pools; the recap and upload through web's account guard (scope `user`)."""
    for _ in range(8):
        u.claim_text_generation(13, 10, 1000, anon_limit=5)

    assert len(sent) == 1 and "text" in sent[0][1]


# --- what it says -----------------------------------------------------------

def test_the_body_names_the_account_masked(u, sent):
    _chat(u, 32)
    body = sent[0][2]

    assert "#13" in body
    assert notify.mask_email(EMAIL) in body
    assert EMAIL not in body and "heavy.user" not in body


def test_the_body_has_the_count_the_limit_and_the_age(u, sent):
    _chat(u, 32)
    body = sent[0][2]

    assert "32 of 40" in body
    assert "3 Oct 2026" in body


def test_the_body_lists_the_other_counters_today(u, sent):
    u.claim_pools([("user", u.LOOKUP, 13, 50)], amount=12)
    _chat(u, 32)
    body = sent[0][2]

    assert re.search(r"lookups?: 12", body), body


def test_the_body_says_how_to_block_it(u, sent):
    _chat(u, 32)
    body = sent[0][2]

    assert "maintenance/block_user.py --list" in body and "--reason" in body


def test_every_account_ceiling_has_words_for_the_email(real_utils):
    """Derived from the action names (#447): an account's own pool is a bare
    name with an `:all` sibling, so a sixth one cannot be added without words."""
    names = {value for name, value in vars(real_utils).items()
             if name.isupper() and isinstance(value, str)
             and re.fullmatch(r"[a-z]+(:anon|:all)?", value)}
    own = {n for n in names if ":" not in n and n + ":all" in names}

    assert {"chat", "lookup", "generate", "recap", "upload"} <= own
    assert own <= set(real_utils.LIMIT_WORDS)


# --- never in the way -------------------------------------------------------

def test_a_failing_mailer_leaves_the_claim_alone(u, monkeypatch):
    def boom(*a):
        raise RuntimeError("mailer exploded")
    monkeypatch.setattr(notify, "send_admin_email", boom)

    results = _chat(u, 33)

    assert all(r == (True, None, 0) for r in results)


def test_a_failing_account_lookup_leaves_the_claim_alone(u, sent, monkeypatch,
                                                         action_logs):
    def boom(user_id):
        raise RuntimeError("db unreachable")
    monkeypatch.setattr(u, "_account_today", boom)

    results = _chat(u, 33)

    assert all(r == (True, None, 0) for r in results)
    assert sent == []
    line = (action_logs / "notify.log").read_text(encoding="utf-8")
    assert "kind=near-limit" in line and "result=failed" in line


# --- admin addresses, and the guide -----------------------------------------

@pytest.mark.parametrize("raw", ["", "a@x.test", " A@X.test , b@y.test ", ",,", "a@x.test,"])
def test_notify_reads_admin_emails_as_web_does(raw):
    import web
    assert notify.admin_addresses(raw) == web._admin_emails(raw)


def test_the_privacy_section_says_so():
    guide = (Path(KUANTORFLOW_PATH) / "docs" / "user-guide.md").read_text(encoding="utf-8")
    start = guide.index("## Privacy: what the site keeps")
    privacy = guide[start:guide.index("\n## ", start + 3)].lower()

    assert "daily limit" in privacy and "emailed" in privacy
