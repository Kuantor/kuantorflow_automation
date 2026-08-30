"""The lookup panel names both providers (kuantorflow#384).

A lookup asks two: a translator, and the explanatory dictionary that writes the
half of the card a learner reads first — the English explanation and the
authentic examples. The heading said only the translator.

Two things make this more than a string:

* **it has to name what will actually be asked.** `_dictionary_backend()` and
  `_translator_backend()` fall back to the first provider this deployment can
  use when the stored choice has no key, and deliberately leave the setting
  alone (#365) — so a heading that read the stored slug would announce a
  provider that is never contacted. The template renders an answer that
  `parsers` resolved, through the same functions the dispatch uses;
* **the short name, not the label.** Settings says *Oxford Learner's
  Dictionaries* and *Google Cloud Translation*, which is right there and a
  sentence in a heading.
"""

import re

import pytest

import parsers


def heading(body):
    found = re.search(r"<h2>Look up a word[^<]*</h2>", body)
    return found.group(0) if found else None


@pytest.fixture()
def keys(monkeypatch):
    """Which providers this deployment can reach, decided per test.

    `available_translators()` reads the environment at call time, which is what
    lets this set one without reloading a module -- the property #353 wrote the
    registry for.
    """
    def install(**present):
        for provider in parsers.TRANSLATORS + parsers.DICTIONARIES:
            if not provider.key_env:
                continue
            if provider.slug in present:
                monkeypatch.setenv(provider.key_env, "test-key-never-used")
            else:
                monkeypatch.delenv(provider.key_env, raising=False)
    return install


@pytest.fixture()
def choose(user_client):
    def install(**settings):
        user_client.post("/settings", json=settings)
        return user_client.get("/").get_data(as_text=True)
    return install


# --- both providers, named --------------------------------------------------

def test_the_heading_names_the_translator_and_the_dictionary(keys, choose):
    keys(claude=True)

    assert heading(choose(translator="claude",
                          explanatory_dictionary="oxford")) == \
        "<h2>Look up a word (Claude + Oxford)</h2>"


def test_it_follows_the_dictionary_choice(keys, choose):
    """Only Oxford is reachable today (#365 greys Merriam-Webster for want of
    a key), so the choice is followed by *asking*, not by hard-coding the one
    answer -- the argument #353 made when it replaced a ternary over two
    provider names with a render from the registry."""
    keys(claude=True, **{"merriam-webster": True})

    assert "Merriam-Webster" in heading(
        choose(translator="claude", explanatory_dictionary="merriam-webster"))


def test_the_short_name_rather_than_the_settings_label(keys, choose):
    """`Look up a word (Google Cloud Translation + Oxford Learner's
    Dictionaries)` is a sentence. Settings keeps the full names, where they
    identify a product being chosen."""
    keys(google_cloud=True)
    body = choose(translator="google_cloud", explanatory_dictionary="oxford")

    assert heading(body) == "<h2>Look up a word (Google + Oxford)</h2>"
    assert "Google Cloud Translation" in body, "and Settings still says it in full"


def test_every_provider_has_a_short_name(app_module):
    """Defaulted to the label, so a provider whose name is already short adds
    nothing -- but none may be missing, or a heading falls back to a sentence
    on the day a fifth provider is added."""
    for provider in parsers.TRANSLATORS + parsers.DICTIONARIES:
        assert provider.name, provider.slug
        assert len(provider.name) <= len(provider.label)


# --- what will actually be asked, not what is stored -----------------------

def test_a_choice_this_deployment_cannot_use_is_not_announced(keys, choose):
    """The bug this ticket really fixes. An account that chose Merriam-Webster
    where there is no key is served by Oxford (#365 falls back and leaves the
    setting alone, so the choice survives until a key arrives) -- and the
    heading has to say Oxford, because Oxford is what answers."""
    keys(claude=True)          # no MERRIAM_WEBSTER_API_KEY

    assert heading(choose(translator="claude",
                          explanatory_dictionary="merriam-webster")) == \
        "<h2>Look up a word (Claude + Oxford)</h2>"


def test_the_same_for_a_translator_whose_key_has_gone(keys, choose):
    """It used to render **nothing** in the parentheses here: the template
    picked from the *available* list, so a stored-but-unreachable choice
    matched none of them while the lookup quietly used another provider."""
    keys(claude=True)          # no MS_TRANSLATOR_KEY

    assert heading(choose(translator="microsoft",
                          explanatory_dictionary="oxford")) == \
        "<h2>Look up a word (Claude + Oxford)</h2>"


def test_with_no_translator_at_all_it_names_the_dictionary_alone(keys, choose):
    """A real state since #348 and the one #349 answers with a dictionary-only
    card. Empty parentheses would be the tell-tale of a heading built by
    joining two things that might not be there."""
    keys()                     # nothing configured

    assert heading(choose(translator="claude",
                          explanatory_dictionary="oxford")) == \
        "<h2>Look up a word (Oxford)</h2>"


# --- one resolution, two readers -------------------------------------------

@pytest.mark.parametrize("stored,expected", [
    ("claude", "claude"),          # configured, so it is used
    ("microsoft", "claude"),       # not configured, so the fallback is
    ("nonsense", "claude"),
])
def test_the_resolver_answers_what_the_dispatch_dispatches(keys, stored,
                                                           expected):
    """The heading and the lookup must not resolve differently, which is why
    the resolution moved next to the dispatch rather than into the template.
    Compared against the *backend* the dispatch picks, so this fails if either
    side grows a rule the other does not have."""
    keys(claude=True)

    resolved = parsers.resolved_translator(stored)
    backend = parsers._translator_backend(stored)

    assert resolved.slug == expected
    assert resolved.fetch is backend


def test_the_same_for_the_dictionary(keys):
    keys()                     # Oxford needs no key and is always there

    assert parsers.resolved_dictionary("merriam-webster").slug == "oxford"
    assert (parsers.resolved_dictionary("merriam-webster").fetch
            is parsers._dictionary_backend("merriam-webster"))


def test_no_translator_resolves_to_nothing_rather_than_a_default(keys):
    """None is the answer `lookup_word()` reads as "no translator", and #349's
    dictionary-only card depends on it. A resolver that helpfully returned the
    first entry would turn that into a lookup against a provider with no key.
    """
    keys()

    assert parsers.resolved_translator("claude") is None
    assert parsers._translator_backend("claude") is None


def test_the_dictionary_never_resolves_to_nothing(keys):
    """Oxford needs no key, which is why `available_dictionaries()` cannot come
    back empty -- and the backend still falls back to Oxford even if it did,
    since an explanation is most of a card's value (#349)."""
    keys()

    assert parsers.resolved_dictionary("oxford").slug == "oxford"
