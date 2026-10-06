"""Translations in the wrong alphabet never reach a card (kuantorflow#544).

A translator -- usually the model -- can drift mid-answer: into another
language (语言学 in a Ukrainian field), into the neighbouring one
(языкознавство offered as Ukrainian), or into one stray letter from another
alphabet (екзубeрантний with a Latin "e"). The last is the worst: it looks
identical to the right word, is not equal to it, and marks a learner wrong for
typing it correctly.

Pinned here:

* **the rule on plain strings:** every *letter* must be Cyrillic, Ukrainian
  must not hold ы ё ъ э, Russian must not hold є ї ґ і; punctuation, stress
  marks and ʼ pass (the deck holds all three, correctly);
* **a bad variant is dropped, its neighbours kept**, and each drop is logged;
* **a translator whose every variant fails counts as having found nothing**,
  so the next configured one answers;
* **the console report** lists exactly the failing variants.
"""

import importlib.util
from pathlib import Path

import pytest

import parsers

KUANTORFLOW = Path(parsers.__file__).parent


def _lines(action_logs, action):
    path = action_logs / "dict.log"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return [l for l in text.splitlines() if f" {action} " in l]


# --- the rule -------------------------------------------------------------

@pytest.mark.parametrize("variant, lang, why", [
    ("语言学", "ukr", "not Cyrillic"),                  # another language
    ("екзубeрантний", "ukr", "not Cyrillic"),           # one Latin e (U+0065)
    ("овerfitting", "rus", "not Cyrillic"),             # half Latin
    ("языкознавство", "ukr", "not a Ukrainian letter"),  # ы is Russian
    ("ёлка", "ukr", "not a Ukrainian letter"),
    ("подъезд", "ukr", "not a Ukrainian letter"),
    ("эхо", "ukr", "not a Ukrainian letter"),
    ("інтернет", "rus", "not a Russian letter"),        # і is Ukrainian
    ("їжа", "rus", "not a Russian letter"),
    ("ґанок", "rus", "not a Russian letter"),
    ("єдиний", "rus", "not a Russian letter"),
])
def test_a_wrong_alphabet_is_refused(variant, lang, why):
    problem = parsers.script_problem(variant, lang)

    assert problem and problem.startswith(why), problem


def test_the_reason_names_the_hidden_letter():
    """`e` and `е` look the same; the code point is what tells them apart."""
    assert "U+0065" in parsers.script_problem("екзубeрантний", "ukr")


@pytest.mark.parametrize("variant, lang", [
    ("предʼявляти звинувачення", "ukr"),   # ʼ, the Ukrainian apostrophe
    ("сім'я", "ukr"),                       # ' as typed
    ("п’ять", "ukr"),                       # ’
    ("цікавий; дивний", "ukr"),             # in the local deck
    ("оставить после себя много последствий/шума.", "rus"),  # in the deck
    ("экзубе́рантный", "rus"),               # a stress mark (U+0301)
    ("як-небудь", "ukr"),
    ("(розм.) крутий", "ukr"),
    ("ёлка", "rus"), ("подъезд", "rus"), ("эхо", "rus"), ("мыло", "rus"),
    ("їжа", "ukr"), ("ґанок", "ukr"), ("єдиний", "ukr"), ("інтернет", "ukr"),
    ("", "ukr"),
])
def test_a_right_translation_passes(variant, lang):
    assert parsers.script_problem(variant, lang) is None


# --- dropping, keeping, logging -------------------------------------------

def test_a_bad_variant_is_dropped_and_its_neighbours_kept(action_logs):
    kept = parsers.checked_translations(
        {"noun": ["лінгвістика", "мовознавство", "语言学"],
         "adjective": ["екзубeрантний"]},
        "ukr", "claude", "linguistics")

    assert kept == {"noun": ["лінгвістика", "мовознавство"]}, \
        "the emptied part of speech goes too"


def test_each_drop_is_logged(action_logs):
    parsers.checked_translations({"noun": ["мовознавство", "语言学"]},
                                 "ukr", "claude", "linguistics")

    (line,) = _lines(action_logs, "TRANSLATE-DROPPED")
    assert "word=linguistics" in line and "provider=claude" in line
    assert "lang=uk " in line and "pos=noun" in line
    assert "variant=语言学" in line and "U+8BED" in line


