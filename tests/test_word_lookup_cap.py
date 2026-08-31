"""What a word lookup may spend (kuantorflow#388).

`parse_word` was the one paid path anybody could reach. One press asks the
translator **once per language** and then the dictionary, and since #353 that
translator is a licensed API on our own key — so an uncapped lookup is a
metered spend with no ceiling, which is the failure #200 fixed for uploads and
#237 never had.

**Every test here checks the same thing twice**: that the refusal happened, and
that the providers were never reached. The second is the point. A guard that
runs after `lookup_word()` refuses nothing that matters — the money is already
gone — and that is exactly the bug #200 was filed about.

The other rule the file exists for is the shape of the ceilings:

    session nudge   3 per browser session, a cookie, resettable, a *nudge*
    account         50 a day, in a row
    anonymous       300 a day site-wide, in the row whose user_id is 0

and the site-wide one counts **anonymous lookups only**. That is the one
deliberate difference from #237's counter, and #199 names the reason: with a
shared ceiling, one person in a loop spends the day's budget and every genuine
visitor is told to come back tomorrow. Here they cannot reach the people who
signed up.

The counter itself is proved against a real MySQL in
`test_word_lookup_cap_db.py` (marker `db`).
"""

import pytest


CARD = {"word": "resilient", "pos": "adjective", "topic": "vocab",
        "explanation_en": "able to recover quickly"}


@pytest.fixture()
def providers(app_module, monkeypatch):
    """What the lookup would cost, if it ran. Returns the list of words asked."""
    asked = []

    def fake_lookup(word, topic=None, **providers):
        asked.append(word)
        return [dict(CARD, word=word, topic=topic)]

    monkeypatch.setattr(app_module, "lookup_word", fake_lookup)
    return asked


def _look_up(client, word="resilient"):
    return client.post("/", data={"action": "parse_word", "word": word,
                                  "topic": "vocab", "force_lookup": "1"}
                       ).get_data(as_text=True)


# --- the anonymous allowance ------------------------------------------------

def test_an_anonymous_visitor_gets_their_free_words(client, providers,
                                                    app_module, monkeypatch):
    """A small allowance rather than an account at the door (#200's answer for
    uploads). The lookup panel is the shop window: an empty one converts
    nobody, and somebody who has looked up three words and wants a fourth is
    exactly the person worth asking for an account."""
    monkeypatch.setattr(app_module, "LOOKUP_ANON_LIMIT", 3)

    for word in ("one", "two", "three"):
        _look_up(client, word)

    assert providers == ["one", "two", "three"]


def test_and_then_the_sign_in_prompt(client, providers, app_module,
                                     monkeypatch):
    monkeypatch.setattr(app_module, "LOOKUP_ANON_LIMIT", 1)
    _look_up(client, "one")

    body = _look_up(client, "two")

    assert providers == ["one"], "the refused lookup must not reach a provider"
    assert "free words" in body
    assert 'kfSignInRequired("' in body, "and it offers the way on"


def test_the_nudge_is_a_cookie_and_the_ceiling_is_not(client, providers,
                                                      app_module, monkeypatch):
    """#164 documents this about its own session counter and it is equally true
    here: clearing cookies resets the nudge. That is fine, and saying so is
    what stops somebody mistaking it for a spend cap -- the daily row below is
    the thing that bounds the bill."""
    monkeypatch.setattr(app_module, "LOOKUP_ANON_LIMIT", 1)
    _look_up(client, "one")
    _look_up(client, "two")
    assert providers == ["one"]

    client.delete_cookie("session")
    with client.session_transaction() as session:
        session["access_granted"] = True

    _look_up(client, "three")
    assert providers == ["one", "three"], (
        "a nudge that survived a cookie clear would be a different feature")


# --- the ceilings that are not nudges ---------------------------------------

def test_an_account_past_its_day_is_told_signing_in_will_not_help(
        user_client, providers, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "claim_word_lookup",
                        lambda *a: (False, "user", 50))

    body = _look_up(user_client)

    assert providers == []
    assert "tomorrow" in body.lower()
    assert 'kfSignInRequired("' not in body, (
        "they are signed in; a ceiling their account has reached is not "
        "something signing in fixes")


def test_the_anonymous_ceiling_offers_a_way_past_it(client, providers,
                                                    app_module, monkeypatch):
    """Unlike the account ceiling, this one *is* answered by signing in --
    an account has a ceiling of its own."""
    monkeypatch.setattr(app_module, "claim_word_lookup",
                        lambda *a: (False, "anonymous", 300))

    body = _look_up(client)

    assert providers == []
    assert 'kfSignInRequired("' in body


