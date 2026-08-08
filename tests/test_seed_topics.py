"""
The seeding script and its word list (kuantorflow#203) — offline.

`seed_topics.py` turns `seed_words.py` into cards through the app's own
`lookup_word()` and `save_flashcard()`. Both are stubbed here: **these tests
never touch a dictionary or a database.** 360 words over a network is what the
script exists to do once, not what a test suite should do on every run.

What is worth pinning down is the set of properties the script borrowed from
`apply_schema.py`, because each one is a specific failure someone would otherwise
hit 300 words into a run they cannot repeat cheaply:

* the word list's *shape*, checked before anything is looked up,
* `--dry-run` spending no lookups and writing nothing,
* a re-run adding only what is missing,
* one failed word not ending the run, and being named at the end,
* the two passes happening in the right order — topics placed as a curriculum
  *before* their cards exist, or `save_flashcard()` would file all eighteen
  under 'Other'.

The end-to-end run against a real MySQL is `test_seed_topics_db.py` (marker db).
"""

import io

import pytest

import seed_topics
import seed_words


# --- the word list is data, so its shape is a test ----------------------


def test_the_word_list_has_no_problems():
    """`seed_words.problems()` is the single validator — the script runs it, and
    so does this. A complaint here is a content bug, not a code bug."""
    assert seed_words.problems() == []


def test_every_topic_has_exactly_twenty_words():
    for topic, words in seed_words.SEED_WORDS.items():
        assert len(words) == seed_words.WORDS_PER_TOPIC, topic


def test_no_word_appears_under_two_topics():
    """Deduplication is global by word + part of speech (#101), so a repeat is
    not a crash — it is a card filed under whichever topic reached it first and a
    second topic quietly nineteen words long."""
    assert seed_words.duplicates() == {}


def test_words_are_single_lower_case_tokens():
    """`lookup_word()` sends each to a translator and a dictionary. A mashed
    compound like 'peerreview' satisfies "one token" and is not a word — it
    would fail every lookup and read as a provider problem."""
    for topic, words in seed_words.SEED_WORDS.items():
        for word in words:
            assert word.isalpha() and word == word.lower(), f"{topic}: {word!r}"


def test_the_list_is_ordered_not_sorted():
    """Order is load-bearing twice: the lookup order (so an interrupted run
    leaves the *useful* half) and `topics.position` in the section. Alphabetical
    would mean somebody sorted it and broke both."""
    topics = list(seed_words.SEED_WORDS)
    assert topics != sorted(topics)
    assert topics[0] == "Work and careers"


def test_a_broken_list_stops_the_script_before_any_lookup(monkeypatch, capsys):
    """Checked first, always — a topic of nineteen words would otherwise be
    found out 300 lookups in."""
    monkeypatch.setattr(seed_words, "problems", lambda: ["Topic: 19 words"])
    calls = []
    monkeypatch.setattr(seed_topics, "lookup_word",
                        lambda *a, **k: calls.append(a))

    assert seed_topics.main([]) == 1
    assert "19 words" in capsys.readouterr().err
    assert calls == [], "it looked something up anyway"


