"""Accept either aspect of a verb in the Quiz (kuantorflow#100).

A Ukrainian or Russian verb is stored in one aspect at random, so the other
aspect of the same verb -- *відшкодувати* for *відшкодовувати*, *сложить* for
*складывать* -- was marked wrong. A rule cannot find the partner (the stem
often changes, and a prefix can change the meaning), so the pairs are read
**in advance** from Wiktionary's headword templates into `aspect_pairs`, and
the grader only looks them up:

* `aspects.partners_in_wikitext()` reads `{{uk-verb}}` / `{{ru-verb}}`:
  every `pf=` / `impf=` / `pf2=` ..., stress marks stripped, ё folded;
* `aspects.fetch_partners()` asks Wiktionary politely: batches, a pause, and
  `Retry-After` on a 429; a page that failed is left out, never stored as
  "no partner";
* `aspects.fill()` stores only forms not yet checked, both directions, and a
  marker for "checked, no partner"; `scripts/fill_aspect_pairs.py` runs it
  over the deck, and a new verb card is filled when it is saved;
* the Quiz (English -> Ukrainian/Russian) accepts a stored partner of any of a
  verb card's variants, in the quiz's own language, with the setting on; the
  results page says which.

Wiktionary and the database are faked here; `test_aspect_pairs_db.py` runs
the SQL for real.
"""

import json
import sys
import types
from pathlib import Path

import pytest

from conftest import KUANTORFLOW_PATH

import aspects

ACUTE = chr(0x301)
# The real lookup, kept before conftest's default stub replaces it for every
# test (so that no card save in the suite reaches Wiktionary).
FETCH = aspects.fetch_partners


# --- reading a page -----------------------------------------------------------

def test_a_form_is_normalised():
    assert aspects.normalise(" Написа" + ACUTE + "ти ") == "написати"
    assert aspects.normalise("ещё") == "еще"
    assert aspects.normalise("Сложи" + ACUTE + "ть") == "сложить"


def test_a_ukrainian_pair():
    text = "==Ukrainian==\n{{uk-verb|писа" + ACUTE + "ти|impf|pf=написа" + ACUTE + "ти}}\n"

    assert aspects.partners_in_wikitext(text, "ukr") == {"написати"}


def test_every_partner_is_read():
    text = "{{ru-verb|сложи" + ACUTE + "ть|pf|impf=скла" + ACUTE + "дывать|impf2=слага" + ACUTE + "ть}}"

    assert aspects.partners_in_wikitext(text, "rus") == {"складывать", "слагать"}


def test_several_partners_in_one_value_are_split():
    """Found by the first real fill: *завчити* names its imperfectives as
    `impf=завча́ти,заучува́ти`, one value with a comma."""
    text = "{{uk-verb|завчи" + ACUTE + "ти|pf|impf=завча" + ACUTE + "ти,заучува" + ACUTE + "ти}}"

    assert aspects.partners_in_wikitext(text, "ukr") == {"завчати", "заучувати"}


def test_a_verb_of_both_aspects_has_no_partner():
    """Its template is there and names nobody: checked, and no partner."""
    text = "{{uk-verb|імпровізува" + ACUTE + "ти|both}}"

    assert aspects.partners_in_wikitext(text, "ukr") == set()


def test_only_the_quiz_languages_own_template_counts():
    text = "{{ru-verb|писа" + ACUTE + "ть|impf|pf=написа" + ACUTE + "ть}}"

    assert aspects.partners_in_wikitext(text, "ukr") is None
    assert aspects.partners_in_wikitext("no verb here", "rus") is None


def test_two_headwords_on_one_page_are_both_read():
    text = ("{{ru-verb|сложи" + ACUTE + "ть|pf|impf=скла" + ACUTE + "дывать}}\n"
            "{{ru-verb|сложи" + ACUTE + "ть|pf|impf=сла" + ACUTE + "гать}}")

    assert aspects.partners_in_wikitext(text, "rus") == {"складывать", "слагать"}


