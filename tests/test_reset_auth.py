"""Reset Auth (kuantorflow#98), after the gate came off (#199).

It used to forget **two** things — the keyword gate's pass and the Google
identity — and land on the gate. Since #199 there is no keyword, so what is
left is the identity, plus the part that makes it a different control from
`/logout` rather than a second spelling of it: the popup's JavaScript clears
this browser's own storage first, and that is where Mykola's conversation
lives (`localStorage`, keyed on `_identity_token()`, #170).

So the one-sentence summary changed from "hand the site back" to **"hand the
browser back"**, and that is the thing these tests are about. Signing out
leaves the thread; resetting does not.

Settings files must still survive a reset — that has not changed and is the
reason a reset is not the same as deleting an account.
"""

import json


def test_reset_clears_the_identity(user_client):
    r = user_client.post("/auth/reset")

    assert r.status_code == 302
    assert r.headers["Location"].endswith("/")
    with user_client.session_transaction() as sess:
        assert sess.get("user") is None


def test_reset_clears_the_whole_session_not_just_the_user(user_client):
    """`session.clear()` rather than `session.pop("user")`, which is what
    `/logout` does. Anything else the session accumulates -- the anonymous
    message count, the remembered game selection, #237's held text -- goes
    too, because the point is a browser handed to somebody else.
    """
    with user_client.session_transaction() as sess:
        sess["anon_messages"] = 4
        sess["a_left_over_key"] = "still here"

    user_client.post("/auth/reset")

    with user_client.session_transaction() as sess:
        assert dict(sess) == {}, f"left behind: {dict(sess)}"


def test_the_site_still_answers_after_a_reset(user_client):
    """The assertion this file used to make in reverse. It checked that the
    pages were *gated again*; the same request now has to keep working, since
    a reset returns the visitor to being anonymous rather than shut out."""
    user_client.post("/auth/reset")

    assert user_client.get("/").status_code == 200


def test_reset_works_for_an_anonymous_visitor(client):
    """#102 freezes the settings controls for an anonymous visitor; Reset Auth
    is an action rather than a setting, so it stays available -- and it still
    has something to do, because the browser storage it clears is there
    whether or not anybody signed in."""
    r = client.post("/auth/reset")

    assert r.status_code == 302 and r.headers["Location"].endswith("/")
    assert client.get("/").status_code == 200


def test_reset_rejects_get(client):
    assert client.get("/auth/reset").status_code == 405


def test_reset_preserves_the_settings_file(user_client, settings_dir):
    user_client.post("/settings", json={"translator": "microsoft"})
    user_client.post("/auth/reset")
    stored = json.loads(
        (settings_dir / "config-7.json").read_text(encoding="utf-8"))
    assert stored["translator"] == "microsoft", \
        "a reset must not delete preferences — signing back in restores them"


def test_reset_button_enabled_even_in_read_only_popup(client):
    """#102 freezes the settings controls for anonymous visitors; Reset Auth
    is an action, not a setting, and must stay clickable."""
    body = client.get("/").get_data(as_text=True)
    row = body.split('id="reset-auth-btn"')[1].split(">")[0]
    assert "disabled" not in row
    assert 'id="reset-auth-modal"' in body             # confirmation dialog
    assert 'action="/auth/reset"' in body


def test_the_confirmation_no_longer_promises_a_keyword(client):
    """The wording is the part a learner sees, and it said the site would ask
    for the keyword again. With no keyword that sentence is simply false --
    and a confirmation dialog that describes something that will not happen is
    worse than a vague one, because it is the last thing read before an
    irreversible-looking button."""
    body = client.get("/").get_data(as_text=True)
    dialog = body.split('id="reset-auth-modal"')[1].split("</div>")[0]

    assert "keyword" not in dialog.lower()
    assert "signed out" in dialog.lower()


def test_the_button_title_no_longer_promises_a_keyword(client):
    """Same sentence, in the tooltip, which is the other place it was
    written."""
    body = client.get("/").get_data(as_text=True)
    at = body.index('id="reset-auth-btn"')
    tag = body[body.rindex("<button", 0, at):body.index(">", at)]

    assert "keyword" not in tag.lower()
