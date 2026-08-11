"""Mykola's typewriting animation, and the setting that turns it off (ai_agent#50).

Presentation only: the words arrive at the same time either way, and the
animation is never allowed to outlive the text it is drawing. Which is exactly
what makes it dangerous — an animation that stalls does not look like a broken
animation, it looks like a broken answer, and it takes the closing event down
with it: no sources, no copy button, and no deck refresh for a card that really
was saved.

So what these tests pin is not the pacing (a number nobody can assert a feel
about) but the three ways it could swallow an answer.
"""

import json

import pytest

import settings_store


# --- the setting ------------------------------------------------------------

def test_it_is_on_by_default():
    """The chunky version is what it replaces, so a reader who wants the raw
    arrival has to say so — not the other way round."""
    assert settings_store.DEFAULTS["mykola_typewriter"] is True


@pytest.mark.parametrize("value,expected", [
    (True, True), (False, False),
    # Anything that is not a real boolean keeps the default rather than being
    # read for truthiness — so "" and 0 do *not* turn the animation off. The
    # checkbox only ever sends true or false, so this is about a hand-made
    # request, and falling back beats guessing what "0" was meant to mean.
    ("yes", True), ("", True), (1, True), (0, True), (None, True),
])
def test_it_is_validated_like_every_other_switch(value, expected):
    assert settings_store.sanitize(
        {"mykola_typewriter": value})["mykola_typewriter"] is expected


def test_turning_it_off_is_stored(user_client, settings_dir):
    resp = user_client.post("/settings", json={"mykola_typewriter": False})
    assert resp.status_code == 200
    assert resp.get_json()["settings"]["mykola_typewriter"] is False
    stored = json.loads(next(settings_dir.glob("config-7.json"))
                        .read_text(encoding="utf-8"))
    assert stored["mykola_typewriter"] is False


# --- the popup --------------------------------------------------------------

def test_the_popup_offers_it(user_client):
    body = user_client.get("/").get_data(as_text=True)
    assert 'name="mykola_typewriter"' in body
    assert "Show Mykola&rsquo;s typewriting animation" in body
    assert "mykola_typewriter: settingsForm.mykola_typewriter.checked" in body, \
        "the checkbox is rendered but never saved"


def test_an_anonymous_visitor_sees_it_read_only(client):
    """Settings are shared by every anonymous visitor and read-only for them
    (#102) — the control still renders so the site does not look different."""
    body = client.get("/").get_data(as_text=True)
    assert 'name="mykola_typewriter"' in body
    checkbox = body.split('name="mykola_typewriter"', 1)[1].split(">", 1)[0]
    assert "disabled" in checkbox


# --- the three ways an animation swallows an answer -------------------------

def test_it_is_driven_by_a_timer_not_animation_frames(client, app_module,
                                                      monkeypatch):
    """A browser stops running animation frames in a tab that is not on screen.
    Driven by requestAnimationFrame, an answer that arrived while the learner
    was reading another tab would sit half-typed forever — and the closing
    event would never be applied, losing the sources and a saved card's deck
    refresh with it. Found by measuring: the preview pane does not composite,
    so the first version of this hung exactly that way."""
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    body = client.get("/").get_data(as_text=True)
    assert "requestAnimationFrame(tick)" not in body
    assert "setTimeout(tick, TYPE_FRAME_MS)" in body


def test_a_hidden_tab_catches_up_at_once(client, app_module, monkeypatch):
    """Timers survive a hidden tab but are throttled, so typing there would
    crawl. Nobody is watching it type — finish the text instead."""
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    body = client.get("/").get_data(as_text=True)
    assert "document.hidden" in body


def test_reduced_motion_turns_it_off(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    body = client.get("/").get_data(as_text=True)
    assert "prefers-reduced-motion: reduce" in body


def test_the_closing_event_waits_for_the_typing_to_catch_up(client, app_module,
                                                            monkeypatch):
    """The answer is only settled — real bubble, sources, copy button, deck
    refresh — once the last character is on screen. Settling early would erase
    the animation mid-word; never settling would lose all of it."""
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    body = client.get("/").get_data(as_text=True)
    assert "if (closing) settle();" in body
    assert "if (!timer) settle();" in body, \
        "an answer that arrives with nothing left to type must still settle"
