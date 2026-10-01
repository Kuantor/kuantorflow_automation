"""Restart Mykola's chat: the number box, and a restart that really happens
(kuantorflow#463, #464).

**#463, the control.** The 24-stop slider became a 1-24 number box with
steppers, half width beside *Fill the gap round*'s box -- the other number a
learner already has in mind -- where the popup had an empty column. The speed
slider stays a slider (it is chosen by ear). A typed value outside a box's
range is pulled into it on change and again before saving: `sanitize()` does
not clamp, it falls back to the default, so 25 hours used to save as 2. Both
number boxes, the same exposure.

**#464, the behaviour,** checked in a real page (the PR records it): a planted
conversation 3 h old restarted, 10 min old did not, an immediate reload did not
restart twice. And one real bug: `restoreState()` read the saved timestamp back
*after* `setMinimized()` and the restored scroll position had already saved the
widget state with it still null -- so every page load wiped it, and an
anonymous visitor's chat never restarted after a single navigation. A used
recap button came back the same way (`recapAsked`). The browser half cannot run
here; what can fail here is the order that broke it.
"""

import re

import settings_store


def _body(client):
    return client.get("/").get_data(as_text=True)


def _fieldset(body, legend):
    for block in re.findall(r"<fieldset[^>]*>.*?</fieldset>", body, re.S):
        if legend in block:
            return block
    raise AssertionError(f"no fieldset for {legend!r}")


def test_the_restart_box_sits_beside_fill_the_gaps():
    """Half width, and straight after it in the grid, so the two pair up."""
    body = None
    import app as app_module
    with app_module.app.test_client() as client:
        body = _body(client)
    fill = body.index("<legend>Fill the gap round</legend>")
    restart = body.index("<legend>Restart Mykola&rsquo;s chat after a break</legend>")
    speech = body.index("<legend>How fast words are spoken</legend>")
    assert fill < restart < speech, "the restart group is not right after Fill the gap's"
    block = _fieldset(body, "Restart Mykola")
    assert 'class="settings-group"' in block and "settings-group--wide" not in block


def test_it_is_a_number_box_in_the_fill_the_gap_style(client):
    block = _fieldset(_body(client), "Restart Mykola")
    assert '<label class="settings-number">' in block
    assert re.search(r'<input type="number" name="restart_chat_interval"[^>]*min="1"[^>]*max="24"', block)
    assert 'type="range"' not in block and "<output" not in block
    assert 'aria-describedby="restart-interval-hint"' in block and 'id="restart-interval-hint"' in block


def test_the_speed_of_speech_is_still_a_slider(client):
    block = _fieldset(_body(client), "How fast words are spoken")
    assert 'type="range"' in block and "settings-slider-row" in block


def test_the_hint_no_longer_promises_a_recap(client):
    """#495 took the automatic recap out of the restart."""
    block = _fieldset(_body(client), "Restart Mykola")
    text = " ".join(re.sub(r"<[^>]+>", " ", block).split())
    assert "Between 1 and 24" in text and "fresh conversation" in text
    assert "reviews" not in text and "recap" not in text.lower()


def test_both_number_boxes_clamp_on_change_and_before_saving(client):
    body = _body(client)
    clamp = body[body.index("function clampNumberBox(box)"):]
    clamp = clamp[:clamp.index("\n            }")]
    assert "Math.min(high, Math.max(low, value))" in clamp
    assert "[restartBox, settingsForm.gapped_deck_size].forEach" in body
    # The save handler clamps just before it decides what changed.
    save = body[:body.index("var APPLIED_WITHOUT_A_RELOAD")][-400:]
    assert "clampNumberBox(restartBox);" in save
    assert "clampNumberBox(settingsForm.gapped_deck_size);" in save


def test_out_of_range_on_the_server_still_falls_back_to_the_default():
    """Why the client clamps: the store does not, and would quietly save 2."""
    clean = settings_store.sanitize({"restart_chat_interval": 25})
    assert clean["restart_chat_interval"] == settings_store.DEFAULTS["restart_chat_interval"]


def test_never_still_posts_zero(client):
    body = _body(client)
    assert re.search(r"restart_chat_interval: restartNever\.checked\s*\?\s*0 : Number\(restartBox\.value\)", body)


def test_the_saved_timestamp_is_read_before_anything_can_save(client, app_module,
                                                              monkeypatch):
    """The #464 bug. Inside restoreState(), lastMessageAt and recapAsked must
    be taken from the saved state before the first call that saves it --
    setMinimized() and the restored scroll position -- or that save writes
    them back as null and false."""
    monkeypatch.setattr("chat.MYKOLA_AVAILABLE", True)   # the widget's script
    body = _body(client)
    restore = body[body.index("(function restoreState() {"):]
    restore = restore[:restore.index("})();")]
    read_stamp = restore.index("lastMessageAt = state.lastMessageAt")
    read_recap = restore.index("recapAsked = !!state.recapAsked")
    # The calls, not their names: a comment above the reads mentions both.
    first_save = min(restore.index("setMinimized(!!state"),
                     restore.index("messages.scrollTop = state.scrollTop"))
    assert read_stamp < first_save and read_recap < first_save, \
        "the saved state is read back after it has already been overwritten"
