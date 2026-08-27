"""Repairing the space before punctuation on saved cards (kuantorflow#359).

The parser stopped producing `alive .` on the day #359 merged; the rows saved
before it keep it, and nothing in the app reaches them — #101 refuses the
duplicate a fresh lookup would be, and `fill_missing_fields()` only fills
columns that are empty. `maintenance/tidy_punctuation.py` is the repair.

Three of its decisions are the kind that go wrong quietly, so they are pinned
here rather than discovered on somebody's deck:

* the repair is the app's own `parsers._readable()`, imported rather than
  copied, so the tidy and the parser cannot drift apart;
* only the fields it actually changes go into the UPDATE, because
  `update_flashcard()` reads a missing key as "leave this alone" — a wider
  entry would let a repair script lose text it never read;
* its output is safe on a cp1252 console. That is not cosmetic: printing a
  Ukrainian example raises `UnicodeEncodeError`, and under `--apply` that ends
  a run that was writing correctly, halfway, with no summary.

Nothing here touches the network or a database.
"""

import io
import sys

import pytest

from maintenance import tidy_punctuation as tidy


CARD = {
    "id": 4, "word": "alive", "pos": "adjective", "topic": "Health",
    "explanation_en": "living , not dead",
    "translation_ukr": "живий",
    "translation_rus": None,
    "examples_en": '["Are your grandparents still alive ?", "Keep it alive."]',
    "examples_ukr": None,
    "examples_rus": None,
}


# --- what it decides to change ---------------------------------------------

def test_it_repairs_text_and_lists_alike():
    found = tidy.repairs(dict(CARD))

    assert found == {
        "explanation_en": "living, not dead",
        "examples_en": ["Are your grandparents still alive?", "Keep it alive."],
    }


def test_a_field_it_would_not_change_is_left_out():
    """Not written back unchanged: the UPDATE carries only the repair, which
    is what stops this script being able to lose anything."""
    found = tidy.repairs(dict(CARD))

    assert "translation_ukr" not in found, "already tidy"
    assert "translation_rus" not in found, "empty"
    assert "examples_ukr" not in found and "examples_rus" not in found


def test_a_clean_card_needs_no_repair():
    clean = dict(CARD, explanation_en="living, not dead",
                 examples_en='["Keep it alive."]')

    assert tidy.repairs(clean) == {}


def test_the_headword_is_never_rewritten():
    """`word` and `pos` are out of scope by construction, not by luck.

    Renaming a card is a different act with #101's duplicate rule attached, so
    a script that repairs punctuation must not be able to do it by accident.
    """
    odd = dict(CARD, word="alive .", pos="adjective ")

    assert set(tidy.repairs(odd)) <= set(tidy.TEXT_FIELDS + tidy.LIST_FIELDS)
    assert "word" not in tidy.TEXT_FIELDS + tidy.LIST_FIELDS
    assert "pos" not in tidy.TEXT_FIELDS + tidy.LIST_FIELDS


def test_it_uses_the_apps_own_normaliser(monkeypatch):
    """Imported, not reimplemented — the whole point of kuantorflow#359 being
    one function. Proved by moving the app's and watching the script follow."""
    import parsers

    monkeypatch.setattr(parsers, "_readable", lambda text: "TIDIED")

    assert tidy.repairs(dict(CARD))["explanation_en"] == "TIDIED"


# --- the write --------------------------------------------------------------

def test_the_write_carries_only_the_repairs_and_admin(monkeypatch):
    """Without `admin` every unowned card — the whole seeded deck — comes back
    denied, because `update_flashcard()` matches ownership with `=`."""
    seen = {}

    def fake_update(card_id, entry, owner_id=None, admin=False):
        seen.update(card_id=card_id, entry=entry, admin=admin)
        return "updated", ["explanation_en"]

    import utils
    monkeypatch.setattr(utils, "update_flashcard", fake_update)
    monkeypatch.setattr("applog.card_edited", lambda *a, **k: None)

    assert tidy.write(4, {"explanation_en": "living, not dead"}) == "updated"
    assert seen == {"card_id": 4, "admin": True,
                    "entry": {"explanation_en": "living, not dead"}}


