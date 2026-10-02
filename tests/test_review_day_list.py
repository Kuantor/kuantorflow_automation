"""Today's review list stays the same all day (kuantorflow#529).

Anton's report: seven words to review, one game, and the list was gone.
Grading a round moves each answered word to its next date at once (#479), and
the review read the **current** schedule, so a word left the list the moment
it was answered once.

Today's list is now **the words due when the learner's day began**, answered
since or not. The date a word had this morning is the replay of its answers
from before today -- `recall.start_of_day_dates()` -- so nothing is stored.
What is pinned here:

* a word answered today **stays** on the page, in the badge's count and in the
  review round's deck, marked as reviewed;
* a word that was **not** due this morning is not added by being answered
  today (an early pass is practice, a first answer had no date);
* the badge's three states, and a round that reaches unreviewed words first
  without excluding the rest;
* tomorrow is rebuilt from tomorrow's morning;
* `day_start()` is `learner_day()` read backwards.

Dates are pinned by patching `recall.today()`, as in test_review_due.py.
"""

import re
from datetime import date, datetime

import pytest

import recall
import utils
from test_draw_prefers_due import DECK
from test_review_due import SCHEDULE, TODAY, dealt, review  # noqa: F401

# Learner-day 30 September, mid-morning in Kyiv (UTC+3 in summer).
THIS_MORNING = datetime(2026, 9, 30, 7)
LAST_WEEK = datetime(2026, 9, 24, 7)

RESIGN = recall.word_key("resign", "verb")
DELEGATE = recall.word_key("delegate", "verb")
APPRAISE = recall.word_key("appraise", "verb")


def _answers(*rows):
    return [recall.Answer(when, correct) for when, correct in rows]


@pytest.fixture()
def answered_today(review, monkeypatch):
    """`answered_today(histories, schedule)`: what the log says was answered
    today, and the schedule as the refresh left it afterwards."""
    asked = []

    def install(histories, schedule=None):
        if schedule is not None:
            review(schedule)

        def read(user_id, since):
            asked.append(since)
            return dict(histories) if user_id else {}
        monkeypatch.setattr(utils, "histories_answered_since", read)
    install.asked = asked
    return install


# resign was due today; answered right this morning, the refresh moved it on.
AFTER_RESIGN = {**SCHEDULE, ("resign", "verb"): date(2026, 10, 6)}
RESIGN_TODAY = {RESIGN: _answers((LAST_WEEK, True), (THIS_MORNING, True))}


def _badge(body):
    found = re.search(r'class="review-badge"[^>]*>\s*Review\s*\(([^)]*)\)', body)
    return " ".join(found.group(1).split()) if found else None


def _listed(body):
    return re.findall(r'<span class="review-word">([^<]+)</span>', body)


# --- the page and the badge ---------------------------------------------------

def test_a_word_answered_today_stays_on_the_list(user_client, answered_today):
    """The bug itself: resign was answered, its date moved to next week -- and
    it is still today's word."""
    answered_today(RESIGN_TODAY, AFTER_RESIGN)
    body = user_client.get("/review").get_data(as_text=True)

    assert sorted(_listed(body)) == ["delegate", "resign"]
    resign = body[body.index(">resign<"):][:300]
    assert "reviewed today" in resign
    assert "1 already reviewed" in body


def test_not_yet_reviewed_words_are_listed_first(user_client, answered_today):
    answered_today(RESIGN_TODAY, AFTER_RESIGN)
    body = user_client.get("/review").get_data(as_text=True)

    assert _listed(body) == ["delegate", "resign"]


def test_the_page_says_the_list_lasts_until_tomorrow(user_client, answered_today):
    answered_today(RESIGN_TODAY, AFTER_RESIGN)
    text = " ".join(user_client.get("/review").get_data(as_text=True).split())

    assert "stays the same until tomorrow" in text
    assert "first answer of the day" in text


@pytest.mark.parametrize("histories, schedule, label", [
    ({}, SCHEDULE, "2 due"),
    (RESIGN_TODAY, AFTER_RESIGN, "1 of 2 left"),
    ({**RESIGN_TODAY, DELEGATE: _answers((datetime(2026, 9, 20, 7), True),
                                         (THIS_MORNING, False))},
     {**AFTER_RESIGN, ("delegate", "verb"): date(2026, 10, 1)},
     "2 done today"),
], ids=["none-yet", "part-way", "all-done"])
def test_the_badge_says_how_far_through_the_list_you_are(
        user_client, answered_today, histories, schedule, label):
    """It stays all day rather than vanishing once the words are answered."""
    answered_today(histories, schedule)

    assert _badge(user_client.get("/").get_data(as_text=True)) == label


