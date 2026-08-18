"""Backfilling examples onto pre-#225 cards (kuantorflow#314).

The script itself is a one-off repair, but two of its decisions are the kind
that go wrong quietly, so they are pinned here rather than discovered on 549
cards:

* examples are matched to a card's part of speech through #228's synonym map,
  because the translator and the dictionary name the same thing differently;
* the write carries **one field** and `admin=True`, because the seeded deck is
  unowned and `update_flashcard()` matches ownership with `=`, which never
  matches NULL.

Nothing here touches the network or a database — `_fetch_oxford_entry` and
`update_flashcard` are both replaced.
"""

import sys

import pytest

from maintenance import backfill_examples as backfill

CARDS = [
    {"id": 1, "word": "delegate", "pos": "verb", "topic": "Work"},
    {"id": 2, "word": "delegate", "pos": "noun", "topic": "Work"},
    {"id": 3, "word": "delegate", "pos": "adjective", "topic": "Work"},
]

OXFORD = ({"verb": ["to delegate a task"], "noun": ["Congress delegates voted."]},)


@pytest.fixture()
def oxford(monkeypatch):
    """Oxford answering with examples for verb and noun, nothing else."""
    import parsers

    calls = []

    def fake(word):
        calls.append(word)
        return ({"verb": ["def"], "noun": ["def"]},
                {"verb": ["to delegate a task"],
                 "noun": ["Congress delegates voted."]})

    monkeypatch.setattr(parsers, "_fetch_oxford_entry", fake)
    return calls


def test_examples_are_matched_to_each_cards_part_of_speech(oxford):
    found = backfill.examples_for("delegate", CARDS, pause=0)
    assert found == {1: ["to delegate a task"],
                     2: ["Congress delegates voted."]}


def test_one_request_serves_every_card_of_a_word(oxford):
    """`delegate` is three cards and one page — per-card lookups would triple
    the requests and the run time for nothing."""
    backfill.examples_for("delegate", CARDS, pause=0)
    assert oxford == ["delegate"]


def test_a_part_of_speech_oxford_cannot_illustrate_is_skipped(oxford):
    """Not an error: the card keeps its translations and simply carries no
    examples, exactly as #228 leaves cards without explanations."""
    found = backfill.examples_for("delegate", CARDS, pause=0)
    assert 3 not in found


def test_a_synonym_still_matches(monkeypatch):
    """#228's map both ways: a card the translator called `modal verb` takes
    the text Oxford files under `auxiliary verb`."""
    import parsers

    monkeypatch.setattr(parsers, "_fetch_oxford_entry",
                        lambda word: ({}, {"auxiliary verb": ["You must go."]}))
    found = backfill.examples_for(
        "must", [{"id": 9, "word": "must", "pos": "modal verb", "topic": "T"}],
        pause=0)
    assert found == {9: ["You must go."]}


def test_a_failed_lookup_costs_that_word_and_not_the_run(monkeypatch, capsys):
    import parsers

    def boom(word):
        raise RuntimeError("Oxford is away")

    monkeypatch.setattr(parsers, "_fetch_oxford_entry", boom)
    assert backfill.examples_for("delegate", CARDS, pause=0) == {}
    assert "lookup failed" in capsys.readouterr().out


# --- the write --------------------------------------------------------------

def test_the_write_carries_one_field_and_admin(monkeypatch):
    """Two things at once, and both matter: widening the entry would let this
    script lose text it never read, and without `admin` every unowned card
    comes back denied."""
    seen = {}

    def fake_update(card_id, entry, owner_id=None, admin=False):
        seen.update(card_id=card_id, entry=entry, admin=admin)
        return "updated", ["examples_en"]

    import utils
    monkeypatch.setattr(utils, "update_flashcard", fake_update)
    monkeypatch.setattr("applog.card_edited", lambda *a, **k: None)

    assert backfill.write(7, ["A sentence."]) == "updated"
    assert seen["entry"] == {"examples_en": ["A sentence."]}
    assert seen["admin"] is True


def test_a_refused_write_is_not_logged(monkeypatch):
    """`cards.log` counts events rather than attempts — #176's own rule."""
    import utils
    monkeypatch.setattr(utils, "update_flashcard",
                        lambda *a, **k: ("denied", None))
    logged = []
    monkeypatch.setattr("applog.card_edited",
                        lambda *a, **k: logged.append(k))
    assert backfill.write(7, ["A sentence."]) == "denied"
    assert logged == []
