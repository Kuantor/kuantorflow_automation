"""The admin mailer (kuantorflow#591): `notify.send_admin_email()`.

The one piece the three admin notices share -- a new account (#592), the daily
report (#593) and the near-the-limit warning (#594). What it must guarantee:

* configured from `.env` at call time, and **off when it is not configured**:
  nothing sent, nothing raised, one `skipped` line naming what is missing;
* **never raises and never blocks for long**: a refused login, a timeout or a
  bad port costs a `failed` line, and the caller carries on;
* **`NOTIFY_DRY_RUN=1` sends nothing** and logs what it would have sent;
* one `NOTIFY` line per attempt, in `notify.log` and nowhere else, that
  **never contains the body** -- and never the password, even when the
  server's error message happens to repeat it.

`smtplib` is replaced by a recording fake; `conftest.no_admin_mail` clears the
settings for every other test, so the suite can never send a real email.
"""

import re
import socket
import smtplib
import sys
from pathlib import Path

import pytest

from conftest import KUANTORFLOW_PATH

import notify

LF = chr(10)
PASSWORD = "abcd efgh ijkl mnop"
BODY = "Account #13 signed in." + LF + "Secret body line that must not be logged."


class _Server:
    """A fake SMTP connection that records what was done with it."""

    instances = []
    fail_on = None          # "connect", "login" or "send"
    error = None

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.ssl = context is not None
        self.calls, self.messages = [], []
        _Server.instances.append(self)
        if _Server.fail_on == "connect":
            raise _Server.error

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user, password))
        if _Server.fail_on == "login":
            raise _Server.error

    def send_message(self, msg):
        self.calls.append("send")
        if _Server.fail_on == "send":
            raise _Server.error
        self.messages.append(msg)

    def quit(self):
        self.calls.append("quit")

    def close(self):
        self.calls.append("close")


@pytest.fixture()
def smtp(monkeypatch):
    """`smtplib.SMTP` and `SMTP_SSL` replaced by the recording fake."""
    _Server.instances, _Server.fail_on, _Server.error = [], None, None
    monkeypatch.setattr(smtplib, "SMTP", _Server)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _Server)
    return _Server


@pytest.fixture()
def configured(monkeypatch):
    """A configured mailer, as on PythonAnywhere."""
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_USER", "sender@example.test")
    monkeypatch.setenv("SMTP_PASSWORD", PASSWORD)
    monkeypatch.setenv("NOTIFY_EMAIL", "admin@example.test")


def _lines(action_logs):
    path = action_logs / "notify.log"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _fields(line):
    return dict(re.findall(r"(\w+)=('(?:[^'\\]|\\.)*'|\S+)", line))


def _sent(smtp):
    return [m for server in smtp.instances for m in server.messages]


# --- sending ----------------------------------------------------------------

def test_a_configured_mailer_sends_one_message(smtp, configured, action_logs):
    result = notify.send_admin_email("test", "KuantorFlow: hello", BODY)

    assert result == "sent"
    (msg,) = _sent(smtp)
    assert msg["To"] == "admin@example.test"
    assert msg["Subject"] == "KuantorFlow: hello"
    assert "sender@example.test" in msg["From"]
    assert msg.get_content().startswith(BODY)


def test_it_logs_in_over_starttls_on_587(smtp, configured):
    notify.send_admin_email("test", "s", BODY)

    (server,) = smtp.instances
    assert (server.host, server.port) == ("smtp.example.test", 587)
    assert server.calls[:2] == ["starttls", ("login", "sender@example.test", PASSWORD)]
    assert server.calls[-1] == "quit"


def test_port_465_is_ssl_from_the_start(smtp, configured, monkeypatch):
    monkeypatch.setenv("SMTP_PORT", "465")

    assert notify.send_admin_email("test", "s", BODY) == "sent"
    (server,) = smtp.instances
    assert server.port == 465 and server.ssl
    assert "starttls" not in server.calls


def test_the_timeout_is_short(smtp, configured):
    """A notice is sent inside a request; a hung server must not hang it."""
    notify.send_admin_email("test", "s", BODY)

    (server,) = smtp.instances
    assert server.timeout and server.timeout <= 10


