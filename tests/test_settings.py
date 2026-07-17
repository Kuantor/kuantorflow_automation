"""Settings store, POST /settings, the Settings popup, and auto-add (#86, #13, #20)."""

import json
import re

import settings_store


# --- The store (#86) ----------------------------------------------------------

def test_first_load_creates_default_config_file(settings_dir):
    values = settings_store.load(None)
    assert values == settings_store.DEFAULTS
    path = settings_dir / "config-default.json"
    assert path.exists(), "first read must materialise the config file"
    assert json.loads(path.read_text(encoding="utf-8")) == settings_store.DEFAULTS


def test_first_load_creates_per_user_config_file(settings_dir):
    settings_store.load("Anton.Kuznietsov@gmail.com")
    assert (settings_dir / "config-anton.kuznietsov.json").exists()
    assert not (settings_dir / "config-default.json").exists()


def test_corrupt_config_falls_back_without_being_overwritten(settings_dir):
    settings_dir.mkdir(parents=True)
    path = settings_dir / "config-default.json"
    path.write_text("{not json", encoding="utf-8")
    assert settings_store.load(None) == settings_store.DEFAULTS
    assert path.read_text(encoding="utf-8") == "{not json", \
        "a corrupt (possibly hand-edited) file must never be clobbered"


# --- POST /settings (#13, #20) ------------------------------------------------

def test_settings_endpoint_saves_and_validates(client, settings_dir):
    r = client.post("/settings", json={
        "cards_automatically": True,
        "translator": "bing",
        "explanatory_dictionary": "no-such-dictionary",   # invalid -> default
        "unknown_key": "dropped",
    })
    assert r.status_code == 200
    stored = r.get_json()["settings"]
    assert stored["cards_automatically"] is True
    assert stored["translator"] == "bing"
    assert stored["explanatory_dictionary"] == "oxford"
    assert "unknown_key" not in stored

    on_disk = json.loads(
        (settings_dir / "config-default.json").read_text(encoding="utf-8"))
    assert on_disk == stored


def test_settings_saved_per_identity(client, settings_dir):
    client.post("/settings", json={"translator": "bing"})

    with client.session_transaction() as sess:
        sess["user"] = {"name": "Anton", "email": "anton.test@gmail.com"}
    client.post("/settings", json={"translator": "google",
                                   "cards_automatically": True})

    default = json.loads(
        (settings_dir / "config-default.json").read_text(encoding="utf-8"))
    personal = json.loads(
        (settings_dir / "config-anton.test.json").read_text(encoding="utf-8"))
    assert default["translator"] == "bing"
    assert default["cards_automatically"] is False
    assert personal["translator"] == "google"
    assert personal["cards_automatically"] is True


# --- The Settings popup (#13, #20) --------------------------------------------

def test_settings_popup_markup(client):
    body = client.get("/").get_data(as_text=True)
    assert 'id="settings-link"' in body            # header menu item
    assert 'id="settings-modal"' in body
    assert 'name="cards_automatically"' in body    # #13 checkbox
    for value in ("google", "bing", "oxford", "merriam-webster"):
        assert f'value="{value}"' in body          # #20 radio families


def test_settings_popup_prefilled_from_store(client):
    client.post("/settings", json={"translator": "bing",
                                   "cards_automatically": True})
    body = client.get("/").get_data(as_text=True)
    assert re.search(r'value="bing"\s+checked', body)
    assert re.search(r'name="cards_automatically"\s+checked', body)
    # the lookup panel title follows the translator choice (#20)
    assert "Look up a word (Bing Translator)" in body


# --- Quiz language toggle (#113) ----------------------------------------------

def test_quiz_lang_defaults_to_ukrainian_and_validates(client, settings_dir):
    r = client.post("/settings", json={"quiz_lang": "no-such-language"})
    assert r.get_json()["settings"]["quiz_lang"] == "ukrainian"  # invalid -> default
    r = client.post("/settings", json={"quiz_lang": "russian"})
    assert r.get_json()["settings"]["quiz_lang"] == "russian"


def test_quiz_lang_toggle_enabled_when_both_languages_visible(client):
    body = client.get("/").get_data(as_text=True)
    assert re.search(r'name="quiz_lang"\s+value="ukrainian"\s+checked', body)
    assert "quiz-lang-hint" in body
    match = re.search(r'name="quiz_lang"[^>]*value="ukrainian"[^>]*', body)
    assert "disabled" not in match.group(0)


def test_quiz_lang_toggle_disabled_when_one_language_hidden(client):
    client.post("/settings", json={"show_russian": False})
    body = client.get("/").get_data(as_text=True)
    for value in ("ukrainian", "russian"):
        section = re.search(
            r'name="quiz_lang"\s+value="%s"[\s\S]{0,120}?>' % value, body)
        assert "disabled" in section.group(0), f"{value} radio must be disabled"
    # the hint is shown (not hidden) in this state
    hint = re.search(r'<p [^>]*id="quiz-lang-hint"[^>]*>', body)
    assert "hidden" not in hint.group(0)


# --- Auto-add on lookup (#13) -------------------------------------------------

def _stub_lookup(app_module, monkeypatch):
    monkeypatch.setattr(
        app_module,
        "lookup_word",
        lambda word, topic=None, **providers: [
            {"word": word, "pos": "adjective", "translation_ukr": "стійкий",
             "topic": topic},
            {"word": word, "pos": "noun", "translation_ukr": "стійкість",
             "topic": topic},
        ],
    )


def test_auto_add_saves_without_review_popup(client, app_module, monkeypatch, saved):
    _stub_lookup(app_module, monkeypatch)
    client.post("/settings", json={"cards_automatically": True})
    r = client.post("/", data={"action": "parse_word", "word": "resilient",
                               "topic": "character"}, follow_redirects=True)
    body = r.get_data(as_text=True)
    assert [e["word"] for e in saved] == ["resilient", "resilient"]
    # Jinja autoescaping turns the quotes around the word into &#39;
    assert "Added 2 card(s) for &#39;resilient&#39; automatically." in body
    assert "proposal-card" not in body, "no review popup in automatic mode"


def test_lookup_receives_the_stored_providers(client, app_module, monkeypatch, saved):
    calls = []

    def capture(word, topic=None, **providers):
        calls.append(providers)
        return [{"word": word, "pos": "noun", "topic": topic}]

    monkeypatch.setattr(app_module, "lookup_word", capture)
    client.post("/settings", json={"translator": "bing",
                                   "explanatory_dictionary": "merriam-webster"})
    client.post("/", data={"action": "parse_word", "word": "run"})
    assert calls == [{"translator": "bing",
                      "explanatory_dictionary": "merriam-webster"}]
