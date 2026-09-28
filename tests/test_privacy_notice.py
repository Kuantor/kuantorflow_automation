"""The privacy notice: reachable from every page, and true (kuantorflow#90, #56).

The notice is `## Privacy: what the site keeps` in the user guide, so /help
shows it and Mykola answers from it. A notice that states facts about the code
is only worth having while those facts hold, so what can be derived from the
code is checked against it here rather than restated:

* how long the activity logs are kept -- `applog.ROTATE_DAYS` and
  `KEEP_ROTATIONS`, not a number typed into this file;
* that an anonymous conversation with Mykola is never written to the server;
* that the links on every page land on the section, whatever the Markdown
  renderer names its anchor.

The rest of the notice is prose about who reads what, and is reviewed as prose.
"""

import re
from pathlib import Path

import pytest

import applog


def _guide():
    import web
    return Path(web.USER_GUIDE).read_text(encoding="utf-8")


def _privacy_section():
    guide = _guide()
    start = guide.index("## Privacy: what the site keeps")
    end = guide.index("\n## ", start + 3)
    return guide[start:end]


def _anchors(client):
    return set(re.findall(r'id="([^"]+)"', client.get("/help").get_data(as_text=True)))


# --- reachable ----------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/", "/help", "/quiz", "/games/spell_it"])
def test_every_page_links_to_the_notice_in_its_footer(client, path):
    """#90 asked for a small notice on the site. The footer is on every page,
    and the link must land on a heading that exists -- read from /help, so a
    renamed heading fails here instead of leaving a link to nowhere."""
    body = client.get(path).get_data(as_text=True)
    footer = body[body.index('<footer class="site-footer">'):body.index("</footer>")]
    link = re.search(r'class="site-footer-privacy" href="/help#([^"]+)"', footer)

    assert link, f"no Privacy link in the footer of {path}"
    assert link.group(1) in _anchors(client)


def test_the_sign_in_offer_links_to_the_notice(client, monkeypatch):
    """Mykola's sign-in popup is where a visitor decides whether their chats
    are kept, so the notice is one click from that decision. The popup only
    renders when Mykola and Google sign-in are both available, as they are in
    production; the test turns both on."""
    monkeypatch.setattr("web.GOOGLE_AUTH_AVAILABLE", True)
    monkeypatch.setattr("chat.MYKOLA_AVAILABLE", True)
    body = client.get("/").get_data(as_text=True)
    assert "mykola-consent-note" in body, "the popup did not render at all"
    link = re.search(r'href="/help#([^"]+)">What the site keeps</a>', body)

    assert link and link.group(1) in _anchors(client)


def test_the_notice_is_on_the_help_page(client):
    body = client.get("/help").get_data(as_text=True)

    for heading in re.findall(r"^### (.+)$", _privacy_section(), re.M):
        assert heading in body, heading


# --- true -----------------------------------------------------------------------------

def test_the_stated_log_rotation_is_the_real_one():
    """The notice says the logs are started afresh every N days. N comes from
    applog, so changing the rotation without changing the notice fails here."""
    assert f"every {applog.ROTATE_DAYS} days" in _privacy_section()


def test_about_a_year_is_what_the_rotation_actually_keeps():
    """"Deleted automatically after about a year": the live file plus
    KEEP_ROTATIONS old ones, each ROTATE_DAYS long. If that stops being about
    a year, the sentence is wrong."""
    kept_days = applog.ROTATE_DAYS * (applog.KEEP_ROTATIONS + 1)

    assert "after about a year" in _privacy_section()
    assert 330 <= kept_days <= 400, kept_days


def test_an_anonymous_conversation_is_never_written(app_module):
    """The notice promises that nothing an anonymous visitor says to Mykola
    is saved on the server. `_chat_log_path()` is where a conversation's file
    is chosen, and for a visitor with no account it must choose none."""
    import chat

    with app_module.app.test_request_context("/"):
        assert chat._chat_log_path("any-chat-id") is None

    assert "nothing you say to Mykola is saved on the server" in _privacy_section()


def test_a_signed_in_conversation_is_saved_under_the_account(app_module):
    """The other half of the promise, stated just as plainly: signed in, the
    conversation is kept, under the account, which is what deletion removes."""
    import chat
    import web

    with app_module.app.test_request_context("/"):
        from flask import session
        session["user"] = {"id": 7, "email": "t@example.com", "name": "T"}
        path = chat._chat_log_path("some-chat")

    assert path is not None and path.parent == web.LOG_DIR / "7"
    assert "saved on the server under your account" in _privacy_section()


def test_deleting_the_account_removes_what_the_notice_says(app_module, monkeypatch,
                                                          tmp_path):
    """The notice lists saved conversations and settings among what Delete
    account removes. Checked against the real `delete_account()`, with the
    database calls stubbed and the files in a temporary directory."""
    import app as app_mod
    import settings_store
    import utils
    import web

    monkeypatch.setattr(web, "LOG_DIR", tmp_path / "mykola_logs")
    chats = tmp_path / "mykola_logs" / "7"
    chats.mkdir(parents=True)
    (chats / "chat_x.txt").write_text("User: hello", encoding="utf-8")
    settings_file = settings_store.config_path(7)
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(utils, "resolve_user_cards", lambda uid, keep: 0)
    monkeypatch.setattr(utils, "delete_user", lambda uid: True)

    app_mod.delete_account(7)

    assert not chats.exists()
    assert not settings_file.exists()
    section = _privacy_section()
    assert "your saved conversations with Mykola" in section
    assert "your settings" in section


def test_the_notice_admits_what_deletion_does_not_remove():
    """The activity logs are not rewritten on deletion. A notice that left
    that out would be the one false thing in it."""
    assert "The activity logs are not rewritten" in _privacy_section()