def test_a_signed_in_learner_is_claimed_against_their_own_row(
        user_client, providers, app_module, monkeypatch):
    """The design in one assertion. Anonymous traffic is counted on row 0 and a
    learner on their own, so a day of anonymous abuse leaves the people who
    signed up with everything they had."""
    claimed = []
    monkeypatch.setattr(app_module, "claim_word_lookup",
                        lambda user_id, user_limit, anon_limit:
                        claimed.append((user_id, user_limit, anon_limit))
                        or (True, None, 1))

    _look_up(user_client)

    (user_id, user_limit, anon_limit), = claimed
    assert user_id is not None, "a learner is not counted as anonymous traffic"
    assert (user_limit, anon_limit) == (app_module.LOOKUP_USER_DAILY,
                                        app_module.LOOKUP_ANON_DAILY)


def test_a_blocked_account_may_not_spend_one(user_client, providers,
                                             block_state, app_module):
    """#126 drew its line at writing, when a lookup was free scraping. Since
    #353 it is an API call on our own key, and #237 already refuses a blocked
    account the other paid activity -- two answers to that question would be
    the odd thing."""
    block_state.block()

    body = _look_up(user_client)

    assert providers == []
    assert "blocked" in body.lower()


def test_a_dead_counter_does_not_take_the_lookup_down(client, providers,
                                                      app_module, monkeypatch):
    """Best-effort in the same direction as #164's and #237's counters: an
    unreachable database cannot enforce a ceiling, and a lookup still works
    without one -- the review popup needs no database to draw its cards."""
    def boom(*a):
        raise RuntimeError("database is away")

    monkeypatch.setattr(app_module, "claim_word_lookup", boom)

    _look_up(client)

    assert providers == ["resilient"]


# --- what must not cost a slot ----------------------------------------------

def test_the_duplicate_warning_costs_nothing(client, providers, app_module,
                                             monkeypatch):
    """#145 asks before the lookup, so a word the learner has not decided about
    yet must not take one of their three -- they have not looked anything up."""
    claimed = []
    monkeypatch.setattr(app_module, "flashcard_word_exists", lambda word: True)
    monkeypatch.setattr(app_module, "claim_word_lookup",
                        lambda *a: claimed.append(a) or (True, None, 1))

    body = client.post("/", data={"action": "parse_word", "word": "resilient",
                                  "topic": "vocab"}).get_data(as_text=True)

    assert 'id="dup-warning-modal"' in body
    assert (providers, claimed) == ([], [])


def test_a_word_that_was_not_typed_costs_nothing(client, app_module,
                                                 monkeypatch):
    claimed = []
    monkeypatch.setattr(app_module, "claim_word_lookup",
                        lambda *a: claimed.append(a) or (True, None, 1))

    client.post("/", data={"action": "parse_word", "word": "  ",
                           "topic": "vocab"})

    assert claimed == []


def test_a_refusal_is_claimed_once_not_twice(client, app_module, monkeypatch):
    """`_lookup_refusal()` claims the slot as it answers, so the route has to
    ask it once and keep the answer. Asking again to decide how to render the
    refusal would take a second slot for a lookup that never happened."""
    calls = []
    monkeypatch.setattr(app_module, "claim_word_lookup",
                        lambda *a: calls.append(a) or (True, None, 1))

    _look_up(client)

    assert len(calls) == 1


# --- the other door ---------------------------------------------------------

def test_the_edit_dialogs_lookup_is_capped_too(user_client, providers,
                                               app_module, monkeypatch):
    """#191's *Look up & update* spends the same providers on the same key.
    Leaving it out would not be a smaller cap -- it would be a hole in the
    account ceiling, reachable from every card page."""
    monkeypatch.setattr(app_module, "claim_word_lookup",
                        lambda *a: (False, "user", 50))

    response = user_client.post("/lookup.json", json={"word": "resilient"})

    assert response.status_code == 429
    assert providers == []
    assert "tomorrow" in response.get_json()["error"].lower()


def test_and_still_answers_when_there_is_room(user_client, providers,
                                              app_module):
    response = user_client.post("/lookup.json", json={"word": "resilient"})

    assert response.status_code == 200
    assert providers == ["resilient"]