def test_the_recipient_defaults_to_the_first_admin(smtp, configured, monkeypatch):
    monkeypatch.delenv("NOTIFY_EMAIL")
    monkeypatch.setenv("ADMIN_EMAILS", " first@example.test , second@example.test")

    notify.send_admin_email("test", "s", BODY)

    assert [m["To"] for m in _sent(smtp)] == ["first@example.test"]


def test_a_line_break_in_the_subject_cannot_add_a_header(smtp, configured):
    result = notify.send_admin_email("test", "one" + LF + "Bcc: x@example.test", BODY)

    assert result == "sent"
    (msg,) = _sent(smtp)
    assert msg["Bcc"] is None
    assert LF not in msg["Subject"]


def test_a_sent_email_is_logged(smtp, configured, action_logs):
    notify.send_admin_email("test", "KuantorFlow: hello", BODY)

    (line,) = _lines(action_logs)
    fields = _fields(line)
    assert " NOTIFY " in line
    assert fields["kind"] == "test" and fields["result"] == "sent"
    assert fields["subject"] == "'KuantorFlow: hello'"


# --- off --------------------------------------------------------------------

@pytest.mark.parametrize("missing", ["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD",
                                     "NOTIFY_EMAIL"])
def test_unconfigured_sends_nothing_and_says_what_is_missing(
        smtp, configured, monkeypatch, action_logs, missing):
    monkeypatch.delenv(missing)
    monkeypatch.delenv("ADMIN_EMAILS", raising=False)

    assert notify.send_admin_email("test", "s", BODY) == "skipped"
    assert smtp.instances == []
    (line,) = _lines(action_logs)
    fields = _fields(line)
    assert fields["result"] == "skipped"
    assert missing in fields["missing"]


def test_an_empty_environment_is_off_not_an_error(smtp, action_logs):
    """Local development: no mail server, and nothing breaks."""
    assert notify.send_admin_email("test", "s", BODY) == "skipped"
    assert smtp.instances == []


def test_settings_are_read_at_call_time(smtp, monkeypatch, configured):
    """So a reloaded `.env` takes effect, and a test's settings are seen."""
    assert notify.send_admin_email("test", "s", BODY) == "sent"
    monkeypatch.delenv("SMTP_HOST")
    assert notify.send_admin_email("test", "s", BODY) == "skipped"


# --- failures ---------------------------------------------------------------

