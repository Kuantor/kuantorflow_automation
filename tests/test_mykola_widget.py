"""Mykola chat widget markup — the 'New Chat' button (ai_agent#55).

The widget only renders when Mykola is available, so these force
MYKOLA_AVAILABLE. The button's reset is client-side JS (not exercised by the
test client); here we lock in that the button and its wiring are present, and
that the welcome-back recap is re-run only for signed-in visitors.
"""


def _widget(resp_client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    return resp_client.get("/").get_data(as_text=True)


def test_new_chat_button_and_confirm_dialog(client, app_module, monkeypatch):
    body = _widget(client, app_module, monkeypatch)
    assert 'class="mykola-new"' in body                 # the pencil button
    assert 'aria-label="New chat"' in body
    assert 'title="New chat' in body
    # the pencil opens a confirmation dialog (ai_agent#55) rather than
    # resetting immediately
    assert 'id="new-chat-modal"' in body
    assert "Do you really want to start a new conversation?" in body
    assert 'id="new-chat-yes"' in body and 'id="new-chat-no"' in body
    assert "newChatModal.hidden = false" in body        # pencil -> open confirm
    assert "function newChat()" in body                 # the reset handler
    assert "newChat();" in body                          # invoked from the Yes button


def test_new_chat_reruns_recap_for_signed_in(user_client, app_module, monkeypatch):
    body = _widget(user_client, app_module, monkeypatch)
    new_chat = body.split("function newChat()")[1].split("\n            function ")[0]
    assert "requestRecap();" in new_chat, \
        "signed-in New Chat must re-run Mykola's welcome-back recap"


def test_new_chat_no_recap_for_anonymous(client, app_module, monkeypatch):
    body = _widget(client, app_module, monkeypatch)
    new_chat = body.split("function newChat()")[1].split("\n            function ")[0]
    assert "requestRecap" not in new_chat, \
        "anonymous visitors have no recap, so New Chat must not call it"
