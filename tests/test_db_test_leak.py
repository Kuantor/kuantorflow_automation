"""What a failed database check is allowed to say (kuantorflow#457).

`/db/test` is #184's "is the database reachable?" diagnostic, POSTed by the
Settings popup and answered inline so a half-typed lookup is not lost to a
redirect. It used to return `str(e)`, and mysql-connector's message names the
account and the server it tried:

    1045 (28000): Access denied for user 'kuantorflow'@'localhost'
    (using password: YES)

On PythonAnywhere that is the account name and its MySQL host, handed to
anybody who can POST -- and nothing on this route checks who is asking.

**The severity is genuinely low and that is not the point.** There is no
injection here, no data, and MySQL is not reachable from outside
PythonAnywhere; this is an information leak rather than a way in. It is closed
now because #199 turns "anybody who can POST" into the open internet, and
because it costs four lines.

Three things are pinned here, and the second and third are the ones that would
rot:

**The failure message discloses nothing.** Asserted against a message shaped
like the real driver's, not against a placeholder, because a test that raises
`RuntimeError("db down")` cannot tell a generic answer from one that happens
to contain no infrastructure -- which is how the assertion it replaces read.

**The endpoint stays open, and the button stays visible.** That is option B of
the three the ticket set out, and it is a *product* decision rather than a
security one: a learner looking at an empty deck cannot otherwise tell #127's
individual-cards filter or #382's private topics -- both working exactly as
intended -- from a database that is not answering. Admin-only would close the
leak by removing that use, so if somebody later adds a permission check here,
these tests say what would be lost.

**The reason is moved, not deleted.** A generic message with nothing written
anywhere is not a fix, it is the diagnostic thrown away. The real exception
has to reach `app.logger`, which is where `web.py`'s spending guards already
report their own failures and where the person who can act on it is looking.
"""

import logging

import pytest


# Shaped like the real thing rather than a placeholder: this is what
# mysql-connector says when `DB_PASSWORD` is wrong, measured on 20 September.
REAL_DRIVER_MESSAGE = (
    "1045 (28000): Access denied for user 'kuantorflow'@'localhost' "
    "(using password: YES)")

# Every fragment of it that must not reach the caller. Listed one by one so a
# failure names *which* thing leaked.
SECRETS = [
    "kuantorflow",      # the database account, and the PythonAnywhere account
    "localhost",        # the host
    "1045",             # the error number
    "28000",            # the SQL state
    "using password",   # whether credentials were sent at all
    "Access denied",
]


@pytest.fixture()
def dead_db(app_module, monkeypatch):
    """A database that refuses with the driver's own words."""
    def boom():
        raise RuntimeError(REAL_DRIVER_MESSAGE)
    monkeypatch.setattr("utils.get_db_connection", boom)
    return boom


# --- the leak itself --------------------------------------------------------

def test_a_failure_discloses_nothing_about_the_database(client, dead_db):
    """The whole ticket in one assertion, over the raw response body rather
    than one JSON field -- the leak is about what crosses the wire, and a
    future key holding the reason would pass a check on `error` alone."""
    body = client.post("/db/test").get_data(as_text=True)

    leaked = [s for s in SECRETS if s.lower() in body.lower()]
    assert not leaked, f"the response still names: {leaked}"


def test_the_failure_message_is_a_sentence_for_the_person_who_asked(client,
                                                                    dead_db):
    """Generic is not the same as empty. The button exists to answer a
    question, and a blank or absent message turns a working diagnostic into a
    control that appears to do nothing."""
    answer = client.post("/db/test").get_json()

    assert answer["ok"] is False
    assert answer["error"], "the failure says nothing at all"
    assert len(answer["error"].split()) >= 4, "not a sentence"


def test_a_failure_is_still_a_200(client, dead_db):
    """#184's decision, and it stands: the caller asked a question and gets an
    answer. A 500 would make the popup's `.catch` fire and report that the
    *site* could not be reached, which names the wrong culprit."""
    assert client.post("/db/test").status_code == 200