def _stub_dictionary(monkeypatch):
    monkeypatch.setattr(parsers, "_fetch_oxford_entry", lambda word: ({}, {}))
    monkeypatch.setattr(parsers, "_fetch_definitions", lambda word: {})


def test_a_lookup_never_saves_a_wrong_alphabet(monkeypatch, action_logs):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-used")
    monkeypatch.setattr(parsers, "_claude_dictionary", lambda word, code: {
        "noun": ["лінгвістика", "语言学"] if code == "uk"
        else ["лингвистика", "языкознание"]})
    _stub_dictionary(monkeypatch)

    (card,) = parsers.lookup_word("linguistics", translator="claude",
                                  explanatory_dictionary="oxford")

    assert card["translation_ukr"] == "лінгвістика"
    assert card["translation_rus"] == "лингвистика, языкознание"


def test_a_translator_with_nothing_usable_falls_through_to_the_next(
        monkeypatch, action_logs):
    """Every variant refused is an empty answer, which #353 already answers
    by asking the next configured translator."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-used")
    monkeypatch.setenv("MS_TRANSLATOR_KEY", "test-key-never-used")
    monkeypatch.setattr(parsers, "_microsoft_dictionary", lambda word, code: {
        "noun": ["语言学"] if code == "uk" else ["лингвистика"]})
    monkeypatch.setattr(parsers, "_claude_dictionary", lambda word, code: {
        "noun": ["мовознавство"] if code == "uk" else ["не нужно"]})
    _stub_dictionary(monkeypatch)

    (card,) = parsers.lookup_word("linguistics", translator="microsoft",
                                  explanatory_dictionary="oxford")

    assert card["translation_ukr"] == "мовознавство", "Claude answered instead"
    assert card["translation_rus"] == "лингвистика", "Microsoft's Russian was fine"
    ukr = [l for l in _lines(action_logs, "TRANSLATE") if "lang=uk " in l]
    assert "provider=claude" in ukr[1] and "fallback_from=microsoft" in ukr[1]


# --- the console report ---------------------------------------------------

def _report_module():
    path = KUANTORFLOW / "scripts" / "find_bad_translations.py"
    spec = importlib.util.spec_from_file_location("find_bad_translations", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CARDS = [
    {"id": 707, "word": "indict", "topic": "Crime",
     "translation_ukr": "предʼявляти звинувачення", "translation_rus": "обвинять"},
    {"id": 774, "word": "exuberant", "topic": "Emotions",
     "translation_ukr": "бурхливий, екзубeрантний",
     "translation_rus": "экзубе́рантный"},
    {"id": 789, "word": "overfitting", "topic": "AI",
     "translation_ukr": None, "translation_rus": "переобучение, овerfitting"},
    {"id": 800, "word": "linguistics", "topic": "Language",
     "translation_ukr": "лінгвістика, языкознавство", "translation_rus": ""},
]


def test_the_report_lists_exactly_the_failing_variants():
    found = _report_module().bad_translations(CARDS)

    assert [(r[0], r[3], r[4]) for r in found] == [
        (774, "translation_ukr", "екзубeрантний"),
        (789, "translation_rus", "овerfitting"),
        (800, "translation_ukr", "языкознавство"),
    ]
    assert found[0][2] == "Emotions", "the topic, where the card is edited"


def test_the_report_writes_nothing_and_prints_ascii(monkeypatch, capsys):
    module = _report_module()

    class _Cursor:
        def execute(self, sql, *a):
            assert sql.lstrip().upper().startswith("SELECT"), sql

        def fetchall(self):
            return CARDS

    class _Conn:
        def cursor(self, **k):
            return _Cursor()

        def close(self):
            pass

        def commit(self):
            raise AssertionError("a report-only script committed")

    monkeypatch.setattr(module, "get_db_connection", lambda: _Conn())
    module.main([])
    out = capsys.readouterr().out

    out.encode("ascii")       # a cp1252 console must be able to print it
    assert "card 774" in out and "U+0065" in out
    assert "3 variant(s) on 3 of 4 cards" in out
