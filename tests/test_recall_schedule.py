"""The SM-2 schedule's rules, on plain lists (kuantorflow#479).

`recall.replay()` is pure -- one word's answers in, its schedule out -- which
is what lets the live refresh after a round and `rebuild_schedule.py` be the
same arithmetic. So every rule is tested here without a database, and
test_recall_schedule_db.py only has to prove the SQL around it.

The rules are the ticket's: SM-2 on verified pass/fail (1, 6, then interval x
ease; a fail resets, counts a lapse and costs 0.2 ease, floor 1.3), plus four
this app needs -- one answer per learner-day, a Kyiv day from 04:00, an early
pass is practice, and a tick from *Fill the gap* is weaker evidence (#484).

Times are written in UTC, as the log stores them. In late September Kyiv is
UTC+3, so 01:00 UTC is 04:00 there -- the moment a learner's day turns over.
"""

from datetime import date, datetime, timedelta

import pytest

import games
import recall
from recall import Answer, replay


def at(day, hour=9, minute=0):
    """A UTC instant on 2026-09-`day` -- noon in Kyiv, well inside its day."""
    return datetime(2026, 9, day, hour, minute)


def checked(when, correct=True):
    return Answer(when, correct)


def ticked(when, correct=True):
    return Answer(when, correct, self_marked=True)


def sept(day):
    return date(2026, 9, day)


# --- plain SM-2 ---------------------------------------------------------------

def test_a_first_pass_is_due_tomorrow():
    s = replay([checked(at(1))])

    assert (s.reps, s.lapses, s.interval_days, s.due_on) == (1, 0, 1, sept(2))
    assert s.ease == recall.START_EASE


def test_passes_on_time_grow_one_six_then_by_ease():
    """1, 6, round(6 x 2.5) = 15, round(15 x 2.5) = 38: each answer given on
    the day the previous one made it due."""
    s = replay([checked(at(1)), checked(at(2)), checked(at(8)),
                checked(datetime(2026, 9, 23, 9))])

    assert (s.reps, s.interval_days) == (4, 38)
    assert s.due_on == date(2026, 10, 31)


def test_a_fail_resets_counts_a_lapse_and_costs_ease():
    s = replay([checked(at(1)), checked(at(2)), checked(at(8), correct=False)])

    assert (s.reps, s.lapses, s.interval_days, s.due_on) == (0, 1, 1, sept(9))
    assert s.ease == pytest.approx(2.3)
    assert s.ease_permille == 2300


def test_ease_never_falls_below_the_floor():
    s = replay([checked(at(day), correct=False) for day in range(1, 15)])

    assert s.ease == pytest.approx(recall.MIN_EASE)
    assert s.lapses == 14


def test_a_pass_after_a_lapse_climbs_from_one_again_at_the_lower_ease():
    s = replay([checked(at(1)), checked(at(2)), checked(at(8), correct=False),
                checked(at(9)), checked(at(10)), checked(at(16))])

    assert (s.reps, s.interval_days) == (3, round(6 * 2.3))


def test_no_answers_is_no_row():
    """A word never answered has no schedule, which is different from one that
    is due -- #92's count must not include it."""
    assert replay([]) is None


def test_the_order_answers_arrive_in_does_not_matter():
    answers = [checked(at(1)), checked(at(2)), checked(at(8), correct=False)]

    assert replay(list(reversed(answers))) == replay(answers)


# --- one answer per learner-day ------------------------------------------------

def test_only_the_first_answer_of_a_day_moves_the_schedule():
    """Three rounds in an afternoon would otherwise take a word 1 -> 6 -> 15
    days, which is the opposite of spacing."""
    s = replay([checked(at(1, 9)), checked(at(1, 10)), checked(at(1, 11))])

    assert (s.reps, s.interval_days) == (1, 1)


def test_a_later_miss_on_the_same_day_does_not_undo_the_first_pass():
    """The first answer measures recall after the gap; the later ones measure
    recall minutes after seeing the answer."""
    s = replay([checked(at(1, 9)), checked(at(1, 10), correct=False)])

    assert (s.reps, s.lapses) == (1, 0)


# --- the learner's day ---------------------------------------------------------

def test_the_day_turns_over_at_four_in_the_morning_kyiv_time():
    """03:59 in Kyiv still belongs to yesterday; 04:00 is today. In September
    Kyiv is UTC+3, so that is 00:59 and 01:00 UTC."""
    assert recall.learner_day(datetime(2026, 9, 28, 0, 59)) == sept(27)
    assert recall.learner_day(datetime(2026, 9, 28, 1, 0)) == sept(28)