def test_the_check_still_never_redirects(client, dead_db):
    """The reason it is JSON at all: the popup opens on every page, and a
    redirect would drop the visitor onto the index from wherever they were."""
    r = client.post("/db/test", follow_redirects=False)

    assert r.status_code == 200


def test_a_reachable_database_is_unchanged(client, app_module, monkeypatch):
    """The success path is not part of this change and must not become part of
    it: `{"ok": True}` is what the popup's JavaScript tests."""
    monkeypatch.setattr("utils.get_db_connection",
                        lambda: type("C", (), {"close": lambda self: None})())

    assert client.post("/db/test").get_json() == {"ok": True}


# --- moved, not deleted -----------------------------------------------------

def test_the_real_reason_reaches_the_log(client, dead_db, caplog):
    """Without this, "returns a generic message" is satisfied by throwing the
    diagnostic away -- which passes every other test on this page and leaves
    an admin with a button that says the database is down and no way to find
    out why."""
    with caplog.at_level(logging.ERROR):
        client.post("/db/test")

    written = "\n".join(r.getMessage() + "\n" + (r.exc_text or "")
                        for r in caplog.records)

    assert REAL_DRIVER_MESSAGE in written, (
        "the cause was not logged; the diagnostic is gone rather than moved")


def test_the_log_carries_a_traceback_not_just_the_message(client, dead_db,
                                                          caplog):
    """`app.logger.exception` rather than `.error`. The message alone does not
    say *where* the connection was attempted from, and a database check that
    fails in `get_db_connection` and one that fails in `close` are different
    problems."""
    with caplog.at_level(logging.ERROR):
        client.post("/db/test")

    assert any(r.exc_info for r in caplog.records), "no traceback was recorded"


# --- option B: it stays open, and the button stays -------------------------

def test_an_anonymous_visitor_may_still_ask(client, app_module, monkeypatch):
    """No permission check, deliberately. A read-only ping that discloses
    nothing needs no rule about who may send it, and Settings being read-only
    for anonymous visitors (#102) is about *writing*, which this does not do.
    """
    monkeypatch.setattr("utils.get_db_connection",
                        lambda: type("C", (), {"close": lambda self: None})())

    assert client.post("/db/test").status_code == 200


def _button_tag(body):
    """The `<button id="test-db-btn" ...>` opening tag, on its own.

    Extracted rather than substring-matched, because `id="test-db-btn" hidden`
    contains `id="test-db-btn"` -- so the obvious assertion passes against a
    button nobody can see. Proved by writing it the obvious way first and
    hiding the button: the test stayed green.
    """
    at = body.index('id="test-db-btn"')
    start = body.rindex("<button", 0, at)
    return body[start:body.index(">", at) + 1]


def test_the_button_is_not_hidden_from_anyone(client):
    """Option C would have removed it from an ordinary learner's panel. It was
    not taken, and this is the assertion that records the choice: a learner
    with an empty deck is the person the button is *for*."""
    tag = _button_tag(client.get("/").get_data(as_text=True))

    assert "hidden" not in tag, f"the button is hidden: {tag}"
    assert "disabled" not in tag, f"the button is disabled: {tag}"


def _db_test_handler(body):
    """The JavaScript that calls `/db/test`, anchored on the rendered URL.

    Anchoring on the `test-db-result` *element* instead reaches the markup at
    around character 14,000 while the handler is at 58,000 -- so a window cut
    from there contains no JavaScript at all and any assertion over it is
    vacuous. That is how this test first passed while the thing it forbids was
    still in the file.

    `//` comments are stripped, because the comment explaining why the prefix
    was removed necessarily quotes the prefix. A test that reads prose as code
    fails on the sentence documenting the fix.
    """
    at = body.index("/db/test")
    window = body[at:at + 1500]
    return "\n".join(line.split("//")[0] for line in window.splitlines())


def test_the_popup_shows_the_message_as_the_server_wrote_it(client):
    """No "Error:" prefix since #457: the text is now a sentence written for
    the reader rather than a driver exception, and prefixing it reads as
    though the check itself had gone wrong."""
    handler = _db_test_handler(client.get("/").get_data(as_text=True))

    assert "data.error" in handler, "the handler stopped reading the message"
    assert '"Error: "' not in handler