def test_a_linked_partner_loses_its_brackets():
    text = "{{uk-verb|писа" + ACUTE + "ти|impf|pf=[[написа" + ACUTE + "ти]]}}"

    assert aspects.partners_in_wikitext(text, "ukr") == {"написати"}


# --- asking Wiktionary --------------------------------------------------------

class _Resp:
    def __init__(self, payload=None, status=200, headers=None):
        self.payload, self.status_code, self.headers = payload, status, headers or {}

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _page(title, content=None):
    if content is None:
        return {"title": title, "missing": True}
    return {"title": title, "revisions": [{"slots": {"main": {"content": content}}}]}


def test_fetch_reads_each_page_and_a_missing_page_is_no_partner():
    calls = []

    def get(url, params=None, **kw):
        calls.append(params["titles"].split("|"))
        return _Resp({"query": {"pages": [
            _page("писати", "{{uk-verb|писати|impf|pf=написати}}"),
            _page("гуляти")]}})

    found = FETCH(["писати", "гуляти"], "ukr", get=get, sleep=lambda s: None)

    assert found == {"писати": {"написати"}, "гуляти": set()}
    assert calls == [["писати", "гуляти"]]


def test_fetch_follows_a_redirect_back_to_the_form_asked_for():
    def get(url, params=None, **kw):
        return _Resp({"query": {"redirects": [{"from": "еще", "to": "ещё"}],
                                "pages": [_page("ещё", "{{ru-verb|x|impf|pf=y}}")]}})

    assert FETCH(["еще"], "rus", get=get, sleep=lambda s: None) == {"еще": {"y"}}


def test_fetch_asks_in_batches_with_a_pause():
    batches, pauses = [], []

    def get(url, params=None, **kw):
        titles = params["titles"].split("|")
        batches.append(len(titles))
        return _Resp({"query": {"pages": [_page(t) for t in titles]}})

    forms = [f"дієслово{i}" for i in range(60)]
    FETCH(forms, "ukr", get=get, sleep=pauses.append)

    assert batches == [aspects.BATCH, aspects.BATCH, 60 - 2 * aspects.BATCH]
    assert pauses.count(aspects.PAUSE_SECONDS) == 2


def test_fetch_honours_retry_after():
    answers = [_Resp(status=429, headers={"Retry-After": "7"}),
               _Resp({"query": {"pages": [_page("писати", "{{uk-verb|писати|impf|pf=написати}}")]}})]
    pauses = []

    found = FETCH(["писати"], "ukr", get=lambda *a, **k: answers.pop(0),
                                   sleep=pauses.append)

    assert found == {"писати": {"написати"}}
    assert 7 in pauses


def test_a_failed_batch_is_left_out_not_stored_as_no_partner():
    def get(url, params=None, **kw):
        raise ConnectionError("down")

    assert FETCH(["писати"], "ukr", get=get, sleep=lambda s: None) == {}


# --- filling the table --------------------------------------------------------

@pytest.fixture()
def store(monkeypatch):
    state = types.SimpleNamespace(checked=set(), saved=[], fetched=[])
    monkeypatch.setattr("utils.aspect_forms_checked",
                        lambda lang, forms: {f for f in forms if (lang, f) in state.checked})
    monkeypatch.setattr("utils.save_aspect_pairs",
                        lambda lang, found: state.saved.append((lang, dict(found))) or len(found))

    def fetch(forms, lang, **kw):
        state.fetched.append((lang, list(forms)))
        return {aspects.normalise(f): ({"написати"} if aspects.normalise(f) == "писати" else set())
                for f in forms}
    monkeypatch.setattr(aspects, "fetch_partners", fetch)
    return state


def test_fill_asks_only_for_forms_not_yet_checked(store, action_logs):
    store.checked.add(("ukr", "гуляти"))

    summary = aspects.fill({"ukr": ["Писа" + ACUTE + "ти", "гуляти"]}, source="script")

    assert store.fetched == [("ukr", ["писати"])]
    assert store.saved == [("ukr", {"писати": {"написати"}})]
    assert summary["ukr"] == {"asked": 1, "paired": 1}
    line = (action_logs / "dict.log").read_text(encoding="utf-8")
    assert "ASPECT-PAIRS" in line and "lang=ukr" in line and "source=script" in line


