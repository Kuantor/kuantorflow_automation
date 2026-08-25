"""Licensed translation providers (kuantorflow#353).

kuantorflow#348 ended with both scraped backends withdrawn on the same day and
the conclusion that swapping a `client` parameter to route around Google's
refusal was a worse posture than the one that broke. This file covers what
replaced them: four providers that license this use, offered only where the
deployment has the key.

Two properties are load-bearing and easy to lose:

* **the registry resolves fetchers by name**, so monkeypatching one is picked
  up — storing the function object captures it at import and silently breaks
  every stub in the suite, which is exactly what the first version did;
* **availability is read at call time**, so a key can be added without a code
  change and a test can set one without reloading a module.

No network: the HTTP providers are stubbed at `parsers.requests`, and Claude's
SDK is injected into `sys.modules` the way `test_generated_text.py` does it —
`anthropic` is deliberately not installed in this venv.
"""

import sys
import types

import pytest

import parsers
import settings_store


ALL_KEYS = ("ANTHROPIC_API_KEY", "MS_TRANSLATOR_KEY", "DEEPL_API_KEY",
            "GOOGLE_TRANSLATE_API_KEY")


@pytest.fixture()
def keys(monkeypatch):
    """Configure exactly the named providers and nothing else."""
    def configure(*names):
        for key in ALL_KEYS:
            monkeypatch.delenv(key, raising=False)
        for name in names:
            monkeypatch.setenv(parsers.translator(name).key_env, "test-key")
    return configure


class _Response:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise parsers.requests.HTTPError(f"{self.status_code}")


@pytest.fixture()
def posted(monkeypatch):
    """Record every outgoing POST and answer it from a queue."""
    calls = []

    def install(*responses):
        queue = list(responses)

        def post(url, **kwargs):
            calls.append({"url": url, **kwargs})
            return queue.pop(0) if queue else _Response({})

        monkeypatch.setattr(parsers.requests, "post", post)
        return calls
    return install


# --- the registry -----------------------------------------------------------

def test_only_configured_providers_are_offered(keys):
    keys("claude", "deepl")
    assert [t.slug for t in parsers.available_translators()] == ["claude", "deepl"]


def test_nothing_configured_is_a_real_state(keys):
    """And not an error. `lookup_word()` answers it with #349's card."""
    keys()
    assert parsers.available_translators() == ()
    assert parsers._translator_backend("claude") is None


def test_a_choice_whose_key_has_gone_falls_through(keys):
    """Rather than failing every lookup — the deployment lost a key, which is
    not the learner's problem to solve from the Settings panel."""
    keys("deepl")
    assert parsers._translator_backend("claude") is parsers._deepl_dictionary


def test_the_registry_resolves_fetchers_by_name(monkeypatch, keys):
    """Storing the function object captures it at import, and every stub in
    this suite silently reaches the real backend instead. That is not
    hypothetical: the first version of this registry did exactly that."""
    keys("claude")
    monkeypatch.setattr(parsers, "_claude_dictionary",
                        lambda word, code: {"noun": ["stub"]})
    assert parsers._translator_backend("claude")("x", "uk") == {"noun": ["stub"]}


def test_the_retired_scrapers_are_kept_but_unreachable():
    """They stay in the file so #348's history is readable — and a later
    cleanup should not delete them as dead code without deciding to."""
    assert callable(parsers._google_dictionary)
    assert callable(parsers._bing_dictionary)
    assert "google" not in parsers.TRANSLATOR_SLUGS
    assert "bing" not in parsers.TRANSLATOR_SLUGS


@pytest.mark.parametrize("retired", ["google", "bing"])
def test_a_stored_retired_provider_is_coerced_to_the_default(retired):
    """Nobody is stranded on a provider that cannot work (#352) — `sanitize()`
    replaces a value that is no longer a choice."""
    assert settings_store.sanitize({"translator": retired})["translator"] \
        == settings_store.DEFAULTS["translator"]


# --- what each provider returns --------------------------------------------

def test_microsoft_groups_by_part_of_speech(posted, keys):
    keys("microsoft")
    posted(_Response([{"translations": [
        {"posTag": "NOUN", "displayTarget": "дім"},
        {"posTag": "NOUN", "displayTarget": "будинок"},
        {"posTag": "VERB", "displayTarget": "тримати"},
    ]}]))
    assert parsers._microsoft_dictionary("house", "uk") == {
        "noun": ["дім", "будинок"], "verb": ["тримати"]}


def test_microsoft_falls_back_to_a_plain_translation(posted, keys):
    """Same shape the dictionary endpoint's miss has always taken."""
    keys("microsoft")
    posted(_Response([{"translations": []}]),
           _Response([{"translations": [{"text": "будь на зв'язку"}]}]))
    assert parsers._microsoft_dictionary("keep in touch", "uk") == {
        "other": ["будь на зв'язку"]}


