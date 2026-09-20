"""What crawlers are asked to leave alone (kuantorflow#458).

The deck becomes crawlable the moment #199 removes the keyword gate, and a
search engine's cache is the one part of opening a site that a later commit
cannot undo. So this ships **before** the gate comes off: crawlers arrive
within hours of a site becoming reachable, and the window between the gate
dropping and this file existing is exactly when indexing would happen.

Two properties carry it, and neither is obvious from reading the file:

**It has to answer without a keyword.** A crawler will never have one. That
was the reason for the gate exemption this file shipped with, and since
kuantorflow#199 there is no gate and nothing to be exempt from — so what these
cases now check is simply that it answers a visitor with no session, which is
the state every crawler is permanently in.

**The paths in it have to be paths that exist.** The file is rendered from one
declaration for that reason, and this asserts the declaration still matches
the URL map. A renamed route would otherwise fall silently out of the list
while the file went on looking perfectly correct.

What this is *not* is a control. Well-behaved crawlers obey it and nothing
else does; access is decided by #382's namespace and #127's owner filter, in
SQL. These tests are about discoverability only.
"""

import pytest


def test_it_answers_without_the_keyword(fresh_client):
    """`fresh_client` has not been through the gate, which is the state every
    crawler is permanently in."""
    r = fresh_client.get("/robots.txt")

    assert r.status_code == 200, "the gate swallowed it"
    assert r.mimetype == "text/plain"


def test_it_is_not_a_redirect(fresh_client):
    """Was `..._to_the_gate`: without the exemption this would have answered
    302 to `/enter`, and a crawler would have indexed the gate page instead.
    There is no gate to be redirected to since #199, and the assertion is kept
    because a redirect still *answers* — whatever were to introduce one, the
    result is a crawler indexing the wrong thing."""
    r = fresh_client.get("/robots.txt", follow_redirects=False)

    assert r.status_code == 200
    assert "User-agent" in r.get_data(as_text=True)


def _directives(body):
    """The file's directives, parsed rather than matched as raw text.

    Line endings are not ours to assume: git's `autocrlf` rewrites this file
    to CRLF on checkout here, and RFC 9309 accepts either -- so an assertion
    on "Allow: /" plus a newline passes or fails depending on who cloned the
    repo, which is not a property worth testing.
    """
    out = []
    for line in body.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" in line:
            name, value = line.split(":", 1)
            out.append((name.strip().lower(), value.strip()))
    return out


def test_the_deck_is_asked_to_stay_out(fresh_client):
    directives = _directives(fresh_client.get("/robots.txt").get_data(as_text=True))

    for path in ("/flashcards/", "/deck/", "/quiz", "/games/", "/topics.json"):
        assert ("disallow", path) in directives, path


def test_the_landing_page_is_not(fresh_client):
    """Option B: the front door is findable, the deck is not. A portfolio link
    wants the first; #194 is why the second is not a free choice."""
    directives = _directives(fresh_client.get("/robots.txt").get_data(as_text=True))

    assert ("allow", "/") in directives
    assert ("disallow", "/") not in directives, "this would exclude the whole site"


def _disallowed(app_module):
    """The paths the file actually asks crawlers to avoid.

    Parsed from the file rather than from a list in Python, because the file
    is the source of truth (#458): it is hand-written and reviewed in a diff,
    the way `seed_words.py` is content rather than output. A test reading a
    second copy would only ever prove the two copies agree.
    """
    from pathlib import Path
    text = Path(app_module.app.static_folder, "robots.txt").read_text(
        encoding="utf-8")
    return [line.split(":", 1)[1].strip()
            for line in text.splitlines()
            if line.strip().lower().startswith("disallow:")
            and line.split(":", 1)[1].strip()]


def test_every_path_it_names_is_a_route_that_exists(app_module):
    """The one that stops a renamed route falling quietly out of the list.

    A robots file naming a path nothing serves is not an error anybody sees:
    the file still parses, crawlers still obey it, and the route it was meant
    to cover is simply no longer covered. Checked against the app's own URL
    map, so the file and the routes cannot drift apart in silence.
    """
    rules = [r.rule for r in app_module.app.url_map.iter_rules()]

    unmatched = [p for p in _disallowed(app_module)
                 if not any(rule.startswith(p) for rule in rules)]

    assert not unmatched, (
        "robots.txt asks crawlers to avoid paths that no route serves, so "
        "whatever they were covering is now uncovered: %s" % unmatched)


def test_it_names_something(app_module):
    """The guard that keeps the test above from passing over an empty list --
    the failure mode of everything derived from a file."""
    assert len(_disallowed(app_module)) >= 4


def test_what_is_served_is_what_is_in_the_file(app_module, fresh_client):
    """One copy, handed over unchanged. Without this the file could be
    checked while something else was served."""
    from pathlib import Path
    on_disk = Path(app_module.app.static_folder, "robots.txt").read_bytes()

    assert fresh_client.get("/robots.txt").data == on_disk


def test_it_is_a_request_rather_than_a_control(fresh_client):
    """This was `test_the_gate_still_refuses_everything_it_names`, and the
    assertion has **inverted** rather than moved.

    While the gate stood, every path this file disallows answered 302, so the
    robots file could be read as a second lock. It never was one, and
    kuantorflow#199 makes that visible: the same paths now answer 200 to
    anybody. Well-behaved crawlers obey `Disallow` and nothing else does; what
    actually decides access is #382's namespace and #127's owner filter, in
    SQL.

    Worth asserting rather than deleting, because the belief that `robots.txt`
    withholds something is common and is a quiet way to ship a real leak:
    somebody adds a route holding private data, lists it here, and considers
    the job done.
    """
    for path in ("/quiz", "/games/spell_it", "/topics.json"):
        r = fresh_client.get(path, follow_redirects=False)
        assert r.status_code == 200, "%s answered %s" % (path, r.status_code)


@pytest.mark.parametrize("path", ["/flashcards/Law", "/deck/Law", "/quiz",
                                  "/games/spell_it", "/topics.json"])
def test_a_person_still_reaches_them(client, stub_deck, path):
    """The other half: robots.txt asks crawlers to stay out and changes
    nothing for a person. (Was `..._with_the_keyword_...`; there is no keyword
    since #199, and the fixture no longer enters one.)"""
    stub_deck(cards=[{"id": 1, "word": "verdict", "pos": "noun",
                      "topic": "Law", "translation_ukr": "vyrok",
                      "explanation_en": "a jury's decision",
                      "examples_en": ["The verdict came on Friday."]}])

    assert client.get(path, follow_redirects=True).status_code == 200