def test_fill_with_nothing_new_asks_nothing(store):
    store.checked.update({("ukr", "писати")})

    summary = aspects.fill({"ukr": ["писати"]}, source="script")

    assert store.fetched == [] and store.saved == []
    assert summary["ukr"] == {"asked": 0, "paired": 0}


def test_a_verb_card_is_filled_with_its_single_word_variants(store):
    aspects.fill_for_card({"word": "write", "pos": "verb",
                           "translation_ukr": "писати, брати в оренду",
                           "translation_rus": "писать"})

    assert ("ukr", ["писати"]) in store.fetched
    assert ("rus", ["писать"]) in store.fetched


@pytest.mark.parametrize("pos", ["noun", "adverb", "", None])
def test_only_verb_cards_are_filled(store, pos):
    aspects.fill_for_card({"word": "x", "pos": pos, "translation_ukr": "писати"})

    assert store.fetched == []


def test_a_failure_while_filling_never_raises(monkeypatch):
    def down(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr("utils.aspect_forms_checked", down)

    aspects.fill_for_card({"word": "write", "pos": "verb", "translation_ukr": "писати"})


# --- the save hook ------------------------------------------------------------

def test_saving_a_verb_card_fills_its_pairs_once_per_request(user_client, app_module,
                                                              monkeypatch):
    filled = []
    monkeypatch.setattr(aspects, "fill_for_card", lambda card: filled.append(card["word"]))
    monkeypatch.setattr("utils.save_flashcard", lambda entry, **kw: 101)

    import cards
    with app_module.app.test_request_context("/"):
        from flask import session
        session["user"] = {"id": 7, "email": "t@example.test", "name": "T"}
        # The noun first: once a verb has used the request's one lookup, a noun
        # slipping through would never show.
        cards._save_and_log({"word": "house", "pos": "noun", "translation_ukr": "дім"}, "test")
        cards._save_and_log({"word": "write", "pos": "verb", "translation_ukr": "писати"}, "test")
        cards._save_and_log({"word": "read", "pos": "verb", "translation_ukr": "читати"}, "test")

    assert filled == ["write"], "one Wiktionary request per page request, verbs only"


def test_a_failing_fill_never_costs_the_card(user_client, app_module, monkeypatch):
    def down(card):
        raise RuntimeError("wiktionary down")
    monkeypatch.setattr(aspects, "fill_for_card", down)
    monkeypatch.setattr("utils.save_flashcard", lambda entry, **kw: 102)

    import cards
    with app_module.app.test_request_context("/"):
        from flask import session
        session["user"] = {"id": 7, "email": "t@example.test", "name": "T"}
        assert cards._save_and_log({"word": "write", "pos": "verb",
                                    "translation_ukr": "писати"}, "test") is True


# --- the Quiz -----------------------------------------------------------------

CARDS = [
    {"id": 1, "word": "reimburse", "pos": "verb", "topic": "t",
     "translation_ukr": "відшкодовувати, повертати", "translation_rus": "возмещать"},
    {"id": 2, "word": "record", "pos": "noun", "topic": "t",
     "translation_ukr": "запис", "translation_rus": "запись"},
]
PAIRS = {"ukr": {"відшкодовувати": {"відшкодувати"}, "повертати": {"повернути"},
                 "запис": {"записати"}},
         "rus": {"возмещать": {"возместить"}}}


@pytest.fixture()
def quiz(user_client, monkeypatch):
    monkeypatch.setattr("utils.get_flashcards_by_topics",
                        lambda topics, owner_id=None, **kw: [dict(c) for c in CARDS])
    monkeypatch.setattr("utils.get_flashcards_by_topic",
                        lambda topic, owner_id=None, **kw: [dict(c) for c in CARDS])
    lookups = []

    def partners(lang, forms):
        lookups.append((lang, sorted(forms)))
        table = PAIRS.get(lang, {})
        return {f: table[f] for f in forms if f in table}
    monkeypatch.setattr("utils.aspect_partners", partners)
    user_client.lookups = lookups
    return user_client


def _post(client, lang, **answers):
    return client.post(f"/quiz/t?lang={lang}",
                       data={f"answer_{k[1:]}": v for k, v in answers.items()}
                       ).get_data(as_text=True)


def test_the_other_aspect_is_accepted_on_a_verb_card(quiz):
    body = _post(quiz, "ukr", a1="відшкодувати", a2="запис")

    assert "Score: 2 / 2" in body
    assert "the other aspect of" in body and "відшкодовувати" in body


def test_not_on_a_noun_card(quiz):
    body = _post(quiz, "ukr", a1="повертати", a2="записати")

    assert "Score: 1 / 2" in body


def test_not_across_languages(quiz):
    """A Russian partner does not answer a Ukrainian question."""
    body = _post(quiz, "ukr", a1="возместить", a2="запис")

    assert "Score: 1 / 2" in body


def test_a_pair_never_answers_a_noun_card(app_module):
    """The grader's own guard, beside the round's lookup of verb cards only:
    *записати* pairs with nothing on a card whose *запис* is a noun."""
    import rounds
    noun = {"word": "record", "pos": "noun", "translation_ukr": "запис"}
    verb = dict(noun, pos="verb", translation_ukr="записувати")

    assert rounds._aspect_of(noun, "записати", "translation_ukr", {"запис": {"записати"}}) is None
    assert rounds._aspect_of(verb, "записати", "translation_ukr",
                             {"записувати": {"записати"}}) == "записувати"


def test_an_exact_answer_is_still_exact(quiz):
    body = _post(quiz, "ukr", a1="повертати", a2="запис")

    assert "Score: 2 / 2" in body
    assert "the other aspect of" not in body


def test_the_setting_off_is_the_strict_quiz(quiz):
    quiz.post("/settings", json={"accept_verb_aspects": False})

    body = _post(quiz, "ukr", a1="відшкодувати", a2="запис")

    assert "Score: 1 / 2" in body
    assert quiz.lookups == []


def test_one_lookup_per_round(quiz):
    _post(quiz, "rus", a1="возместить", a2="запись")

    assert quiz.lookups == [("rus", ["возмещать"])], "verb cards' variants, in one query"


# --- the setting, the script, the guide ---------------------------------------

def test_the_setting_is_on_by_default_and_on_the_panel(client):
    import settings_store
    assert settings_store.DEFAULTS["accept_verb_aspects"] is True

    body = client.get("/").get_data(as_text=True)
    assert 'name="accept_verb_aspects"' in body
    assert "accept_verb_aspects: settingsForm.accept_verb_aspects.checked" in body


@pytest.fixture()
def script(monkeypatch, store):
    sys.path.insert(0, str(Path(KUANTORFLOW_PATH) / "scripts"))
    import fill_aspect_pairs
    monkeypatch.setattr("utils.verb_card_translations",
                        lambda: [("писати, брати в оренду", "писать"), ("гуляти", None)])
    return fill_aspect_pairs


def test_the_script_fills_both_languages(script, store, capsys):
    assert script.main([]) == 0

    assert ("ukr", ["писати", "гуляти"]) in store.fetched or ("ukr", ["гуляти", "писати"]) in store.fetched
    assert any(lang == "rus" for lang, _ in store.fetched)
    out = capsys.readouterr().out
    assert "ukr" in out and "rus" in out


def test_the_scripts_dry_run_asks_and_writes_nothing(script, store, capsys):
    assert script.main(["--dry-run"]) == 0

    assert store.fetched == [] and store.saved == []
    assert "would ask" in capsys.readouterr().out


def test_a_second_run_has_nothing_to_do(script, store, capsys):
    store.checked.update({("ukr", "писати"), ("ukr", "гуляти"), ("rus", "писать")})

    script.main([])

    assert store.fetched == []
    assert "nothing to do" in capsys.readouterr().out


def test_the_guide_says_so():
    guide = (Path(KUANTORFLOW_PATH) / "docs" / "user-guide.md").read_text(encoding="utf-8")

    assert "Accept either aspect of a verb" in guide
    assert "написати" in guide
