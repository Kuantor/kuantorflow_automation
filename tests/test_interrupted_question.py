"""A question asked, and the page left before the answer (kuantorflow#304).

Ask Mykola something and click a link — any link, to any page — before the
answer arrives, and until now two things were lost at once:

* **the answer**, because `/mykola/chat/stream` is read with `fetch` in that
  page's JavaScript and the navigation tears the context down mid-stream;
* **the question**, in the sense that matters. It stayed *on screen*, because
  `addMessage("user", …)` persists immediately — which is why this looked like
  a display bug — but `history`, the conversation the model is shown, is only
  ever assigned from a reply. No reply, no entry. The transcript and Mykola's
  view of it had silently diverged, and every later turn was answered as
  though the question had never been asked.

The widget now remembers the question it is waiting on, and the next page
asks it again. Re-asking rather than resuming is the point: the original
request died with the page that made it and there is nothing to reattach to.
The server's reply then carries the whole history back, which is what puts the
turn into the conversation — so nothing here appends to `history` by hand,
where a client-built entry could leave two user turns in a row.

These are assertions about the widget's script, which is where all of this
lives. The behaviour itself was driven in a browser: asked, navigated to a
topic page at 250ms, and the answer arrived there; asked again, navigated to
the card deck, and the follow-up arrived there and read as a follow-up.
"""

import pytest


@pytest.fixture()
def widget(client, app_module, monkeypatch):
    """Mykola's widget script alone, from a page that renders it.

    Sliced out rather than searched for in the page, because the index page
    has **two** `form.addEventListener("submit", …)` handlers of its own — the
    review popup's and the one that disables a button while a lookup runs —
    and both come before the widget in the rendered HTML. A search over the
    whole page silently reads one of those instead.
    """
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    body = client.get("/").get_data(as_text=True)
    start = body.index('document.getElementById("mykola-messages")')
    return body[start:body.index("js/speech.js", start)]


def _fn(widget_src, name):
    """One function's body from the widget's script."""
    start = widget_src.index(f"function {name}(")
    return widget_src[start:widget_src.index("\n            }", start)]


# --- the question is written down before it can be lost -----------------


def test_the_pending_question_is_part_of_the_saved_state(widget):
    """The request cannot survive the navigation; this is what does. Without it
    the next page has no way to know an answer is owed."""
    assert "pending: pending," in _fn(widget, "saveWidgetState")


def test_it_is_recorded_before_the_message_is_added(widget):
    """Order is the whole point: between marking the question pending and the
    save that `addMessage()` performs is exactly the window a click on a link
    falls into. Recorded after, a fast click would still lose it."""
    submit = widget[widget.index('form.addEventListener("submit"'):]
    submit = submit[:submit.index("});")]
    assert submit.index("pending = question") < submit.index('addMessage("user"')


# --- and cleared wherever a turn ends ------------------------------------


def test_an_answer_clears_it(widget):
    """`finishAnswer()` is the one place both delivery paths end up, streamed
    or whole, so clearing it there covers both."""
    assert "pending = null" in _fn(widget, "finishAnswer")


def test_an_error_clears_it(widget):
    """A refusal or a failure is an end to the turn too. Left set, the question
    would re-ask itself on every page load for the rest of the session —
    worse than the bug being fixed."""
    assert "pending = null" in _fn(widget, "showChatError")


def test_a_cut_stream_that_delivered_something_clears_it(widget):
    """Half an answer is still an answer to this question. The partial-reply
    branch keeps the words rather than blanking them (ai_agent#50), and the
    turn is over."""
    cut = widget[widget.index("The connection ended without a closing event"):]
    # To the end of the branch, not to the first `return;` — the guard that
    # steps aside when a closing event already arrived is one of those.
    cut = cut[:cut.index("buffer += decoder.decode")]
    assert "pending = null" in cut
    assert cut.index("pending = null") < cut.index('addMessage("mykola", shown')


def test_a_network_failure_clears_it(widget):
    """The `catch` around the request, which is not `showChatError`'s path."""
    ask = _fn(widget, "ask")
    assert "pending = null" in ask
    assert ask.index("catch(") < ask.index("pending = null")


# --- what the next page does with it -------------------------------------


def test_a_restored_pending_question_is_asked_again(widget):
    """On any page, after any navigation — the state is restored the same way
    everywhere, so this needs nothing per page."""
    restore = widget[widget.index("function restoreState()"):]
    restore = restore[:restore.index("})();")]
    assert "state.pending" in restore
    assert "resumePending(state.pending)" in restore


def test_resuming_wins_over_restarting_a_stale_chat(widget):
    """Both can be true at once — ask something, wander off for hours, come
    back. Restarting first wipes the thread and the unanswered question with
    it, and the recap loses nothing by waiting for the next load."""
    restore = widget[widget.index("function restoreState()"):]
    restore = restore[:restore.index("})();")]
    assert restore.index("resumePending(state.pending)") < \
        restore.index("maybeRestartChat()")
    assert "} else if (hasConversation())" in restore, \
        "the two must be exclusive, not both"


def test_the_question_is_put_back_if_it_is_not_on_screen(widget):
    """Normally it was saved when it was sent. If that write failed, the
    alternative is an answer to a question nobody can see."""
    resume = _fn(widget, "resumePending")
    assert 'last.kind !== "user"' in resume
    assert 'addMessage("user", question)' in resume


def test_resuming_does_not_steal_the_focus(widget):
    """Sending is the learner's action and earns the caret back; a page load
    finishing an old request is not, and a phone would open its keyboard."""
    assert "ask(question, false)" in _fn(widget, "resumePending")
    submit = widget[widget.index('form.addEventListener("submit"'):]
    assert "ask(question, true)" in submit[:submit.index("});")]


def test_the_retry_carries_the_same_conversation(widget):
    """Same chat id, same history — a re-ask that started a new thread would
    answer the question out of context and split the log in two."""
    ask = _fn(widget, "ask")
    assert "history: history" in ask and "chat_id: chatId" in ask


def test_both_delivery_paths_go_through_the_one_asker(widget):
    """`askStreaming()` falls back to `askWhole()` itself, so the non-streaming
    server gets the same treatment without a second copy of any of this."""
    assert "askStreaming(body, typing)" in _fn(widget, "ask")
    # One call site, not two: the definition also matches the plain name, so
    # the call is counted by what follows it.
    assert widget.count("askStreaming(body, typing).catch(") == 1
