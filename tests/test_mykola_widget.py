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
    assert "showRecap(data)" in recap
    shown = _function(body, "showRecap")
    assert "data.notice" in shown, "a recap that can't be given must say so"


def test_no_recap_button_for_anonymous(client, app_module, monkeypatch):
    """Nothing of theirs is saved to look back on (#163)."""
    body = _widget(client, app_module, monkeypatch)
    assert 'id="mykola-recap"' not in body


def test_new_chat_no_recap_for_anonymous(client, app_module, monkeypatch):
    body = _widget(client, app_module, monkeypatch)
    new_chat = body.split("function newChat()")[1].split("\n            function ")[0]
    assert "requestRecap" not in new_chat, \
        "anonymous visitors have no recap, so New Chat must not call it"


def _function(body, name):
    return body.split("function %s(" % name)[1].split("\n            function ")[0]


def test_the_recap_button_goes_once_pressed(user_client, app_module, monkeypatch):
    """One recap per conversation: pressing hides the button (the user's
    report on #495 -- it stayed, inviting a second paid recap of the same
    chats). Hidden before the request, so a double press cannot send two, and
    saved with the thread so the next page does not bring it back."""
    body = _widget(user_client, app_module, monkeypatch)
    recap = _function(body, "requestRecap")
    before_fetch = recap.split("fetch(")[0]
    assert "recapAsked = true" in before_fetch
    assert "syncRecapButton()" in before_fetch
    assert "saveWidgetState()" in before_fetch
    sync = _function(body, "syncRecapButton")
    assert "tools.hidden = recapAsked" in sync

    save = _function(body, "saveWidgetState")
    assert "recapAsked: recapAsked" in save
    assert "recapAsked = !!state.recapAsked" in body
    restore = body.split("recapAsked = !!state.recapAsked")[1][:200]
    assert "syncRecapButton()" in restore


def test_a_failed_recap_brings_the_button_back(user_client, app_module, monkeypatch):
    """The request never got an answer, and Mykola says to try again -- so
    the button has to be there to try with."""
    body = _widget(user_client, app_module, monkeypatch)
    failed = _function(body, "requestRecap").split(".catch(")[1].split("}).then(")[0]
    assert "retry: true" in failed and "showRecap(" in failed
    # ...and the server's own failure says `retry` too (test_recap_streams.py),
    # so both reach the one place that turns it into the button coming back.
    shown = _function(body, "showRecap")
    assert "if (data.retry) recapAsked = false" in shown
    assert "syncRecapButton()" in shown


def test_a_new_conversation_brings_the_button_back(user_client, app_module,
                                                   monkeypatch):
    """New chat and the restart after a break both go through
    startFreshChat(), and a new conversation may have its own recap."""
    body = _widget(user_client, app_module, monkeypatch)
    fresh = _function(body, "startFreshChat")
    assert "recapAsked = false" in fresh
    assert "syncRecapButton()" in fresh
    assert "startFreshChat(" in _function(body, "newChat")


def test_the_hidden_recap_row_is_really_hidden():
    """.mykola-tools is display:flex, which beats the browser's own [hidden]
    rule -- without this the button stays on screen with hidden set."""
    import re
    from pathlib import Path
    css = (Path(chat.__file__).parent / "static" / "css" / "style.css").read_text(encoding="utf-8")
    assert re.search(r"\.mykola-tools\[hidden\]\s*\{\s*display:\s*none;", css)


def test_the_recap_is_typed_out_like_an_answer(user_client, app_module,
                                               monkeypatch):
    """The user's report on #495: the recap landed in one piece, the one
    message of Mykola's the typewriter never touched. It asks for a stream and
    hands it to the chat's own readReply(), with showRecap() as the finisher
    -- one typewriter, so the setting and reduced motion apply to both."""
    body = _widget(user_client, app_module, monkeypatch)
    recap = _function(body, "requestRecap")
    assert "stream: canStream" in recap
    assert 'type.indexOf("text/event-stream") === 0' in recap
    assert "readReply(resp, typing, showRecap)" in recap
    reply = _function(body, "readReply")
    assert "(finish || finishAnswer)(closing)" in reply, \
        "readReply() must hand the closing event to the recap's finisher"
