"""Graded rounds write the learner's answer log (kuantorflow#338, phase 1).

The write lives in one place, `rounds._graded_answers()`, which is the point of
#416: the six rounds that grade an answer against a card reach it, and nothing
else can. So what this file pins is the *set* -- every graded game records,
with its own slug, and every other activity does not -- plus the three rules
about **who**: a signed-in learner is recorded, an anonymous visitor never is,
and a blocked account still is.

And one rule about failure: the log is history, and a history table that cannot
be written must never cost the learner the results page they just earned.

The SQL itself -- one shared instant per round, CASCADE on the account, SET
NULL on the card -- is in test_recall_answers_db.py, against a real MySQL.
"""

import logging

import pytest
from werkzeug.datastructures import MultiDict

import games
from conftest import TEST_USER_ID
from test_graded_rounds import CARDS, GRADED, UNATTRIBUTABLE

# The slug each GRADED round must record under, in GRADED's order. The slug is
# what #479 will read to weight games differently, so a round recording under
# the wrong one is a real fault rather than a label.
GRADED_SLUGS = ["scrambled", "multiple_choice", "listen_and_type", "spell_it",
                "rebuild_the_sentence", "quiz"]

# Activities that must never record, and why -- each is a claim #338 makes.
NEVER_RECORDED = {
    "odd_one_out": "posts question indexes, so there is no card to credit",
    "real_or_fake": "asks about invented words with no row behind them",
    "fill_the_gap": "is self-marked, and the schedule runs on checked answers",
    "read_a_text": "asks no questions at all",
}


@pytest.fixture()
def deck(stub_deck):
    return stub_deck(cards=CARDS)


@pytest.fixture()
def recorded(app_module, monkeypatch):
    """Every `utils.record_answers()` call, instead of an INSERT."""
    calls = []

    def fake(user_id, game, answers):
        calls.append((user_id, game,
                      [(card["id"], correct) for card, correct in answers]))
        return len(answers)

    monkeypatch.setattr("utils.record_answers", fake)
    return calls


# --- the set of writers ------------------------------------------------------

def test_every_activity_is_either_a_writer_or_excluded_for_a_reason():
    """A new activity has to be put on one side of the line. Without this, a
    tenth game that grades somewhere of its own would simply not record, and
    every other test here would stay green."""
    assert len(GRADED_SLUGS) == len(GRADED)
    classified = set(GRADED_SLUGS) | set(NEVER_RECORDED)

    assert classified == set(games.ACTIVITIES), (
        "unclassified: %s" % sorted(set(games.ACTIVITIES) ^ classified))


@pytest.mark.parametrize("name,url,data,slug",
                         [row + (slug,) for row, slug in zip(GRADED, GRADED_SLUGS)],
                         ids=[r[0] for r in GRADED])
def test_a_graded_round_records_each_answer_under_its_game(
        user_client, deck, recorded, name, url, data, slug):
    body = user_client.post(url, data=data).get_data(as_text=True)

    assert "Score: 1 / 1" in body, f"{name} did not actually grade a round"
    assert recorded == [(TEST_USER_ID, slug, [(1, True)])]


def test_a_wrong_answer_is_recorded_as_wrong(user_client, deck, recorded):
    """The rows are the evidence the schedule will run on, so a miss matters
    exactly as much as a hit."""
    user_client.post("/games/spell_it/play?topic=Work",
                     data={"answer_1": "delegate", "answer_2": "resing"})

    assert recorded == [(TEST_USER_ID, "spell_it", [(1, True), (2, False)])]


@pytest.mark.parametrize("name,url,data", UNATTRIBUTABLE,
                         ids=[r[0] for r in UNATTRIBUTABLE])
def test_a_round_with_no_card_behind_it_records_nothing(
        user_client, deck, recorded, name, url, data):
    """Signed in, so the only reason for silence is the round itself. The
    score is read first so this cannot pass by not playing."""
    body = user_client.post(url, data=data).get_data(as_text=True)

    assert "Score: 1 / 1" in body, f"{name} did not actually grade a round"
    assert recorded == []


def test_fill_the_gap_records_nothing(user_client, deck, recorded):
    """Self-marked: the learner flips the card and ticks *I remember it*, with
    nothing compared. Fine for #337's next few minutes, wrong as history."""
    response = user_client.get("/games/fill_the_gap/play?topic=Work")

    assert response.status_code == 200
    assert recorded == []


# --- who ---------------------------------------------------------------------

def test_an_anonymous_round_records_nothing(client, deck, recorded):
    """No account, no `user_id` to key a row on -- and the round is still
    graded, so this is the write being skipped rather than the round failing."""
    body = client.post("/games/spell_it/play?topic=Work",
                       data={"answer_1": "delegate"}).get_data(as_text=True)

    assert "Score: 1 / 1" in body
    assert recorded == []


def test_a_blocked_account_is_still_recorded(user_client, deck, recorded,
                                            block_state):
    """#126 drew its line at writing *shared* content. This is private data
    about the learner, and skipping it would only make their schedule wrong on
    the day they are unblocked."""
    block_state.block()

    user_client.post("/games/spell_it/play?topic=Work",
                     data={"answer_1": "delegate"})

    assert recorded == [(TEST_USER_ID, "spell_it", [(1, True)])]


# --- failure -----------------------------------------------------------------

def test_a_failed_write_still_shows_the_results(user_client, deck, monkeypatch,
                                               caplog):
    """The learner has just answered a round. A history table that cannot be
    written costs the history row, and is logged so an empty table is noticed
    -- `confirmed_words` once sat empty for a week because nobody looked."""
    def broken(user_id, game, answers):
        raise RuntimeError("the database is not answering")

    monkeypatch.setattr("utils.record_answers", broken)

    with caplog.at_level(logging.ERROR):
        response = user_client.post("/games/spell_it/play?topic=Work",
                                    data={"answer_1": "delegate"})

    assert response.status_code == 200
    assert "Score: 1 / 1" in response.get_data(as_text=True)
    assert "for recall" in caplog.text


# --- the writer itself, offline ----------------------------------------------

def test_nothing_to_write_opens_no_connection(real_utils, monkeypatch):
    """An anonymous call or an empty round answers 0 without touching the
    database -- so the guard in the round is not the only thing between an
    anonymous visitor and a connection."""
    def no_database():
        raise AssertionError("opened a connection with nothing to write")

    monkeypatch.setattr(real_utils, "get_db_connection", no_database)
    card = {"id": 1, "word": "delegate", "pos": "verb"}

    assert real_utils.record_answers(None, "quiz", [(card, True)]) == 0
    assert real_utils.record_answers(TEST_USER_ID, "quiz", []) == 0


def test_one_round_is_one_statement(real_utils, monkeypatch):
    """One INSERT for the whole round is what gives its rows one shared
    `UTC_TIMESTAMP()` -- three statements would be three instants, and a round
    could no longer be read back out of the log."""
    from conftest import fake_card_db

    cursor, conn = fake_card_db(monkeypatch)
    answers = [({"id": 1, "word": "delegate", "pos": "verb"}, True),
               ({"id": 2, "word": "resign", "pos": "verb"}, False)]

    assert real_utils.record_answers(TEST_USER_ID, "quiz", answers) == 2

    inserts = [q for q, _ in cursor.queries if q.startswith("INSERT")]
    assert len(inserts) == 1
    assert inserts[0].count("UTC_TIMESTAMP()") == 2
    assert conn.committed
    _query, params = cursor.queries[0]
    assert params == [TEST_USER_ID, 1, "delegate", "verb", "quiz", 1,
                      TEST_USER_ID, 2, "resign", "verb", "quiz", 0]