def test_deepl_returns_one_untagged_entry(posted, keys):
    """DeepL translates and does not classify, so everything lands under
    `other` — a card with one part of speech rather than several, which is why
    it is not the default despite being the cheapest."""
    keys("deepl")
    posted(_Response({"translations": [{"text": "дім"}]}))
    assert parsers._deepl_dictionary("house", "uk") == {"other": ["дім"]}


def test_deepl_tries_the_paid_host_when_the_free_one_refuses(posted, keys):
    """A key works on one host only, and a 403 is how the wrong one says so."""
    keys("deepl")
    calls = posted(_Response({}, status=403),
                   _Response({"translations": [{"text": "дім"}]}))
    assert parsers._deepl_dictionary("house", "uk") == {"other": ["дім"]}
    assert [c["url"] for c in calls] == list(parsers.DEEPL_URLS)


def test_google_cloud_returns_one_untagged_entry(posted, keys):
    keys("google_cloud")
    posted(_Response({"data": {"translations": [{"translatedText": "дім"}]}}))
    assert parsers._google_cloud_dictionary("house", "uk") == {"other": ["дім"]}


def test_a_translation_identical_to_the_word_is_dropped(posted, keys):
    """Every provider does this: a service that echoes the English back has
    told us nothing, and a card claiming `house` means `house` is worse than a
    card with no translation at all."""
    keys("deepl")
    posted(_Response({"translations": [{"text": "House"}]}))
    assert parsers._deepl_dictionary("house", "uk") == {}


# --- Claude -----------------------------------------------------------------

@pytest.fixture()
def claude_sdk(monkeypatch):
    """A stub `anthropic` module; returns the recorded request kwargs."""
    sent = {}

    def install(payload):
        class _Messages:
            def create(self, **kwargs):
                sent.update(kwargs)
                return types.SimpleNamespace(content=[
                    types.SimpleNamespace(type="text", text=payload)])

        class _Client:
            def __init__(self, *a, **k):
                self.messages = _Messages()

        monkeypatch.setitem(sys.modules, "anthropic",
                            types.SimpleNamespace(Anthropic=_Client))
        return sent
    return install


def test_claude_groups_by_part_of_speech(claude_sdk, keys):
    keys("claude")
    claude_sdk('{"entries": [{"part_of_speech": "noun", '
               '"translations": ["дім", "будинок"]}, '
               '{"part_of_speech": "verb", "translations": ["тримати"]}]}')
    assert parsers._claude_dictionary("house", "uk") == {
        "noun": ["дім", "будинок"], "verb": ["тримати"]}


def test_claude_asks_for_structured_output(claude_sdk, keys):
    """The schema is the contract, so a malformed reply is not a failure mode.

    Its sibling in this file — `_split_glued_translations()` — asks for JSON in
    prose and strips ``` fences before parsing. That works and is a parsing
    problem that does not need to exist.
    """
    keys("claude")
    sent = claude_sdk('{"entries": []}')
    parsers._claude_dictionary("house", "uk")

    fmt = sent["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"] == parsers.TRANSLATE_SCHEMA
    assert fmt["schema"]["additionalProperties"] is False


def test_claude_is_told_which_language_and_bounded(claude_sdk, keys):
    keys("claude")
    sent = claude_sdk('{"entries": []}')
    parsers._claude_dictionary("house", "ru")

    assert "Russian" in sent["messages"][0]["content"]
    assert sent["max_tokens"] == parsers.TRANSLATE_MAX_TOKENS
    assert sent["model"] == parsers.TRANSLATE_MODEL


def test_claude_caps_the_terms_per_part_of_speech(claude_sdk, keys):
    """A model asked for three can return four; the card's width is this
    app's decision, not the model's."""
    keys("claude")
    claude_sdk('{"entries": [{"part_of_speech": "noun", '
               '"translations": ["a", "b", "c", "d", "e"]}]}')
    assert parsers._claude_dictionary("house", "uk") == {
        "noun": ["a", "b", "c"][:parsers.MAX_TRANSLATIONS]}


# --- the Settings panel -----------------------------------------------------

def test_the_panel_offers_what_is_configured(client, keys):
    keys("claude", "deepl")
    body = client.get("/").get_data(as_text=True)
    assert 'value="claude"' in body and 'value="deepl"' in body
    assert 'value="microsoft"' not in body


def test_the_panel_explains_an_unconfigured_deployment(client, keys):
    """Rather than an empty box — and it names the variables, because the
    person reading it is the one who can set them."""
    keys()
    body = client.get("/").get_data(as_text=True)
    assert "No translation service is configured" in body
    assert "ANTHROPIC_API_KEY" in body
    assert 'name="translator"' not in body


def test_a_provider_that_cannot_group_says_so_in_the_panel(client, keys):
    """DeepL and Google Cloud give one card per word. That is a real
    difference between the options and belongs where the choice is made."""
    keys("deepl")
    body = client.get("/").get_data(as_text=True)
    assert "one card per word" in body
