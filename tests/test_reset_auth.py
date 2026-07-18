"""Reset Auth (kuantorflow#98): clear the whole session, land on the gate.

The gate pass and the Google identity both live in the signed session
cookie; POST /auth/reset clears it entirely. Settings files must survive a
reset, and the button must stay enabled for anonymous gated visitors
despite the #102 read-only popup.
"""

import json


def test_reset_clears_gate_pass_and_identity(user_client):
    r = user_client.post("/auth/reset")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/enter")
    # the gate pass is gone — pages are gated again
    assert user_client.get("/").status_code == 302
    # and so is the Google identity
    with user_client.session_transaction() as sess:
        assert sess.get("user") is None
        assert sess.get("access_granted") is None


def test_reset_works_for_anonymous_gated_visitors(client):
    assert client.get("/").status_code == 200          # inside the gate
    r = client.post("/auth/reset")
    assert r.status_code == 302 and r.headers["Location"].endswith("/enter")
    assert client.get("/").status_code == 302          # gated again


def test_reset_rejects_get(client):
    assert client.get("/auth/reset").status_code == 405


def test_reset_preserves_the_settings_file(user_client, settings_dir):
    user_client.post("/settings", json={"translator": "bing"})
    user_client.post("/auth/reset")
    stored = json.loads(
        (settings_dir / "config-test.user.json").read_text(encoding="utf-8"))
    assert stored["translator"] == "bing", \
        "a reset must not delete preferences — signing back in restores them"


def test_reset_button_enabled_even_in_read_only_popup(client):
    """#102 freezes the settings controls for anonymous visitors; Reset Auth
    is an action, not a setting, and must stay clickable."""
    body = client.get("/").get_data(as_text=True)
    row = body.split('id="reset-auth-btn"')[1].split(">")[0]
    assert "disabled" not in row
    assert 'id="reset-auth-modal"' in body             # confirmation dialog
    assert "reset authentication" in body
    assert 'action="/auth/reset"' in body


def test_keyword_reentry_after_reset(client, keyword):
    """The full round-trip: reset, then the keyword opens the site again."""
    client.post("/auth/reset")
    r = client.post("/enter", data={"keyword": keyword})
    assert r.status_code == 302
    assert client.get("/").status_code == 200
