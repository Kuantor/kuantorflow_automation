"""No route reaches a real database (kuantorflow#418, step one).

The suite's most important property is not asserted anywhere: that it never
opens a connection to whatever `DB_*` points at. It is held up instead by
`conftest.py` stubbing a handful of names **on the `app` module** — and that
works only because every database call currently lives in `app.py`'s own
namespace.

#418 moves routes into feature modules. The moment `index()` lives in
`cards.py` with its own `from utils import get_topics_by_section`, the stub in
`conftest` stops reaching it, **the test still passes**, and the suite quietly
starts reading a real database. That is not hypothetical: this project has
already had tests increment the live `text_generation_usage` counter until an
account hit its daily ceiling and unrelated tests began failing.

So this file goes in **before** any code moves. It patches the one function
every database call in this project funnels through — `utils.get_db_connection`
— to raise, and walks the routes. If a route reaches a real connection, the
run goes red immediately and names the route.

**The route list is derived from the app's own URL map**, not written out here,
so a route added tomorrow is covered without anyone remembering this file. What
is written out is the *exclusions*, each with a reason, because an exclusion is
a decision and a silent gap is not.
"""

import pytest
import cards


# Rules this walk does not visit, and why. Every entry is a decision.
SKIPPED = {
    "/static/<path:filename>": "serves a file; no application code runs",
    "/mykola-media/<path:filename>": "serves a file from the agent repo",
    "/mykola-static/<path:filename>": "serves a file from the agent repo",
    "/enter": "the gate itself; the client fixture is already through it",
    "/logout": "clears the session the rest of the walk depends on",
    "/login/google": "redirects to Google",
    "/auth/google/callback": "expects a code from Google",
    "/topics/generate/stream": "server-sent events, and it spends real money",
}


def _paths(app_module, topic, games_module):
    """Every GET rule worth visiting, with its arguments filled in."""
    paths = []
    for rule in app_module.app.url_map.iter_rules():
        if "GET" not in rule.methods or rule.rule in SKIPPED:
            continue
        if not rule.arguments:
            paths.append(rule.rule)
        elif rule.arguments == {"topic"}:
            paths.append(rule.rule.replace("<topic>", topic))
        elif rule.arguments == {"game"}:
            paths.extend(rule.rule.replace("<game>", slug)
                         for slug in games_module.ACTIVITIES)
        else:
            raise AssertionError(
                f"{rule.rule} takes {sorted(rule.arguments)} and this walk does "
                "not know how to fill them — add it to SKIPPED with a reason, "
                "or teach this function the argument")
    return sorted(paths)


CARDS = [
    {"id": 1, "word": "verdict", "pos": "noun", "topic": "Law",
     "translation_ukr": "vyrok", "translation_rus": "prigovor",
     "explanation_en": "a jury's decision",
     "examples_en": ["The verdict came after three days of argument."]},
    {"id": 2, "word": "parole", "pos": "noun", "topic": "Law",
     "translation_ukr": "umovne", "translation_rus": "uslovnoe",
     "explanation_en": "early release from prison",
     "examples_en": ["He was released on parole after two years."]},
    {"id": 3, "word": "acquit", "pos": "verb", "topic": "Law",
     "translation_ukr": "vypravdaty", "translation_rus": "opravdat",
     "explanation_en": "to decide somebody is not guilty",
     "examples_en": ["The court moved to acquit him of every charge."]},
]


@pytest.fixture()
def deck(stub_deck):
    return stub_deck(cards=CARDS)


@pytest.fixture()
def no_database(app_module, monkeypatch):
    """The one function every database call in this project goes through."""
    import utils
    reached = []

    def refuse(*args, **kwargs):
        reached.append(True)
        raise AssertionError("a real database connection was opened")

    monkeypatch.setattr(utils, "get_db_connection", refuse)
    return reached


def test_the_walk_visits_something(app_module, deck):
    """A guard against the whole file passing because it visited nothing —
    the failure mode of every derived list."""
    import games
    assert len(_paths(app_module, "Law", games)) >= 10


def test_no_page_reaches_a_real_database(client, app_module, deck, no_database):
    """The property the suite has relied on without stating it.

    Each page is fetched with the standard fixtures in place. A route that
    reaches `utils.get_db_connection` has escaped them — which is exactly what
    #418's moves risk, and exactly what nothing else here would notice.
    """
    import games
    failures = []
    for path in _paths(app_module, "Law", games):
        no_database.clear()
        try:
            response = client.get(path)
            answered = response.status_code
        except AssertionError:
            answered = "raised"
        # **The attempt is the assertion, not the status code.** Several
        # read paths catch a dead database and degrade to an empty page on
        # purpose -- `_visible_sections()` says so in as many words -- so a
        # route that reached a real connection can still answer 200 with
        # nothing in it. Asserting on the response was this test's first
        # version, and it passed while the very move it exists to catch was
        # simulated against it.
        if no_database:
            failures.append(f"{path} -> opened a connection (answered {answered})")
    assert not failures, (
        "routes that did not stay offline: " + "; ".join(failures))


def test_the_guard_itself_works(client, app_module, deck, no_database):
    """Proves the patch bites, so a green run above means something. Calling
    the real function is what every unstubbed route would end up doing."""
    import utils
    with pytest.raises(AssertionError, match="real database connection"):
        utils.get_db_connection()
    assert no_database, "the refusal did not record the attempt"