def test_the_rollover_follows_kyiv_into_winter_time():
    """In January Kyiv is UTC+2, so the same 04:00 is 02:00 UTC -- a fixed
    offset would be an hour wrong for half the year."""
    assert recall.learner_day(datetime(2026, 1, 15, 1, 59)) == date(2026, 1, 14)
    assert recall.learner_day(datetime(2026, 1, 15, 2, 0)) == date(2026, 1, 15)


def test_a_late_evening_answer_and_an_early_morning_one_are_one_day():
    """23:30 and 02:30 Kyiv time are the same learner-day, so the second does
    not count again."""
    s = replay([checked(datetime(2026, 9, 1, 20, 30)),      # 23:30 Kyiv
                checked(datetime(2026, 9, 1, 23, 30))])     # 02:30 Kyiv

    assert (s.reps, s.interval_days) == (1, 1)


def test_the_zone_is_kyiv():
    """`tzdata` is a requirement because Windows has no zone database; the
    UTC+2 fallback exists for a machine without it, not for this one."""
    assert "Kyiv" in str(recall.LEARNERS_ZONE) or "Kiev" in str(recall.LEARNERS_ZONE)


# --- an early pass is practice ---------------------------------------------------

def test_a_pass_before_the_word_is_due_changes_nothing():
    """Without this a word played four days running reaches 37 days with its
    spacing never tested. Due on the 8th; passed again on the 3rd."""
    on_time = replay([checked(at(1)), checked(at(2))])
    with_practice = replay([checked(at(1)), checked(at(2)), checked(at(3))])

    assert on_time.due_on == sept(8)
    assert with_practice == on_time


def test_a_fail_before_the_word_is_due_is_a_real_lapse():
    """Forgetting sooner than scheduled is exactly what a lapse is."""
    s = replay([checked(at(1)), checked(at(2)), checked(at(3), correct=False)])

    assert (s.lapses, s.interval_days, s.due_on) == (1, 1, sept(4))


def test_an_overdue_pass_counts_like_an_on_time_one():
    s = replay([checked(at(1)), checked(at(20))])

    assert (s.reps, s.interval_days, s.due_on) == (2, 6, sept(26))


# --- self-marked answers (#484) ----------------------------------------------------

def test_a_checked_answer_decides_a_day_even_after_a_tick():
    """Fill the gap played first, the quiz ten minutes later: the quiz wins."""
    s = replay([ticked(at(1, 9), correct=False), checked(at(1, 10))])

    assert (s.reps, s.lapses) == (1, 0)


def test_an_unticked_card_is_a_full_lapse():
    """"I did not remember it" is an honest signal, not a discounted one."""
    s = replay([checked(at(1)), checked(at(2)), ticked(at(8), correct=False)])

    assert (s.reps, s.lapses, s.interval_days) == (0, 1, 1)
    assert s.ease == pytest.approx(2.3)


def test_ticks_alone_grow_by_half_and_stop_at_the_cap():
    """1, then half-way from 1 to 6 (4), then capped at 6 however many more."""
    s1 = replay([ticked(at(1))])
    s2 = replay([ticked(at(1)), ticked(at(2))])
    s4 = replay([ticked(at(1)), ticked(at(2)), ticked(at(6)), ticked(at(12))])

    assert s1.interval_days == 1
    assert s2.interval_days == 4
    assert s4.interval_days == recall.WEAK_PASS_CAP


def test_a_tick_never_shortens_an_interval_checked_answers_earned():
    s = replay([checked(at(1)), checked(at(2)), checked(at(8)),
                ticked(datetime(2026, 9, 23, 9))])

    assert s.interval_days == 15


def test_a_tick_is_weaker_than_a_checked_pass_at_every_step():
    for days in ([1], [1, 2], [1, 2, 8]):
        by_tick = replay([ticked(at(d)) for d in days])
        by_check = replay([checked(at(d)) for d in days])
        assert by_tick.interval_days <= by_check.interval_days, days


# --- which games are self-marked -------------------------------------------------

def test_self_marked_games_come_from_the_one_declaration():
    assert recall.SELF_MARKED_GAMES == {
        slug for slug, a in games.ACTIVITIES.items() if a.self_marked}


def test_a_log_row_becomes_an_answer_with_the_right_weight():
    assert recall.answer_from_row(at(1), 1, "fill_the_gap").self_marked
    assert not recall.answer_from_row(at(1), 1, "spell_it").self_marked
    # A game since removed still counts: as checked, which every game but
    # Fill the gap has always been.
    assert not recall.answer_from_row(at(1), 0, "retired_game").self_marked
