"""The site is open: no keyword, and nothing asks for one (kuantorflow#199).

This is `test_access_gate.py` **inverted**, not deleted. The old file asserted
that every page answered 302 to `/enter` until a shared password was typed;
the same pages are the ones that must now answer 200 to somebody who has typed
nothing, and that is worth a file rather than an absence. A gate coming back
by accident — a stray `before_request`, a redirect added for some other
reason — would otherwise show up as nothing at all in a green run.

**What the keyword was, and was not.** It was never an authorisation. It was
one string, handed out by hand, that every holder could pass on and nobody
could revoke, and it protected exactly one thing: the *rate* at which
strangers could reach paths that spend money. So the honest replacement is not
another door but a ceiling on each of those paths, which is what #200, #388,
#447 and #456 built, and why #199 shipped last of the five.

Two of those ceilings are pinned here rather than only in their own files,
because the property that matters on this page is not "the ceiling works" —
it is that **opening the site did not open a paid path with it**. Their own
files test the arithmetic; this one tests that the guard is still in front of
the spend now that anybody can reach it.

What is deliberately *not* here: the individual refusal messages, the
per-account numbers, and the pools. Those belong to #447 and #456 and are
tested there.
"""

import pytest


PUBLIC_PAGES = ["/", "/quiz", "/games/real_or_fake", "/topics.json",
                "/robots.txt"]


# --- the site answers somebody who has typed nothing ------------------------

@pytest.mark.parametrize("path", PUBLIC_PAGES)
def test_a_page_answers_a_visitor_with_no_session(fresh_client, path):
    """`fresh_client` has no session at all, which is the state every first
    visitor and every crawler is in."""
    r = fresh_client.get(path)

    assert r.status_code == 200, f"{path} answered {r.status_code}"


@pytest.mark.parametrize("path", PUBLIC_PAGES)
def test_a_page_does_not_redirect_a_visitor_anywhere(fresh_client, path):
    """Separate from the case above, because a gate reintroduced under another
    name would be a redirect rather than a refusal -- and `follow_redirects`
    is on by default in enough helpers that a 302 can pass unnoticed."""
    r = fresh_client.get(path, follow_redirects=False)

    assert r.status_code == 200, (
        f"{path} redirected to {r.headers.get('Location')!r}")


def test_there_is_no_gate_endpoint(app_module):
    """The route itself, so that a half-removal is caught: leaving `/enter`
    registered while dropping the `before_request` gives a site that is open
    *and* still serves a keyword form nobody needs."""
    endpoints = {r.endpoint for r in app_module.app.url_map.iter_rules()}

    assert "gate" not in endpoints
    assert not any(str(r) == "/enter" for r in app_module.app.url_map.iter_rules())


def test_nothing_reads_a_keyword_any_more(app_module):
    """`ACCESS_KEYWORD` is gone from the configuration rather than left
    defined and unread. A dangling constant is how a removed feature comes
    back: the next person finds it and wires it up."""
    import web

    assert not hasattr(web, "ACCESS_KEYWORD")


def test_the_only_before_request_is_the_session_repair(app_module):
    """There is exactly one, and it is #148's. Asserted by name because this
    is where a gate would return -- `before_request` is the hook that blocks
    every page at once, and a new one is a one-line change.
    """
    hooks = [f.__name__ for f in app_module.app.before_request_funcs[None]]

    assert hooks == ["drop_identity_from_before_the_users_table"], hooks


# --- what the keyword was actually protecting -------------------------------

def test_writing_still_needs_an_account(fresh_client):
    """#125, and it never depended on the gate. Worth restating here because
    "the site is open" is exactly the sentence somebody would read as "anyone
    can now add cards"."""
    r = fresh_client.post("/cards/add", data={"word": "x"})

    assert r.status_code == 403
    assert r.get_json()["sign_in_required"] is True


def test_settings_are_still_read_only_for_an_anonymous_visitor(fresh_client):
    """#102. The popup is open to everyone and the saves are not."""
    r = fresh_client.post("/settings", json={"translator": "microsoft"})

    assert r.status_code == 403


def test_the_chat_still_refuses_past_the_anonymous_allowance(fresh_client,
                                                             monkeypatch):
    """#164's session nudge, which is the first thing an anonymous visitor
    meets. Pinned here because the chat is the most expensive path in the app
    -- `ai_agent` answers with `claude-opus-5`, where everything this repo
    calls itself is Haiku.

    `MYKOLA_AVAILABLE` is forced on the way every other chat test does it:
    without the agent the route answers 503 before reaching the quota, which
    would make this pass for the wrong reason on a machine that has no agent
    and fail on one that does.
    """
    monkeypatch.setattr("chat.MYKOLA_AVAILABLE", True)
    with fresh_client.session_transaction() as sess:
        sess["anon_messages"] = 10_000

    r = fresh_client.post("/mykola/chat", json={"question": "hello"})

    assert r.status_code == 402
    assert r.get_json()["sign_in_required"] is True


def test_the_word_lookup_refuses_before_it_calls_a_provider(fresh_client,
                                                            monkeypatch):
    """#388, and the assertion is about **order** rather than about the
    refusal: a guard that runs after the providers is a guard that has already
    paid. Proved with a tripwire rather than by reading the message, because
    the page renders either way.
    """
    import web

    called = []
    monkeypatch.setattr("parsers.lookup_word",
                        lambda *a, **kw: called.append(a) or [])
    with fresh_client.session_transaction() as sess:
        sess[web.LOOKED_UP_COUNT_KEY] = 10_000

    # `action` and `force_lookup` are both required and both easy to leave
    # out: without `action` the route does nothing at all, and without
    # `force_lookup` #145's duplicate warning can answer first. A POST missing
    # either renders a page and calls nothing, which passes this assertion for
    # the wrong reason -- it did, until break 6 showed the test could not fail.
    fresh_client.post("/", data={"action": "parse_word", "word": "resign",
                                 "topic": "vocab", "force_lookup": "1"})

    assert not called, "a provider was called after the ceiling was reached"


def test_the_lookup_tripwire_is_wired_up(fresh_client, monkeypatch):
    """The control for the case above: with the ceiling *not* reached, the
    same POST must reach the provider. Without this, the test above passes on
    any request that quietly does nothing -- which is exactly how it was first
    written."""
    called = []
    monkeypatch.setattr("parsers.lookup_word",
                        lambda *a, **kw: called.append(a) or [])

    fresh_client.post("/", data={"action": "parse_word", "word": "resign",
                                 "topic": "vocab", "force_lookup": "1"})

    assert called, "the POST never reached the lookup, so the tripwire is idle"


def test_the_upload_still_needs_an_account(fresh_client):
    """#200 -- the first of the five, and the one that gave the pattern: the
    refusal is at the door, before `file.read()`, because which file calls
    Claude cannot be known without parsing it and parsing is the thing being
    paid for."""
    r = fresh_client.post("/upload_notes", data={})

    assert r.status_code in (403, 404), r.status_code
