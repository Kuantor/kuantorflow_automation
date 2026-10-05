"""A request id and one log line per request (kuantorflow#555).

The action logs answer "what happened to this person's deck?". Nothing
answered "how is the site doing?": how long pages take for real learners, and
which lines belong to one request. #555 gives every request an id, sent back
as `X-Request-ID`, writes one line per request to `requests.log`, and puts the
same id on every other line the request writes.

What is pinned here:

* **the header** is present and differs between requests;
* **one line per request**, with method, path, endpoint, status, ms, the
  database connections opened, and the account id -- **never the email**, and
  never the query string;
* **static files are not logged**;
* **a request that raises** still leaves its line, as a 500;
* **logging never breaks a request**;
* `get_db_connection()` **counts** against the request, which is how #554 is
  judged in production;
* applog's other lines and the server's own lines **carry the id**, and a line
  with no request behind it carries none.
"""

import logging
import re

import pytest
from flask import Response, g
from flask.logging import default_handler

import applog
import utils
import web

TEST_USER_EMAIL = "test.user@gmail.com"


def _lines(action_logs, name="requests"):
    path = action_logs / f"{name}.log"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _fields(line):
    return dict(re.findall(r"(\w+)=('(?:[^'\\]|\\.)*'|\S+)", line))


# --- the header -------------------------------------------------------------

def test_every_response_carries_a_request_id(client):
    first = client.get("/robots.txt").headers.get("X-Request-ID")
    second = client.get("/robots.txt").headers.get("X-Request-ID")

    assert first and re.fullmatch(r"[0-9a-f]{8}", first)
    assert second and second != first


# --- the line ---------------------------------------------------------------

def test_one_line_per_request_with_its_fields(client, action_logs):
    response = client.get("/robots.txt?word=resilient")
    lines = _lines(action_logs)

    assert len(lines) == 1
    fields = _fields(lines[0])
    assert " REQUEST " in lines[0]
    assert fields["method"] == "GET"
    assert fields["path"] == "/robots.txt", "the path alone, not the query"
    assert "resilient" not in lines[0]
    assert fields["endpoint"] == "robots_txt"
    assert fields["status"] == "200"
    assert float(fields["ms"]) >= 0
    assert fields["db"] == "0"
    assert fields["user_id"] == "anonymous"
    assert fields["rid"] == response.headers["X-Request-ID"]


def test_a_signed_in_line_has_the_id_and_never_the_email(user_client,
                                                         action_logs):
    user_client.get("/robots.txt")
    text = (action_logs / "requests.log").read_text(encoding="utf-8")

    assert _fields(text.splitlines()[0])["user_id"] == "7"
    assert TEST_USER_EMAIL not in text
    assert "test.user" not in text


def test_a_missing_page_is_logged_with_its_status(client, action_logs):
    client.get("/no-such-page")

    fields = _fields(_lines(action_logs)[0])
    assert fields["status"] == "404"
    assert fields["endpoint"] == "-"


def test_static_files_are_not_logged(client, action_logs):
    assert client.get("/static/css/style.css").status_code == 200

    assert _lines(action_logs) == []


@pytest.fixture()
def broken_view(monkeypatch):
    def boom():
        raise RuntimeError("broken view")
    monkeypatch.setitem(web.app.view_functions, "robots_txt", boom)


def test_a_request_that_raises_is_logged_as_a_500(client, action_logs,
                                                  broken_view):
    """In production Flask turns the exception into a 500 and still runs
    `after_request`."""
    assert client.get("/robots.txt").status_code == 500

    lines = _lines(action_logs)
    assert len(lines) == 1
    assert _fields(lines[0])["status"] == "500"


def test_a_propagated_exception_still_leaves_its_line(client, action_logs,
                                                      broken_view, monkeypatch):
    """With exceptions propagated (debug, `TESTING`) `after_request` never
    runs; the teardown hook writes the line instead, as the 500 the visitor
    would have got."""
    monkeypatch.setitem(web.app.config, "PROPAGATE_EXCEPTIONS", True)

    with pytest.raises(RuntimeError):
        client.get("/robots.txt")

    lines = _lines(action_logs)
    assert len(lines) == 1
    assert _fields(lines[0])["status"] == "500"


def test_logging_never_breaks_a_request(client, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(applog, "request_served", broken)

    response = client.get("/robots.txt")

    assert response.status_code == 200
    assert response.headers.get("X-Request-ID"), "the id survives a broken log"


# --- counting connections (#554 is judged by this) --------------------------

class _FakeConnection:
    def close(self):
        pass


@pytest.fixture()
def fake_driver(monkeypatch):
    """The real `get_db_connection()`, with the MySQL driver underneath it
    stubbed: everything up to the network runs, including the count."""
    import mysql.connector
    monkeypatch.setattr(mysql.connector, "connect",
                        lambda **kwargs: _FakeConnection())
    monkeypatch.setenv("DB_PASSWORD", "test-only")


def test_connections_are_counted_against_the_request(action_logs, fake_driver):
    """Two connections in one request are `db=2` on its line."""
    with web.app.test_request_context("/progress"):
        web.app.preprocess_request()
        utils.get_db_connection().close()
        utils.get_db_connection().close()
        assert g.db_connects == 2
        web.app.process_response(Response("ok"))

    assert _fields(_lines(action_logs)[0])["db"] == "2"


def test_a_connection_outside_a_request_still_works(fake_driver):
    """The scripts have no request: nothing to count against, and the
    connection is returned as before."""
    assert isinstance(utils.get_db_connection(), _FakeConnection)


# --- the id on the other lines ----------------------------------------------

def test_applog_lines_carry_the_request_id(action_logs):
    with web.app.test_request_context("/"):
        web.app.preprocess_request()
        rid = g.request_id
        applog.lookup_started("resilient", "claude", "oxford")

    line = _lines(action_logs, "dict")[0]
    assert line.endswith(f"rid={rid}")


def test_a_line_with_no_request_has_no_id(action_logs):
    applog.lookup_started("resilient", "claude", "oxford")

    assert "rid=" not in _lines(action_logs, "dict")[0]


def test_the_server_log_lines_carry_the_request_id():
    record = logging.LogRecord("kuantorflow", logging.ERROR, __file__, 1,
                               "Could not read the block state", None, None)
    with web.app.test_request_context("/"):
        web.app.preprocess_request()
        rid = g.request_id
        for f in default_handler.filters:
            f.filter(record)
        text = default_handler.format(record)

    assert f"rid={rid}" in text
    assert "Could not read the block state" in text


def test_the_guide_says_the_page_log_holds_no_email():
    """The privacy section names the new log, and the promise this file
    pins: the account number, never the email address."""
    guide = web.USER_GUIDE.read_text(encoding="utf-8")
    privacy = guide[guide.index("## Privacy: what the site keeps"):]

    assert "each page you open" in privacy
    assert "account number, not your email address" in privacy
