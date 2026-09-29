import chat
"""Mykola chat widget markup — the 'New Chat' button (ai_agent#55).

The widget only renders when Mykola is available, so these force
MYKOLA_AVAILABLE. The button's reset is client-side JS (not exercised by the
test client); here we lock in that the button and its wiring are present, and
that the recap happens only when a signed-in learner presses its button
(kuantorflow#495) -- never by itself on opening the chat or on New Chat.
"""


def _widget(resp_client, app_module, monkeypatch):
    monkeypatch.setattr("chat.MYKOLA_AVAILABLE", True)
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


def test_new_chat_does_not_recap_by_itself(user_client, app_module, monkeypatch):
    """kuantorflow#495: New Chat used to re-run the recap -- a paid model call
    nobody asked for. The button is there for a learner who wants one."""
    body = _widget(user_client, app_module, monkeypatch)
    new_chat = body.split("function newChat()")[1].split("\n            function ")[0]
    assert "requestRecap" not in new_chat


def test_opening_the_chat_asks_only_for_the_farewell(user_client, app_module,
                                                    monkeypatch):
    """Opening the chat was the recap. Now it asks once for the free farewell,
    without `requested`, which the server answers without the model."""
    body = _widget(user_client, app_module, monkeypatch)
    open_panel = body.split("function openPanel()")[1].split("\n            function ")[0]
    assert "checkFarewell()" in open_panel
    assert "requestRecap" not in open_panel
    farewell = body.split("function checkFarewell()")[1].split("\n            function ")[0]
    assert "requested" not in farewell


def test_the_recap_button_is_what_asks_for_a_recap(user_client, app_module,
                                                  monkeypatch):
    body = _widget(user_client, app_module, monkeypatch)

    assert '<button type="button" id="mykola-recap"' in body
    assert "Recap our last chats" in body
    assert 'recapButton.addEventListener("click", requestRecap)' in body
    recap = body.split("function requestRecap()")[1].split("\n            function ")[0]
    assert "requested: true" in recap
    assert "data.notice" in recap, "a recap that can't be given must say so"


def test_no_recap_button_for_anonymous(client, app_module, monkeypatch):
    """Nothing of theirs is saved to look back on (#163)."""
    body = _widget(client, app_module, monkeypatch)
    assert 'id="mykola-recap"' not in body


def test_new_chat_no_recap_for_anonymous(client, app_module, monkeypatch):
    body = _widget(client, app_module, monkeypatch)
    new_chat = body.split("function newChat()")[1].split("\n            function ")[0]
    assert "requestRecap" not in new_chat, \
        "anonymous visitors have no recap, so New Chat must not call it"
