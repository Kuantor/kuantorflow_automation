"""Graded rounds write the learner's answer log (kuantorflow#338, phase 1).

The write lives in one place, `rounds._graded_answers()`, which is the point of
#416: the six rounds that grade an answer against a card reach it, and nothing
else can. So what this file pins is the *set* -- every graded game records,
with its own slug; *Fill the gap* records the learner's own ticks since
kuantorflow#484, declared `self_marked` so #479 can weigh them lower; and every
other activity does not -- plus the three rules about **who**: a signed-in learner is recorded, an anonymous visitor never is,
and a blocked account still is.

And one rule about failure: the log is history, and a history table that cannot
be written must never cost the learner the results page they just earned.

The SQL itself -- one shared instant per round, CASCADE on the account, SET
NULL on the card -- is in test_recall_answers_db.py, against a real MySQL.
"""

import logging
import re

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

# Activities that record the learner's own marks rather than a checked answer
# (kuantorflow#484). They write the same rows; `Activity.self_marked` is what
# lets #479's schedule weigh them lower.
SELF_MARKED = {"fill_the_gap"}

# Activities that must never record, and why -- each is a claim #338 makes.
NEVER_RECORDED = {
    "odd_one_out": "posts question indexes, so there is no card to credit",
    "real_or_fake": "asks about invented words with no row behind them",
    "read_a_text": "asks no questions at all",
}

GAP_CARDS = [dict(card, examples_en=[f"She had to {card['word']} the task."])
             for card in CARDS]


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
    classified = set(GRADED_SLUGS) | SELF_MARKED | set(NEVER_RECORDED)

    assert classified == set(games.ACTIVITIES), (
        "unclassified: %s" % sorted(set(games.ACTIVITIES) ^ classified))


def test_the_self_marked_declaration_is_exactly_the_self_marked_games():
    """#479 reads `Activity.self_marked` to weigh a tick below a checked
    answer. A checked game carrying it would have its real answers discounted;
    a self-marked game without it would have ticks counted as proof."""
    declared = {slug for slug, activity in games.ACTIVITIES.items()
                if activity.self_marked}

    assert declared == SELF_MARKED


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


# --- Fill the gap: the learner's own marks (kuantorflow#484) ------------------

def test_dealing_fill_the_gap_records_nothing(user_client, stub_deck, recorded):
    """The deal is not an answer. Only *Finish* posts anything."""
    stub_deck(cards=GAP_CARDS)
    response = user_client.get("/games/fill_the_gap/play?topic=Work")

    assert response.status_code == 200
    assert recorded == []


def test_finishing_fill_the_gap_records_each_card_turned_over(
        user_client, stub_deck, recorded):
    """A tick is `remembered`; a card turned over and left unticked posts an
    empty value and is recorded as not remembered. Cards never turned over are
    not posted at all -- the page's job -- so only 1 and 3 come back."""
    stub_deck(cards=GAP_CARDS)
    response = user_client.post("/games/fill_the_gap/play?topic=Work",
                                data={"answer_1": "remembered", "answer_3": ""})

    assert response.status_code == 204
    assert recorded == [(TEST_USER_ID, "fill_the_gap", [(1, True), (3, False)])]


def test_only_the_exact_mark_counts_as_remembered(user_client, stub_deck,
                                                 recorded):
    """The judge is an exact comparison, so a hand-built POST cannot turn a
    card into a pass by sending anything truthy."""
    stub_deck(cards=GAP_CARDS)
    user_client.post("/games/fill_the_gap/play?topic=Work",
                     data={"answer_1": "yes", "answer_2": "on"})

    assert recorded == [(TEST_USER_ID, "fill_the_gap", [(1, False), (2, False)])]


def test_a_card_outside_the_visible_deck_is_not_recorded(user_client,
                                                        stub_deck, recorded):
    """The ids come from the page, so they are read back against this
    learner's deck -- the same `games.asked()` rule every round uses."""
    stub_deck(cards=GAP_CARDS)
    user_client.post("/games/fill_the_gap/play?topic=Work",
                     data={"answer_999": "remembered", "answer_2": "remembered"})

    assert recorded == [(TEST_USER_ID, "fill_the_gap", [(2, True)])]


def test_an_anonymous_finish_records_nothing(client, stub_deck, recorded):
    stub_deck(cards=GAP_CARDS)
    response = client.post("/games/fill_the_gap/play?topic=Work",
                           data={"answer_1": "remembered"})

    assert response.status_code == 204
    assert recorded == []


def test_the_round_page_carries_what_the_post_needs(user_client, stub_deck):
    """The browser half cannot run here, so its inputs are pinned: every tick
    box names its card, and the value it posts is the one the server compares
    against -- rendered from `rounds.GAP_REMEMBERED` rather than written
    twice. The flip tracking itself was verified in a browser."""
    import rounds
    stub_deck(cards=GAP_CARDS)
    body = user_client.get("/games/fill_the_gap/play?topic=Work").get_data(
        as_text=True)

    ids = re.findall(r'class="gap-remember-box" data-card-id="(\d+)"', body)
    assert sorted(map(int, ids)) == [card["id"] for card in GAP_CARDS]
    assert f'box.checked ? "{rounds.GAP_REMEMBERED}" : ""' in body


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


# --- then the schedule (kuantorflow#479) ---------------------------------------

@pytest.fixture()
def refreshed(app_module, monkeypatch):
    """Every `utils.refresh_schedule()` call, instead of a replay and upsert."""
    calls = []
    monkeypatch.setattr("utils.refresh_schedule",
                        lambda user_id, words: calls.append((user_id, words)))
    return calls


def test_a_recorded_round_refreshes_the_schedule_for_its_words(
        user_client, deck, recorded, refreshed):
    """The words the round answered, with their parts of speech -- the
    schedule's key -- and nothing else."""
    user_client.post("/games/spell_it/play?topic=Work",
                     data={"answer_1": "delegate", "answer_3": "burnout"})

    assert refreshed == [(TEST_USER_ID, [("delegate", "verb"),
                                         ("burnout", "noun")])]


def test_no_log_row_means_no_refresh(user_client, deck, monkeypatch, refreshed):
    """The schedule is a cache of the log. If the log write failed there is
    nothing new to replay, and refreshing would only repeat yesterday."""
    def broken(user_id, game, answers):
        raise RuntimeError("the database is not answering")

    monkeypatch.setattr("utils.record_answers", broken)
    user_client.post("/games/spell_it/play?topic=Work",
                     data={"answer_1": "delegate"})

    assert refreshed == []


def test_a_failed_refresh_keeps_the_log_row_and_the_results(
        user_client, deck, recorded, monkeypatch, caplog):
    """The two failures mean different things: a lost log row is lost history,
    a stale schedule row is a cache `rebuild_schedule.py` repairs. So the log
    is already written, the page still shows, and the log line says which."""
    def broken(user_id, words):
        raise RuntimeError("upsert failed")

    monkeypatch.setattr("utils.refresh_schedule", broken)
    with caplog.at_level(logging.ERROR):
        response = user_client.post("/games/spell_it/play?topic=Work",
                                    data={"answer_1": "delegate"})

    assert "Score: 1 / 1" in response.get_data(as_text=True)
    assert recorded == [(TEST_USER_ID, "spell_it", [(1, True)])]
    assert "recall schedule" in caplog.text
    assert "rebuild_schedule.py" in caplog.text


def test_an_anonymous_round_refreshes_nothing(client, deck, recorded, refreshed):
    client.post("/games/spell_it/play?topic=Work", data={"answer_1": "delegate"})

    assert refreshed == []


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
