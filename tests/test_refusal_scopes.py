"""Every refused pool says the right thing, and logs its own limit (kuantorflow#643).

A paid action's claim refuses with one of three scopes -- the account's own
pool (`user`), the shared anonymous one (`anonymous`), or the whole site's
(`daily`) -- and only one of them is something signing in fixes: the anonymous
pool, because an account has a pool of its own (#456). `web.chat_refusal()`
always mapped all three; the lookup and text refusals had two branches each:

* a lookup refused by the **site-wide** pool told a signed-in learner to sign
  in, and offered the button, and logged the anonymous limit (150, not 250);
* a text refused by the **anonymous** pool offered no sign-in, and logged the
  site-wide limit (60, not 20).

The limits asserted are read from `web`, never written here.
"""

import pytest

import web

LEARNER = {"id": 7, "email": "learner@example.test", "name": "Learner"}

# scope -> (signed in?, sign-in offered?)
EXPECTED = {
    "user": (True, False),
    "anonymous": (False, True),
    "daily": (True, False),
}

LOOKUP_LIMITS = {"user": "LOOKUP_USER_DAILY", "anonymous": "LOOKUP_ANON_DAILY",
                 "daily": "LOOKUP_ALL_DAILY"}
TEXT_LIMITS = {"user": "GENERATION_USER_DAILY", "anonymous": "GENERATION_ANON_DAILY",
               "daily": "GENERATION_DAILY_LIMIT"}


def _refuse(app_module, monkeypatch, claim, scope, refusal, signed_in):
    monkeypatch.setattr(f"utils.{claim}", lambda *a, **k: (False, scope, 99))
    with web.app.test_request_context("/"):
        from flask import session
        if signed_in:
            session["user"] = dict(LEARNER)
        return refusal()


def _limit_line(action_logs, name):
    lines = [l for l in (action_logs / f"{name}.log").read_text(encoding="utf-8").splitlines()
             if " LIMIT " in l]
    assert len(lines) == 1, lines
    return lines[0]


@pytest.mark.parametrize("scope", sorted(EXPECTED))
def test_a_refused_lookup_offers_sign_in_only_where_it_helps(app_module, monkeypatch,
                                                             action_logs, scope):
    signed_in, offers = EXPECTED[scope]
    answer = _refuse(app_module, monkeypatch, "claim_word_lookup", scope,
                     web._lookup_refusal, signed_in)

    assert answer["sign_in"] is offers
    assert ("sign in" in answer["message"].lower()) is offers, answer["message"]


@pytest.mark.parametrize("scope", sorted(EXPECTED))
def test_a_refused_lookup_logs_its_own_pools_limit(app_module, monkeypatch,
                                                   action_logs, scope):
    _refuse(app_module, monkeypatch, "claim_word_lookup", scope,
            web._lookup_refusal, EXPECTED[scope][0])

    line = _limit_line(action_logs, "dict")
    assert f"kind={scope}" in line
    assert f"limit={getattr(web, LOOKUP_LIMITS[scope])} " in line + " "


@pytest.mark.parametrize("scope", sorted(EXPECTED))
def test_a_refused_text_offers_sign_in_only_where_it_helps(app_module, monkeypatch,
                                                           action_logs, scope):
    signed_in, offers = EXPECTED[scope]
    answer = _refuse(app_module, monkeypatch, "claim_text_generation", scope,
                     web._generation_refusal, signed_in)

    assert answer["sign_in"] is offers
    assert ("sign in" in answer["message"].lower()) is offers, answer["message"]


@pytest.mark.parametrize("scope", sorted(EXPECTED))
def test_a_refused_text_logs_its_own_pools_limit(app_module, monkeypatch,
                                                 action_logs, scope):
    _refuse(app_module, monkeypatch, "claim_text_generation", scope,
            web._generation_refusal, EXPECTED[scope][0])

    line = _limit_line(action_logs, "gen_texts")
    assert f"kind={scope}" in line
    assert f"limit={getattr(web, TEXT_LIMITS[scope])} " in line + " "


def test_the_three_limits_differ_so_the_log_tells_them_apart():
    # Otherwise "logs its own limit" could pass by coincidence.
    for limits in (LOOKUP_LIMITS, TEXT_LIMITS):
        assert len({getattr(web, name) for name in limits.values()}) == 3