def test_check_validates_and_exits_without_touching_anything(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(seed_topics, "lookup_word",
                        lambda *a, **k: calls.append(a))
    monkeypatch.setattr(seed_topics, "place_topic",
                        lambda *a, **k: calls.append(a))

    assert seed_topics.main(["--check"]) == 0
    out = capsys.readouterr().out
    assert "18 topics" in out and "360 words" in out
    assert calls == []


# --- choosing what to run -----------------------------------------------


def test_topic_selects_one_and_is_case_insensitive():
    """It arrives from a console, where nobody matches capitals exactly."""
    chosen = seed_topics.chosen_topics("crime AND justice")
    assert list(chosen) == ["Crime and justice"]
    assert len(chosen["Crime and justice"]) == 20


def test_an_unknown_topic_lists_the_known_ones():
    with pytest.raises(LookupError) as excinfo:
        seed_topics.chosen_topics("Underwater Basket Weaving")
    assert "Work and careers" in str(excinfo.value)


def test_no_topic_means_all_of_them():
    assert list(seed_topics.chosen_topics(None)) == list(seed_words.SEED_WORDS)


def test_a_partial_run_does_not_renumber_the_section(monkeypatch):
    """A `--topic` run has to place its one topic at the number it holds in the
    *full* curriculum. Numbering from the chosen subset would put whatever you
    ran last at position 1."""
    placed = []
    monkeypatch.setattr(seed_topics, "place_topic",
                        lambda name, section, position, created_by_user_id=None:
                        (placed.append((name, section, position)), ("created", 1))[1])

    seed_topics.place_topics(seed_topics.chosen_topics("Sport and competition"),
                             None, dry_run=False, out=io.StringIO())

    assert placed == [("Sport and competition",
                       seed_topics.SECTION, 18)], "the last topic is 18th"


# --- the two passes, in order -------------------------------------------


@pytest.fixture()
def spy(monkeypatch):
    """Record the order of placements and saves, looking nothing up."""
    events = []

    def fake_lookup(word, topic=None, translator=None,
                    explanatory_dictionary=None):
        events.append(("lookup", word, topic))
        return [{"word": word, "pos": "noun", "topic": topic,
                 "translation_ukr": "x"}]

    def fake_place(name, section, position, created_by_user_id=None):
        events.append(("place", name, position))
        return "created", position

    def fake_save(entry, added_by_user_id=None):
        events.append(("save", entry["word"], entry["topic"]))
        return 1

    monkeypatch.setattr(seed_topics, "lookup_word", fake_lookup)
    monkeypatch.setattr(seed_topics, "place_topic", fake_place)
    monkeypatch.setattr(seed_topics, "save_flashcard", fake_save)
    return events


def test_every_topic_is_placed_before_any_card_is_saved(spy):
    """The whole reason there are two passes. `save_flashcard()` files an unknown
    topic under 'Other' at position 0 — correct for a topic a learner invents,
    wrong for a curriculum — so the rows have to exist first."""
    seed_topics.run(seed_topics.chosen_topics(None), None, None,
                    "google", "oxford", pause=0, out=io.StringIO())

    kinds = [e[0] for e in spy]
    assert kinds.count("place") == 18
    assert set(kinds[:18]) == {"place"}, "a save happened before the last place"


def test_the_cards_carry_their_topic(spy):
    seed_topics.run(seed_topics.chosen_topics("Art and culture"), None, None,
                    "google", "oxford", pause=0, out=io.StringIO())
    saves = [e for e in spy if e[0] == "save"]
    assert len(saves) == 20
    assert {e[2] for e in saves} == {"Art and culture"}


def test_the_chosen_providers_reach_the_lookup(monkeypatch):
    """Passed explicitly, never read from a settings file: the script is not a
    user, and a deck whose contents depend on whose config was lying around is
    not reproducible."""
    seen = []
    monkeypatch.setattr(seed_topics, "place_topic",
                        lambda *a, **k: ("created", 1))
    monkeypatch.setattr(seed_topics, "save_flashcard", lambda *a, **k: 1)
    monkeypatch.setattr(
        seed_topics, "lookup_word",
        lambda word, topic=None, translator=None, explanatory_dictionary=None:
        (seen.append((translator, explanatory_dictionary)), [])[1])

    seed_topics.run(seed_topics.chosen_topics("Art and culture"), None, None,
                    "bing", "merriam", pause=0, out=io.StringIO())

    assert set(seen) == {("bing", "merriam")}


def test_the_defaults_are_the_settings_defaults():
    """Google + Oxford, which are also the two that work from PythonAnywhere."""
    import settings_store

    assert seed_topics.DEFAULT_TRANSLATOR == settings_store.DEFAULTS["translator"]
    assert seed_topics.DEFAULT_DICTIONARY == \
        settings_store.DEFAULTS["explanatory_dictionary"]


def test_the_section_is_the_one_215_created_empty():
    """Not a flag: putting the curriculum somewhere else is not something a run
    of this script should be able to do quietly."""
    assert seed_topics.SECTION == "B2–C1 Conversational Topics"


# --- a dry run spends nothing -------------------------------------------


def test_a_dry_run_looks_nothing_up_and_places_nothing(monkeypatch, capsys):
    """It must not spend 360 network requests telling you what it would spend
    them on."""
    calls = []
    monkeypatch.setattr(seed_topics, "lookup_word",
                        lambda *a, **k: calls.append("lookup"))
    monkeypatch.setattr(seed_topics, "place_topic",
                        lambda *a, **k: calls.append("place"))
    monkeypatch.setattr(seed_topics, "save_flashcard",
                        lambda *a, **k: calls.append("save"))
    monkeypatch.setattr(seed_topics, "current_placement", lambda topics: {})

    assert seed_topics.main(["--dry-run"]) == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "nothing was changed" in out
    assert "360 word(s) would be looked up" in out


def test_a_dry_run_names_a_topic_it_would_move(monkeypatch, capsys):
    """The one thing the seed does to data somebody else made, so it is visible
    before it happens rather than in the log afterwards."""
    monkeypatch.setattr(seed_topics, "current_placement",
                        lambda topics: {"Sport and competition": ("Other", 0)})

    seed_topics.main(["--dry-run", "--topic", "Sport and competition"])

    out = capsys.readouterr().out
    assert "would MOVE from 'Other' position 0" in out


def test_a_dry_run_says_when_a_topic_is_already_in_place(monkeypatch, capsys):
    monkeypatch.setattr(
        seed_topics, "current_placement",
        lambda topics: {"Sport and competition": (seed_topics.SECTION, 18)})

    seed_topics.main(["--dry-run", "--topic", "Sport and competition"])
    assert "already in place" in capsys.readouterr().out


# --- one bad word must not end the run ----------------------------------


def test_a_failed_lookup_skips_the_word_and_the_run_continues(monkeypatch):
    """Losing word 12 of 360 must not cost the other 348. Reverso and
    Merriam-Webster are blocked from PythonAnywhere's IPs, so this is the
    ordinary case there, not the exotic one."""
    saved = []
    monkeypatch.setattr(seed_topics, "place_topic", lambda *a, **k: ("created", 1))
    monkeypatch.setattr(seed_topics, "save_flashcard",
                        lambda entry, added_by_user_id=None:
                        (saved.append(entry["word"]), 1)[1])

    def flaky(word, topic=None, translator=None, explanatory_dictionary=None):
        if word in ("delegate", "mentor"):
            raise ValueError(f"No translations found for '{word}'")
        return [{"word": word, "pos": "noun", "topic": topic}]

    monkeypatch.setattr(seed_topics, "lookup_word", flaky)

    counts = seed_topics.run(seed_topics.chosen_topics("Work and careers"),
                             None, None, "google", "oxford", pause=0,
                             out=io.StringIO())

    assert len(saved) == 18, "the other eighteen were saved"
    assert [w for w, _ in counts.failed] == ["delegate", "mentor"]
    assert counts.added == 18


def test_failed_words_are_named_in_the_summary(monkeypatch, capsys):
    """Named, not counted: these are the words to fix by hand, and a number does
    not tell you which."""
    monkeypatch.setattr(seed_topics, "place_topic", lambda *a, **k: ("created", 1))
    monkeypatch.setattr(seed_topics, "save_flashcard", lambda *a, **k: 1)

    def flaky(word, topic=None, translator=None, explanatory_dictionary=None):
        if word == "headhunt":
            raise ValueError("nothing came back")
        return [{"word": word, "pos": "noun", "topic": topic}]

    monkeypatch.setattr(seed_topics, "lookup_word", flaky)

    seed_topics.main(["--topic", "Work and careers", "--pause", "0"])

    out = capsys.readouterr().out
    assert "could not be built:" in out
    assert "- headhunt: ValueError: nothing came back" in out


def test_a_failed_save_does_not_end_the_run_either(monkeypatch):
    """A dead row, not a dead run — a card whose text upsets the column for some
    reason should cost that word and nothing else."""
    monkeypatch.setattr(seed_topics, "place_topic", lambda *a, **k: ("created", 1))
    monkeypatch.setattr(
        seed_topics, "lookup_word",
        lambda word, topic=None, **k: [{"word": word, "pos": "noun",
                                        "topic": topic}])

    def flaky_save(entry, added_by_user_id=None):
        if entry["word"] == "delegate":
            raise RuntimeError("column too short")
        return 1

    monkeypatch.setattr(seed_topics, "save_flashcard", flaky_save)

    counts = seed_topics.run(seed_topics.chosen_topics("Work and careers"),
                             None, None, "google", "oxford", pause=0,
                             out=io.StringIO())

    assert counts.added == 19
    assert [w for w, _ in counts.failed] == ["delegate"]


# --- re-running -----------------------------------------------------------


def test_a_word_already_in_the_database_counts_as_present_not_added(monkeypatch):
    """`save_flashcard()` returns None for a duplicate (#101). That is the whole
    of the script's idempotency, and it is what makes an interrupted run
    finishable by running it again."""
    monkeypatch.setattr(seed_topics, "place_topic", lambda *a, **k: ("unchanged", 1))
    monkeypatch.setattr(
        seed_topics, "lookup_word",
        lambda word, topic=None, **k: [{"word": word, "pos": "noun",
                                        "topic": topic}])
    monkeypatch.setattr(seed_topics, "save_flashcard", lambda *a, **k: None)

    counts = seed_topics.run(seed_topics.chosen_topics("Work and careers"),
                             None, None, "google", "oxford", pause=0,
                             out=io.StringIO())

    assert (counts.added, counts.present) == (0, 20)
    assert counts.failed == []


def test_a_word_is_present_only_when_none_of_its_cards_were_written(monkeypatch):
    """Counting per card would make the totals disagree with the per-word lines
    above them, which is what someone reads to follow progress."""
    monkeypatch.setattr(seed_topics, "place_topic", lambda *a, **k: ("unchanged", 1))
    monkeypatch.setattr(
        seed_topics, "lookup_word",
        lambda word, topic=None, **k: [{"word": word, "pos": "noun", "topic": topic},
                                       {"word": word, "pos": "verb", "topic": topic}])
    # The noun is a duplicate, the verb is new: one card written, so the word
    # is not "already present".
    monkeypatch.setattr(seed_topics, "save_flashcard",
                        lambda entry, added_by_user_id=None:
                        None if entry["pos"] == "noun" else 1)

    counts = seed_topics.run(seed_topics.chosen_topics("Work and careers"),
                             None, None, "google", "oxford", pause=0,
                             out=io.StringIO())

    assert (counts.added, counts.present) == (20, 0)


# --- logging --------------------------------------------------------------


def test_every_card_is_logged_with_the_seed_source(monkeypatch, action_logs):
    """CLAUDE.md's rule is that a new save path logs. There is no request here,
    so it logs beside the write like `set_user_blocked()` does — and `cards.log`
    has to be able to answer "where did these 400 cards come from?"."""
    monkeypatch.setattr(seed_topics, "place_topic", lambda *a, **k: ("created", 1))
    monkeypatch.setattr(
        seed_topics, "lookup_word",
        lambda word, topic=None, **k: [{"word": word, "pos": "noun",
                                        "topic": topic}])
    # First word saves, the rest are duplicates: both log lines get exercised.
    seen = []
    monkeypatch.setattr(
        seed_topics, "save_flashcard",
        lambda entry, added_by_user_id=None:
        1 if not seen and not seen.append(entry) else None)

    seed_topics.run(seed_topics.chosen_topics("Work and careers"), None,
                    "seven@example.com", "google", "oxford", pause=0,
                    out=io.StringIO())

    lines = (action_logs / "cards.log").read_text(encoding="utf-8").splitlines()
    creates = [ln for ln in lines if " CREATE " in ln]
    skips = [ln for ln in lines if " SKIP " in ln]
    assert len(creates) == 1 and len(skips) == 19
    for line in creates + skips:
        assert "source='seed script'" in line
        assert "user=seven@example.com" in line


def test_an_unowned_run_logs_the_user_as_anonymous(monkeypatch, action_logs):
    monkeypatch.setattr(seed_topics, "place_topic", lambda *a, **k: ("created", 1))
    monkeypatch.setattr(
        seed_topics, "lookup_word",
        lambda word, topic=None, **k: [{"word": word, "pos": "noun",
                                        "topic": topic}])
    monkeypatch.setattr(seed_topics, "save_flashcard", lambda *a, **k: 1)

    seed_topics.run(seed_topics.chosen_topics("Work and careers"), None, None,
                    "google", "oxford", pause=0, out=io.StringIO())

    lines = (action_logs / "cards.log").read_text(encoding="utf-8")
    assert "user=anonymous" in lines


# --- output ---------------------------------------------------------------


def test_the_output_is_ascii(monkeypatch):
    """A Windows console is cp1252 and raises on a Ukrainian translation, which
    would end a run that was saving cards perfectly well. Topic names and words
    are ASCII and translations are never printed — the section name, which is
    not ASCII, must not be either."""
    monkeypatch.setattr(seed_topics, "place_topic", lambda *a, **k: ("created", 1))
    monkeypatch.setattr(
        seed_topics, "lookup_word",
        lambda word, topic=None, **k: [{"word": word, "pos": "noun",
                                        "topic": topic,
                                        "translation_ukr": "переклад"}])
    monkeypatch.setattr(seed_topics, "save_flashcard", lambda *a, **k: 1)

    out = io.StringIO()
    seed_topics.run(seed_topics.chosen_topics(None), None, None, "google",
                    "oxford", pause=0, out=out)

    text = out.getvalue()
    text.encode("ascii")        # raises if anything slipped through
    assert "Work and careers" in text