@pytest.mark.parametrize("fail_on,error", [
    ("connect", socket.timeout("timed out")),
    ("connect", ConnectionRefusedError("refused")),
    ("login", smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted")),
    ("send", smtplib.SMTPRecipientsRefused({})),
    ("send", RuntimeError("anything at all")),
])
def test_a_failure_never_raises_and_is_logged(smtp, configured, action_logs,
                                              fail_on, error):
    smtp.fail_on, smtp.error = fail_on, error

    assert notify.send_admin_email("test", "s", BODY) == "failed"
    (line,) = _lines(action_logs)
    fields = _fields(line)
    assert fields["result"] == "failed"
    assert type(error).__name__ in fields["error"]


def test_a_failed_connection_is_still_closed(smtp, configured):
    smtp.fail_on, smtp.error = "login", smtplib.SMTPAuthenticationError(535, b"no")

    notify.send_admin_email("test", "s", BODY)

    (server,) = smtp.instances
    assert "quit" in server.calls or "close" in server.calls


def test_a_bad_port_is_a_failure_not_a_crash(smtp, configured, monkeypatch, action_logs):
    monkeypatch.setenv("SMTP_PORT", "five-eight-seven")

    assert notify.send_admin_email("test", "s", BODY) == "failed"
    assert smtp.instances == []
    assert _fields(_lines(action_logs)[0])["result"] == "failed"


def test_the_password_never_reaches_the_log(smtp, configured, action_logs):
    """Even when the server's error message repeats it."""
    smtp.fail_on = "login"
    smtp.error = smtplib.SMTPAuthenticationError(535, ("bad password " + PASSWORD).encode())

    notify.send_admin_email("test", "s", BODY)

    text = (action_logs / "notify.log").read_text(encoding="utf-8")
    assert "Authentication" in text
    assert PASSWORD not in text and "abcd" not in text


def test_a_long_error_is_cut_short(smtp, configured, action_logs):
    smtp.fail_on, smtp.error = "send", RuntimeError("x" * 2000)

    notify.send_admin_email("test", "s", BODY)

    assert len(_lines(action_logs)[0]) < 500


# --- dry run ----------------------------------------------------------------

def test_a_dry_run_sends_nothing_and_logs(smtp, configured, monkeypatch, action_logs):
    monkeypatch.setenv("NOTIFY_DRY_RUN", "1")

    assert notify.send_admin_email("test", "KuantorFlow: hello", BODY) == "dry-run"
    assert smtp.instances == []
    fields = _fields(_lines(action_logs)[0])
    assert fields["result"] == "dry-run"
    assert fields["subject"] == "'KuantorFlow: hello'"
    assert int(fields["chars"]) == len(BODY)


def test_a_dry_run_works_with_no_mail_server(smtp, monkeypatch, action_logs):
    """It is meant for local development, where nothing is configured."""
    monkeypatch.setenv("NOTIFY_DRY_RUN", "1")

    assert notify.send_admin_email("test", "s", BODY) == "dry-run"
    assert smtp.instances == []


@pytest.mark.parametrize("value", ["0", "", "no", "off"])
def test_a_dry_run_switched_off_sends(smtp, configured, monkeypatch, value):
    monkeypatch.setenv("NOTIFY_DRY_RUN", value)

    assert notify.send_admin_email("test", "s", BODY) == "sent"


# --- the log ----------------------------------------------------------------

@pytest.mark.parametrize("mode", ["sent", "failed", "dry-run", "skipped"])
def test_the_body_is_never_logged(smtp, configured, monkeypatch, action_logs, mode):
    if mode == "failed":
        smtp.fail_on, smtp.error = "send", RuntimeError("boom")
    elif mode == "dry-run":
        monkeypatch.setenv("NOTIFY_DRY_RUN", "1")
    elif mode == "skipped":
        monkeypatch.delenv("SMTP_HOST")

    assert notify.send_admin_email("test", "s", BODY) == mode
    text = (action_logs / "notify.log").read_text(encoding="utf-8")
    assert "Secret body line" not in text and "#13" not in text


def test_notify_lines_go_to_their_own_log(smtp, configured, action_logs):
    notify.send_admin_email("test", "s", BODY)

    assert [p.name for p in action_logs.iterdir()] == ["notify.log"]


# --- the test script and the example settings -------------------------------

def test_the_test_script_sends_through_the_mailer(monkeypatch, capsys):
    sys.path.insert(0, str(Path(KUANTORFLOW_PATH) / "scripts"))
    import send_test_email

    calls = []
    monkeypatch.setattr(notify, "send_admin_email",
                        lambda kind, subject, body: calls.append((kind, subject)) or "sent")

    assert send_test_email.main([]) == 0
    assert calls and calls[0][0] == notify.KIND_TEST
    assert "sent" in capsys.readouterr().out.lower()


@pytest.mark.parametrize("result", ["failed", "skipped", "dry-run"])
def test_the_test_script_fails_unless_sent(monkeypatch, capsys, result):
    sys.path.insert(0, str(Path(KUANTORFLOW_PATH) / "scripts"))
    import send_test_email

    monkeypatch.setattr(notify, "send_admin_email", lambda *a: result)

    assert send_test_email.main([]) == 1
    assert "notify.log" in capsys.readouterr().out


def test_env_example_has_empty_slots_for_every_setting():
    example = (Path(KUANTORFLOW_PATH) / ".env.example").read_text(encoding="utf-8")
    for name in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD",
                 "NOTIFY_EMAIL", "NOTIFY_DRY_RUN"):
        found = re.search(r"^#? ?" + name + r"=(.*)$", example, re.M)
        assert found, name
    assert re.search(r"^SMTP_PASSWORD=$", example, re.M), "no password in the example"
