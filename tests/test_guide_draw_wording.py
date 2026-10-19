"""The guide says what the weighted draw does, and no more (kuantorflow#640).

`recall.draw_weight()` makes a word not due yet `DUE_WEIGHT / NOT_DUE_WEIGHT`
times less likely to be dealt -- never excluded -- and `games.sample()` shuffles
the cards it picks, so due words are likelier, not first. The guide used to
title the section "Words that are due come up first" and say they "are dealt
first", and Mykola, who answers from the guide, repeated it. Only Review deals
strictly from today's due words, and its own section says so.

The ratio the guide states is derived from the weights here, so changing them
without changing the guide fails this test.
"""

import re
from pathlib import Path

from conftest import KUANTORFLOW_PATH

import recall

GUIDE = Path(KUANTORFLOW_PATH) / "docs" / "user-guide.md"
NUMBER_WORDS = {2: "twice", 3: "three", 4: "four", 5: "five", 6: "six",
                7: "seven", 8: "eight", 9: "nine", 10: "ten"}


def _section():
    """(heading, body) of the section that explains the weighted draw."""
    text = GUIDE.read_text(encoding="utf-8")
    at = text.index("the day it is next worth asking")
    start = text.rindex("\n### ", 0, at) + 1
    end = text.index("\n### ", at)
    heading, _, body = text[start:end].partition("\n")
    return heading.lstrip("# ").strip(), body


def test_the_heading_promises_no_order():
    heading, _ = _section()

    assert "first" not in heading.lower(), heading


def test_the_body_does_not_say_dealt_first():
    _, body = _section()

    assert "dealt first" not in body and "come up first" not in body


def test_the_ratio_it_states_is_the_one_the_weights_give():
    ratio = round(recall.DUE_WEIGHT / recall.NOT_DUE_WEIGHT)
    assert recall.UNSEEN_WEIGHT == recall.DUE_WEIGHT, "the guide treats new and due words alike"
    _, body = _section()

    assert re.search(rf"\b{NUMBER_WORDS[ratio]} times less often\b", body), \
        f"the guide should say a known word comes up {NUMBER_WORDS[ratio]} times less often"


def test_it_says_a_known_word_is_never_left_out():
    _, body = _section()

    assert "never left out" in body
