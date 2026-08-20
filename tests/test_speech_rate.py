"""How fast a word is spoken (kuantorflow#268).

**The audio is not tested here and cannot be** — the suite cannot hear
anything. What is testable is everything either side: the setting sanitises and
clamps like every other range setting, the popup renders a control for it, and
the value reaches the document where `speech.js` can read it.

Whether the browser actually speaks at that speed was checked by hand, and the
utterance's `rate` was captured in a real browser rather than assumed: 70 gives
0.7, 50 gives 0.5, 150 gives 1.5, and a missing or unparseable value gives 1.
That is recorded on the PR; none of it can live here.
"""

import re

import settings_store


# --- the setting ----------------------------------------------------------


def test_it_has_a_default_and_a_range():
    assert settings_store.DEFAULTS["speech_rate"] == 100
    assert settings_store.RANGES["speech_rate"] == (50, 150)


def test_it_is_a_whole_number():
    """A percentage rather than the natural 0.5–1.5 float, because `RANGES`
    holds whole numbers and `sanitize()` validates everything in it through
    `_whole_number()`. Storing 0.8 would need a second kind of validation for
    one setting."""
    assert isinstance(settings_store.DEFAULTS["speech_rate"], int)
    assert all(isinstance(bound, int)
               for bound in settings_store.RANGES["speech_rate"])


def test_the_ends_of_the_range_are_accepted():
    for value in settings_store.RANGES["speech_rate"]:
        assert settings_store.sanitize({"speech_rate": value})["speech_rate"] \
            == value


def test_a_value_outside_the_range_falls_back_to_the_default():
    """The same treatment `gapped_deck_size` gets — rejected rather than
    clamped, so a nonsense value cannot quietly become a nearby sensible one."""
    for value in (0, 10, 49, 151, 500, -100):
        assert settings_store.sanitize({"speech_rate": value})["speech_rate"] \
            == settings_store.DEFAULTS["speech_rate"], value


def test_something_that_is_not_a_number_falls_back_too():
    for value in ("fast", None, "", [], {}, True):
        assert settings_store.sanitize({"speech_rate": value})["speech_rate"] \
            == settings_store.DEFAULTS["speech_rate"], value


def test_a_missing_key_takes_the_default():
    assert settings_store.sanitize({})["speech_rate"] == 100


# --- saving it ------------------------------------------------------------


def test_it_saves_and_reads_back(user_client, settings_dir):
    user_client.post("/settings", json={"speech_rate": 80})
    body = user_client.get("/").get_data(as_text=True)
    assert 'data-speech-rate="80"' in body


def test_a_rejected_rate_is_logged_beside_what_was_stored(user_client,
                                                          settings_dir,
                                                          action_logs):
    """#161's rule: the store silently replaces an invalid value with the
    default, so what was asked for and what stuck are different questions."""
    user_client.post("/settings", json={"speech_rate": 900})
    logged = (action_logs / "cards.log").read_text(encoding="utf-8")
    assert "SETTINGS" in logged
    assert "speech_rate" in logged


def test_an_anonymous_visitor_cannot_change_it(client, settings_dir):
    """#102: settings are read-only for anonymous visitors, and this is one."""
    before = client.get("/").get_data(as_text=True)
    client.post("/settings", json={"speech_rate": 50})
    assert before.count('data-speech-rate="100"') == \
        client.get("/").get_data(as_text=True).count('data-speech-rate="100"')


# --- what the page carries ------------------------------------------------


def test_the_value_is_on_the_document_for_speech_js(client):
    """On the document rather than fetched: it is already in `settings` when
    the page renders, and an endpoint for one integer would be a round trip per
    utterance."""
    body = client.get("/").get_data(as_text=True)
    assert 'data-speech-rate="100"' in body


def test_the_popup_has_a_control_with_the_declared_bounds(client):
    """Read off `RANGES` rather than written into the template twice."""
    body = client.get("/").get_data(as_text=True)
    control = re.search(r'<input type="range" name="speech_rate"[^>]*>', body)
    assert control, "no speech_rate control in the settings popup"
    low, high = settings_store.RANGES["speech_rate"]
    assert f'min="{low}"' in control.group(0)
    assert f'max="{high}"' in control.group(0)


def test_the_control_is_disabled_for_an_anonymous_visitor(client):
    body = client.get("/").get_data(as_text=True)
    control = re.search(r'<input type="range" name="speech_rate"[^>]*>', body)
    assert "disabled" in control.group(0)


def test_the_control_is_live_for_an_account(user_client):
    body = user_client.get("/").get_data(as_text=True)
    control = re.search(r'<input type="range" name="speech_rate"[^>]*>', body)
    assert "disabled" not in control.group(0)


def test_the_popup_sends_it_with_everything_else(client):
    """One save, not a second endpoint."""
    body = client.get("/").get_data(as_text=True)
    assert "speech_rate: Number(settingsForm.speech_rate.value)" in body


def test_saving_rewrites_the_document_value(client):
    """So the next press is already at the new speed, without a reload —
    speech.js reads the attribute on every utterance rather than caching it."""
    body = client.get("/").get_data(as_text=True)
    assert "document.body.dataset.speechRate" in body


# --- reopening the popup shows what was saved -----------------------------
#
# The bug this section exists for: save 50%, reopen, and the slider sat at the
# centre while the label still read 50%.
#
# `form.reset()` restores each control's *default*, which is the value the
# server rendered at page load — so after an in-place save the defaults are
# stale. The save handler moved them forward for checkboxes and radios and for
# one named slider, so any control not on that list kept the old behaviour.
#
# Confirmed in a real browser rather than reasoned about. With the old
# narrow sync, a range edited to 50 and a number edited to 6 both came back as
# 100 and 10 after `reset()`, while a ticked checkbox held; with the loop, all
# three hold.


def test_every_input_has_its_default_moved_forward_after_a_save(client):
    """A loop rather than a hand-kept list, because the list is what failed —
    `speech_rate` was added without a line in it, and `gapped_deck_size` had
    the same gap from the day it landed."""
    body = client.get("/").get_data(as_text=True)
    assert 'settingsForm.querySelectorAll("input").forEach' in body
    # The old selector only ever reached checkboxes and radios.
    old_selector = 'input[type=checkbox], input[type=radio]'
    assert old_selector not in body


def test_the_number_beside_the_slider_is_refreshed_when_the_popup_opens(client):
    """`reset()` moves the slider but not the text beside it, so the number
    would keep whatever the last drag left there — which is how a 50% label
    ended up over a thumb sitting at 100."""
    body = client.get("/").get_data(as_text=True)
    opener = body.split("function openSettings()")[1].split("}")[0]
    assert "updateSpeechRate()" in opener