def test_a_word_not_due_this_morning_is_not_added(user_client, answered_today):
    """appraise was due on 12 October; an early pass today is practice and
    moves nothing (#479's rule 3) -- it must not become today's review."""
    early = _answers((datetime(2026, 9, 20, 7), True),
                     (datetime(2026, 9, 21, 7), True),
                     (datetime(2026, 9, 27, 7), True),
                     (THIS_MORNING, True))
    answered_today({APPRAISE: early},
                   {**SCHEDULE, ("appraise", "verb"): date(2026, 10, 12)})
    body = user_client.get("/review").get_data(as_text=True)

    assert "appraise" not in _listed(body)


def test_a_word_first_answered_today_is_not_added(user_client, answered_today,
                                                  stub_deck):
    """commute had no date this morning, so it was not due; failing it today
    makes it due tomorrow, not today."""
    commute = recall.word_key("commute", "verb")
    answered_today({commute: _answers((THIS_MORNING, False))},
                   {**SCHEDULE, ("commute", "verb"): date(2026, 10, 1)})
    body = user_client.get("/review").get_data(as_text=True)

    assert "commute" not in _listed(body)


def test_the_answers_are_read_from_the_start_of_today(user_client,
                                                     answered_today):
    answered_today(RESIGN_TODAY, AFTER_RESIGN)
    user_client.get("/review")

    assert answered_today.asked == [recall.day_start(TODAY)]


def test_an_unreadable_log_leaves_the_review_as_it_was(user_client,
                                                      answered_today,
                                                      monkeypatch):
    """A read that fails costs the start-of-day dates, not the page."""
    def broken(user_id, since):
        raise RuntimeError("log unreachable")

    review_schedule = dict(SCHEDULE)
    answered_today({}, review_schedule)
    monkeypatch.setattr(utils, "histories_answered_since", broken)
    response = user_client.get("/review")

    assert response.status_code == 200
    assert sorted(_listed(response.get_data(as_text=True))) == ["delegate",
                                                                "resign"]


# --- the round ----------------------------------------------------------------

def test_a_review_round_still_deals_a_word_answered_today(user_client,
                                                          answered_today,
                                                          dealt):
    """The second game of the day: resign (id 2) is in the deck again."""
    answered_today(RESIGN_TODAY, AFTER_RESIGN)
    user_client.get("/games/spell_it/play?review=1&words=10")

    assert dealt and dealt[0] == {1, 2}


def test_a_review_post_still_grades_a_word_answered_today(user_client,
                                                          answered_today,
                                                          monkeypatch):
    recorded = []
    monkeypatch.setattr("utils.record_answers",
                        lambda user_id, game, answers: recorded.append(
                            [(c["id"], ok) for c, ok in answers]))
    answered_today(RESIGN_TODAY, AFTER_RESIGN)
    user_client.post("/games/spell_it/play?review=1",
                     data={"answer_2": "resign"})

    assert recorded == [[(2, True)]]


def test_a_reviewed_word_weighs_less_but_is_never_excluded():
    """So the next game reaches the words not yet reviewed first, and a list
    longer than a round is covered before it repeats."""
    due = {RESIGN: TODAY, DELEGATE: date(2026, 9, 27)}
    weight = recall.review_weight(due, TODAY, {RESIGN})

    assert weight({"word": "resign", "pos": "verb"}) == pytest.approx(
        1 * recall.REVIEWED_TODAY_WEIGHT)
    assert weight({"word": "delegate", "pos": "verb"}) == 4
    assert 0 < recall.REVIEWED_TODAY_WEIGHT < 1


# --- the pure half ------------------------------------------------------------

def test_the_start_of_day_date_replays_only_the_answers_before_today():
    """resign: right on the 24th (due the 25th), wrong this morning. The
    morning's date is the 25th; the miss belongs to today."""
    dates, answered = recall.start_of_day_dates(
        {RESIGN: _answers((LAST_WEEK, True), (THIS_MORNING, False))}, TODAY)

    assert dates == {RESIGN: date(2026, 9, 25)}
    assert answered == {RESIGN}


def test_tomorrow_is_rebuilt_from_tomorrows_morning():
    """Answered on the 30th and not since: on 1 October it is not one of the
    day's answered words, and its current date (after the miss: the 1st) is
    the one the list reads -- so a word missed today is due tomorrow."""
    history = {RESIGN: _answers((LAST_WEEK, True), (THIS_MORNING, False))}
    dates, answered = recall.start_of_day_dates(history, date(2026, 10, 1))

    assert dates == {} and answered == set()
    assert recall.replay(history[RESIGN]).due_on == date(2026, 10, 1)


@pytest.mark.parametrize("day", [date(2026, 1, 15), date(2026, 7, 15),
                                 date(2026, 10, 25), date(2026, 3, 29)],
                         ids=["winter", "summer", "dst-ends", "dst-starts"])
def test_day_start_is_learner_day_read_backwards(day):
    from datetime import timedelta
    start = recall.day_start(day)

    assert recall.learner_day(start) == day
    assert recall.learner_day(start - timedelta(seconds=1)) == day - timedelta(days=1)
