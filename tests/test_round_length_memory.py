"""The picker reopens on the round length that was last played (kuantorflow#233).

The round length is remembered beside the topic selection and for the same
reason: it is a per-round preference rather than a per-account setting, so it
lives in the session and not in `settings_store`.

**The selection half was tested and this half was not**, which is how the
following survived: `/quiz` wrote the length back, and no game did. A number
typed into a game's picker was read once and then forgotten, so the box
reopened on whatever the last quiz had stored — and a learner who never took
the quiz could not change it at all. The reported symptom was a box that
"always shows 23".

Everything here is a round trip through the app, because the bug was in *who
writes*, not in the pure helpers, and every pure test of those passed
throughout.
"""

import re

import pytest

import games


CARDS = ([{"id": i, "word": w, "topic": "Work", "translation_ukr": "x"}
          for i, w in enumerate(["delegate", "resign", "burnout", "commute"], 1)]
         + [{"id": i, "word": w, "topic": "Law", "translation_ukr": "y"}
            for i, w in enumerate(["verdict", "parole", "arson"], 10)])

BOTH = "topic=Work&topic=Law"


@pytest.fixture()
def deck(stub_deck):
    return stub_deck(cards=CARDS, topics=[("Work", 4), ("Law", 3)])


@pytest.fixture()
def with_key(monkeypatch):
    """#237's activity is unreachable without a key -- its picker 404s and its
    tile does not render -- so the two tests about *its* box need one."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


def _box(client, game="scrambled"):
    """The number the picker's Words box opens on."""
    body = client.get(f"/games/{game}").get_data(as_text=True)
    return int(re.search(r'name="words"[^>]*value="(\d+)"', body).group(1))


# --- the default ----------------------------------------------------------


def test_a_fresh_session_opens_on_the_declared_default(client, deck):
    assert _box(client) == games.QUIZ_WORDS.default == 10


def test_the_reader_opens_on_its_own_default(client, deck, with_key):
    """#237's box counts words of prose, not questions, so it has its own key
    and its own bounds — and one must not overwrite the other."""
    body = client.get("/games/read_a_text").get_data(as_text=True)
    shown = int(re.search(r'name="words"[^>]*value="(\d+)"', body).group(1))
    assert shown == games.GENERATED_WORDS.default == 150


# --- playing a round remembers its length ---------------------------------


def test_playing_a_game_remembers_the_length(client, deck):
    """The bug. Every game read the remembered value and none wrote it back,
    so a number typed here vanished the moment the round was dealt."""
    client.get(f"/games/scrambled/play?{BOTH}&words=7")
    assert _box(client) == 7


def test_every_game_remembers_it_not_just_one(client, deck):
    """Written once in `game_play` rather than per round, so a game cannot land
    without it — which is exactly how this was missed the first time."""
    for game, length in (("multiple_choice", 6), ("odd_one_out", 8),
                         ("listen_and_type", 9), ("real_or_fake", 12)):
        client.get(f"/games/{game}/play?{BOTH}&words={length}")
        assert _box(client) == length, game


def test_the_quiz_still_remembers_it(client, deck):
    """It always did; this must not have been broken on the way past."""
    client.get(f"/quiz?{BOTH}&words=23")
    assert _box(client) == 23


def test_a_game_played_after_a_quiz_wins(client, deck):
    """The reported symptom, in order: a quiz stored 23, and no game could
    shift it however many times the learner typed something else."""
    client.get(f"/quiz?{BOTH}&words=23")
    assert _box(client) == 23
    client.get(f"/games/scrambled/play?{BOTH}&words=10")
    assert _box(client) == 10


def test_a_round_with_no_length_keeps_the_remembered_one(client, deck):
    """A bare link to a round — the kind the topic page builds — must not
    reset the box to the default."""
    client.get(f"/games/scrambled/play?{BOTH}&words=7")
    client.get(f"/games/scrambled/play?{BOTH}")
    assert _box(client) == 7


def test_an_out_of_range_length_is_clamped_before_it_is_remembered(client, deck):
    """`word_count()` clamps rather than rejects, because the value arrives
    from a URL anybody can edit — and the clamped value is what sticks."""
    client.get(f"/games/scrambled/play?{BOTH}&words=9999")
    assert _box(client) == games.QUIZ_WORDS.high
    client.get(f"/games/scrambled/play?{BOTH}&words=0")
    assert _box(client) == games.QUIZ_WORDS.low


def test_nonsense_leaves_the_remembered_length_alone(client, deck):
    client.get(f"/games/scrambled/play?{BOTH}&words=7")
    client.get(f"/games/scrambled/play?{BOTH}&words=abc")
    assert _box(client) == 7


# --- the two boxes are separate -------------------------------------------


def test_a_game_does_not_move_the_readers_number(client, deck, with_key):
    """Different units — questions asked against words of prose — so they are
    different keys. A game setting 7 must not leave #237 offering to write a
    seven-word passage."""
    client.get(f"/games/scrambled/play?{BOTH}&words=7")
    body = client.get("/games/read_a_text").get_data(as_text=True)
    shown = int(re.search(r'name="words"[^>]*value="(\d+)"', body).group(1))
    assert shown == games.GENERATED_WORDS.default


def test_the_length_is_remembered_across_games(client, deck):
    """One box, one memory: it is a preference about how long a round should
    be, not about which game asked."""
    client.get(f"/games/scrambled/play?{BOTH}&words=11")
    assert _box(client, "multiple_choice") == 11
    assert _box(client, "odd_one_out") == 11