def test_a_refused_write_is_not_logged(monkeypatch):
    """`cards.log` counts events rather than attempts — #176's own rule."""
    import utils
    monkeypatch.setattr(utils, "update_flashcard",
                        lambda *a, **k: ("denied", None))
    logged = []
    monkeypatch.setattr("applog.card_edited",
                        lambda *a, **k: logged.append(k))

    assert tidy.write(4, {"explanation_en": "x"}) == "denied"
    assert logged == []


# --- the run ----------------------------------------------------------------

@pytest.fixture()
def deck(monkeypatch):
    """One repairable card and one clean one, with the writes recorded."""
    written = []
    monkeypatch.setattr(tidy, "cards",
                        lambda topic=None, section=None: [
                            dict(CARD),
                            dict(CARD, id=5, word="scholar",
                                 explanation_en="a person who studies",
                                 examples_en='["A classical scholar."]'),
                        ])
    monkeypatch.setattr(tidy, "write",
                        lambda card_id, fields: written.append((card_id, fields))
                        or "updated")
    return written


def test_a_dry_run_writes_nothing(deck, capsys):
    assert tidy.main([]) == 0

    assert deck == []
    out = capsys.readouterr().out
    assert "1 of 2 card(s) need tidying" in out
    assert "dry run" in out and "re-run with --apply" in out


def test_apply_writes_only_the_card_that_needs_it(deck, capsys):
    assert tidy.main(["--apply"]) == 0

    assert [card_id for card_id, _ in deck] == [4]
    assert set(deck[0][1]) == {"explanation_en", "examples_en"}
    assert "1 card(s) tidied" in capsys.readouterr().out


def test_a_refusal_is_reported_and_fails_the_run(monkeypatch, deck, capsys):
    monkeypatch.setattr(tidy, "write", lambda card_id, fields: "denied")

    assert tidy.main(["--apply"]) == 1
    assert "denied" in capsys.readouterr().out


def test_nothing_to_do_says_so(monkeypatch, capsys):
    monkeypatch.setattr(tidy, "cards", lambda topic=None, section=None: [
        dict(CARD, explanation_en="living, not dead",
             examples_en='["Keep it alive."]')])

    assert tidy.main([]) == 0
    assert "nothing to tidy" in capsys.readouterr().out


# --- the console ------------------------------------------------------------

def test_output_survives_a_console_that_cannot_spell_cyrillic(monkeypatch):
    """The failure that would have ended a real `--apply` halfway.

    A local Windows console is cp1252, the deck holds Ukrainian and Russian
    examples, and `print()` raises rather than mangling. Escaped output keeps
    the run alive and the line readable enough to say which card it was.
    """
    monkeypatch.setattr(sys, "stdout",
                        io.TextIOWrapper(io.BytesIO(), encoding="cp1252"))

    tidy.say("  ~ живий (noun): 'він живий .' -> 'він живий.'")

    sys.stdout.seek(0)
    written = sys.stdout.buffer.getvalue().decode("cp1252")
    assert "\\u0436" in written, "escaped rather than raising"


def test_the_sample_shows_where_the_change_is():
    """A window around the first difference, not a fixed slice of the string.

    The change can sit anywhere in a sentence, and a fixed window that misses
    it prints two identical halves — a line claiming a repair of nothing,
    which is exactly how the first version of this read. So the assertion is
    that the two halves *differ*, whatever the sample chooses to show.
    """
    before = ("Carbon is found in all living things, existing in its pure state "
              "as diamond and graphite ; used when referring to the gas carbon "
              "dioxide and its effect on the climate")
    after = before.replace("graphite ;", "graphite;")
    assert before.index("graphite ;") > 64, "the change is past any head slice"

    left, _, right = tidy.sample(before, after).partition(" -> ")

    assert left and right and left != right, "a sample that shows no change"
    assert "graphite ;" in left and "graphite;" in right
    assert len(left) < len(before), "and it is a window, not the whole string"
