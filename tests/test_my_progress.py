"""My progress: a learner's own report, saved as a PDF (kuantorflow#493).

A signed-in learner's page of what they have done and which words they know,
built from the answer log (#338) and the schedule (#479) -- nothing new is
recorded -- and saved as a PDF through the browser's print dialog, so the
student sends it to whoever they choose and the site needs no teacher role.

What is pinned here:

* **the statuses**, pure functions over plain rows: known (a week's interval),
  struggling (two lapses and not yet back to a week), learning; *due today* a
  count across them, as the Review button counts;
* **every section** -- summary, last 14 days, per game, per topic, the words --
  from a known schedule and log, and **the topic filter narrows all of them**;
* **only the learner's own rows**: the reads take the session's id and
  nothing from the request (the SQL half is in test_recall_schedule_db.py);
* the anonymous visitor, the empty and the failed states, the limitations,
  the print-only heading a PDF reader needs, the header link and the log line.

The print layout itself is browser behaviour, checked on the rendered page and
recorded in the PR.
"""

from datetime import date, datetime

import pytest

import progress
import recall
from conftest import TEST_USER_ID

TODAY = date(2026, 10, 2)

DECK = [
    {"id": 1, "word": "delegate", "pos": "verb", "topic": "Work"},
    {"id": 2, "word": "resign", "pos": "verb", "topic": "Work"},
    {"id": 3, "word": "acquit", "pos": "verb", "topic": "Law"},
    {"id": 4, "word": "verdict", "pos": "noun", "topic": "Law"},
    {"id": 5, "word": "unrelated", "pos": "adjective", "topic": "Misc"},
]


def _row(word, pos, interval, lapses, due, reps=3):
    return {"word": word, "pos": pos, "reps": reps, "lapses": lapses,
            "ease": 2500, "interval_days": interval, "due_on": due}


SCHEDULE = [
    _row("delegate", "verb", 15, 0, date(2026, 10, 10)),   # known
    _row("resign", "verb", 1, 0, TODAY),                    # learning, due
    _row("acquit", "verb", 1, 2, date(2026, 10, 1)),       # struggling, due
    _row("verdict", "noun", 30, 3, date(2026, 10, 20)),    # known: graduated
    _row("ghost", "noun", 2, 0, date(2026, 10, 5)),        # learning, no card
]

# Two rounds today (one Spell it, one Fill the gap) and one a month ago.
R1 = datetime(2026, 10, 2, 7, 0)
R2 = datetime(2026, 10, 2, 8, 0)
OLD = datetime(2026, 9, 1, 7, 0)
ANSWERS = [
    {"word": "delegate", "pos": "verb", "game": "spell_it", "correct": 1, "answered_at": OLD},
    {"word": "delegate", "pos": "verb", "game": "spell_it", "correct": 1, "answered_at": R1},
    {"word": "acquit", "pos": "verb", "game": "spell_it", "correct": 0, "answered_at": R1},
    {"word": "resign", "pos": "verb", "game": "fill_the_gap", "correct": 1, "answered_at": R2},
    {"word": "verdict", "pos": "noun", "game": "fill_the_gap", "correct": 0, "answered_at": R2},
]


def _topics():
    found = {}
    for card in DECK:
        found.setdefault(recall.word_key(card["word"], card["pos"]), []).append(card["topic"])
    return found


def _report(topics=None):
    return progress.build(SCHEDULE, ANSWERS, _topics(), TODAY, topics=topics)


@pytest.fixture()
def learner(stub_deck, monkeypatch):
    """The deck, a pinned today, and this learner's rows -- recording which
    user id each read was asked for."""
    import utils

    stub_deck(cards=DECK)
    monkeypatch.setattr(recall, "today", lambda: TODAY)
    asked = []

    def rows(found):
        def read(user_id):
            asked.append(user_id)
            return [dict(r) for r in found] if user_id else []
        return read
    monkeypatch.setattr(utils, "schedule_rows", rows(SCHEDULE))
    monkeypatch.setattr(utils, "answer_rows", rows(ANSWERS))
    return asked


def _text(response):
    return " ".join(response.get_data(as_text=True).split())


# --- the statuses (pure) ----------------------------------------------------------

@pytest.mark.parametrize("interval, lapses, expected", [
    (7, 0, "known"), (6, 0, "learning"), (1, 1, "learning"),
    (3, 2, "struggling"), (30, 3, "known"),
], ids=["a-week", "six-days", "one-lapse", "two-lapses", "graduated"])
def test_a_words_status_comes_from_its_schedule(interval, lapses, expected):
    assert progress.status(interval, lapses) == expected


def test_the_summary_counts_each_word_once_and_due_across_them():
    """Due is not a fourth state: a known word can be due, and the count must
    agree with the Review button's."""
    summary = _report()["summary"]

    assert (summary["known"], summary["learning"], summary["struggling"]) == (2, 2, 1)
    assert summary["due"] == 2 and summary["words"] == 5


def test_the_words_are_grouped_struggling_first_with_their_counts():
    words = _report()["words"]

    assert [w["word"] for w in words] == ["acquit", "resign", "ghost",
                                           "delegate", "verdict"]
    delegate = next(w for w in words if w["word"] == "delegate")
    assert (delegate["times"], delegate["right"]) == (2, 2)
    assert delegate["topics"] == ["Work"]
    assert next(w for w in words if w["word"] == "ghost")["topics"] == []


def test_by_topic_counts_each_topics_words():
    by_topic = dict(_report()["by_topic"])

    assert by_topic["Work"] == {"known": 1, "learning": 1, "struggling": 0, "due": 1}
    assert by_topic["Law"] == {"known": 1, "learning": 0, "struggling": 1, "due": 1}
    assert "Misc" not in by_topic, "a topic with no answered word is not listed"


def test_the_last_fourteen_days_count_rounds_by_their_shared_instant():
    """A round is its rows' shared timestamp plus the game (#338): today had
    two rounds, four answers, two right; a month ago is out of the window."""
    activity = _report()["activity"]

    assert activity["active"] == 1
    assert activity["rows"] == [{"day": TODAY, "rounds": 2, "answers": 4,
                                 "right": 2}]


def test_per_game_flags_the_self_marked_one():
    games = {row["game"]: row for row in _report()["games"]}

    assert games["spell_it"]["rounds"] == 2 and games["spell_it"]["answers"] == 3
    assert games["fill_the_gap"]["self_marked"] is True
    assert games["spell_it"]["self_marked"] is False


def test_the_topic_filter_narrows_every_section():
    report = _report(topics=["Law"])

    assert {w["word"] for w in report["words"]} == {"acquit", "verdict"}
    assert report["summary"]["words"] == 2 and report["summary"]["due"] == 1
    assert [topic for topic, _ in report["by_topic"]] == ["Law"]
    assert report["activity"]["rows"][0]["answers"] == 2
    assert sum(row["answers"] for row in report["games"]) == 2
    assert report["first_day"] == TODAY, "delegate's old answer is Work's"


def test_a_word_in_two_topics_counts_in_each_but_once_overall():
    topics = _topics()
    topics[recall.word_key("acquit", "verb")] = ["Law", "Work"]
    report = progress.build(SCHEDULE, ANSWERS, topics, TODAY)

    by_topic = dict(report["by_topic"])
    assert by_topic["Work"]["struggling"] == 1 and by_topic["Law"]["struggling"] == 1
    assert report["summary"]["struggling"] == 1


def test_accuracy_is_a_whole_percentage_or_nothing():
    assert progress.percent(2, 3) == 67
    assert progress.percent(0, 0) is None


# --- the page ---------------------------------------------------------------------

def test_an_anonymous_visitor_is_asked_to_sign_in(client, learner):
    text = _text(client.get("/progress"))

    assert "needs an account" in text
    assert learner == [], "nothing is read for nobody"


def test_the_page_shows_the_learners_report(user_client, learner):
    response = user_client.get("/progress")
    text = _text(response)

    assert response.status_code == 200
    for word in ("delegate", "resign", "acquit", "verdict", "ghost"):
        assert f'<span class="review-word">{word}</span>' in text
    assert "Struggling (1)" in text and "Known (2)" in text
    assert "Active on <strong>1</strong> of the last 14 days" in text
    assert "Fill the gap <span class=\"hint\">(your own ticks)</span>" in text


def test_it_reads_the_session_learner_and_nobody_else(user_client, learner):
    """Nothing here takes a user from the request: a `user_id` in the URL is
    ignored, and both reads are asked for the signed-in id."""
    user_client.get("/progress?user_id=999&user=999")

    assert learner and set(learner) == {TEST_USER_ID}


def test_the_filter_narrows_the_page(user_client, learner):
    text = _text(user_client.get("/progress?topic=Law"))

    assert 'review-word">acquit<' in text and 'review-word">verdict<' in text
    assert 'review-word">delegate<' not in text
    assert "Topics: Law" in text


def test_an_unknown_topic_in_the_url_is_ignored(user_client, learner):
    text = _text(user_client.get("/progress?topic=Nonsense"))

    assert "Topics: all" in text and 'review-word">delegate<' in text


def test_only_practised_topics_are_offered_as_filters(user_client, learner):
    text = _text(user_client.get("/progress"))

    assert 'value="Law"' in text and 'value="Work"' in text
    assert 'value="Misc"' not in text


def test_the_limitations_are_stated(user_client, learner):
    text = _text(user_client.get("/progress"))

    assert "What this does not include" in text
    assert "without signing in" in text
    assert "Odd one out" in text and "Real or fake" in text
    assert "your own tick" in text


def test_the_pdf_heading_says_whose_report_and_what_it_covers(user_client,
                                                             learner):
    """On paper there is no header and no app to ask: the file names the
    learner, the dates, the filter, the key to the statuses and the site."""
    text = _text(user_client.get("/progress?topic=Law"))
    head = text[text.index('progress-print-head'):][:900]

    assert "print-only" in text[text.index('progress-print-head') - 60:][:80]
    assert "Progress report &mdash; Test User" in head
    assert "made 2 October 2026" in head
    assert "topics: Law" in head
    assert progress.STATUS_KEY.split(".")[0] in head
    assert "localhost" in head


def test_the_download_button_opens_the_print_dialog(user_client, learner):
    text = _text(user_client.get("/progress"))

    assert 'id="progress-pdf"' in text and "window.print()" in text
    assert "Save as PDF" in text


def test_nothing_recorded_yet_says_so(user_client, stub_deck, monkeypatch):
    monkeypatch.setattr(recall, "today", lambda: TODAY)
    text = _text(user_client.get("/progress"))

    assert "Nothing recorded yet" in text


def test_an_unreadable_log_is_a_notice_not_an_error(user_client, learner,
                                                    monkeypatch):
    import utils

    def broken(user_id):
        raise RuntimeError("database down")

    monkeypatch.setattr(utils, "schedule_rows", broken)
    response = user_client.get("/progress")

    assert response.status_code == 200
    assert "could not be read just now" in _text(response)


def test_the_header_and_the_front_page_link_it_for_a_signed_in_learner(
        user_client, learner):
    """Both: the header's link is hidden on a phone, where a fourth link would
    wrap the row #502 kept to one, so the front page is the way in there."""
    signed_in = user_client.get("/").get_data(as_text=True)

    assert '<a class="nav-progress" href="/progress">My progress</a>' in signed_in
    assert '<a class="progress-badge" href="/progress">My progress</a>' in signed_in


def test_the_header_link_is_hidden_on_a_phone():
    import re
    from pathlib import Path
    import web
    css = (Path(web.__file__).parent / "static" / "css" / "style.css").read_text(encoding="utf-8")
    phone = css[css.index("@media (max-width: 640px)"):][:900]
    assert re.search(r"\.site-header nav a\.nav-progress\s*\{\s*display:\s*none", phone)


def test_no_header_link_for_an_anonymous_visitor(client, learner):
    """`user_client` is this same client signed in, so this test has its own."""
    assert 'href="/progress"' not in client.get("/").get_data(as_text=True)


def test_opening_it_is_logged(user_client, learner, action_logs):
    user_client.get("/progress?topic=Law")
    log = (action_logs / "cards.log").read_text(encoding="utf-8")

    line = next(l for l in log.splitlines() if "PROGRESS" in l)
    assert "words=2" in line and "topics=Law" in line


# --- the date range (follow-up to #493) -------------------------------------------
#
# The answers outside the range are dropped first, so the words are the ones
# practised in it, counted by that period's answers; a word's state is still
# today's, because the schedule holds nothing else. The activity table covers
# the range, and the PDF heading names it.

SEPT_1 = date(2026, 9, 1)


def test_a_range_keeps_only_the_words_practised_in_it():
    report = progress.build(SCHEDULE, ANSWERS, _topics(), TODAY,
                            since=SEPT_1, until=SEPT_1)

    assert [w["word"] for w in report["words"]] == ["delegate"]
    delegate = report["words"][0]
    assert (delegate["times"], delegate["right"]) == (1, 1), "that period's answers"
    assert delegate["status"] == "known", "its state is today's"
    assert report["summary"]["words"] == 1
    assert [topic for topic, _ in report["by_topic"]] == ["Work"]
    assert report["dated"] is True and report["first_day"] == SEPT_1


def test_a_range_narrows_activity_and_games_to_its_answers():
    report = progress.build(SCHEDULE, ANSWERS, _topics(), TODAY,
                            since=SEPT_1, until=SEPT_1)
    activity = report["activity"]

    assert (activity["first"], activity["last"], activity["days"]) == (SEPT_1, SEPT_1, 1)
    assert activity["rows"] == [{"day": SEPT_1, "rounds": 1, "answers": 1, "right": 1}]
    assert [(g["game"], g["answers"]) for g in report["games"]] == [("spell_it", 1)]


def test_an_open_ended_range_runs_to_today():
    """From 1 October: today's four answered words, delegate counted once (its
    September answer is outside), and a two-day activity window."""
    report = progress.build(SCHEDULE, ANSWERS, _topics(), TODAY,
                            since=date(2026, 10, 1))

    assert sorted(w["word"] for w in report["words"]) == ["acquit", "delegate",
                                                          "resign", "verdict"]
    assert next(w for w in report["words"] if w["word"] == "delegate")["times"] == 1
    assert (report["activity"]["first"], report["activity"]["last"]) == (date(2026, 10, 1), TODAY)
    assert report["activity"]["days"] == 2


def test_a_range_with_only_an_end_starts_at_the_first_answer():
    report = progress.build(SCHEDULE, ANSWERS, _topics(), TODAY, until=TODAY)

    assert report["activity"]["first"] == SEPT_1
    assert report["summary"]["words"] == 4, "ghost was never answered"


def test_without_a_range_nothing_changes():
    report = _report()

    assert report["dated"] is False
    assert report["summary"]["words"] == 5
    assert report["activity"]["days"] == progress.ACTIVITY_DAYS


def test_topics_and_dates_narrow_together():
    report = progress.build(SCHEDULE, ANSWERS, _topics(), TODAY,
                            topics=["Law"], since=TODAY)

    assert sorted(w["word"] for w in report["words"]) == ["acquit", "verdict"]
    assert sum(g["answers"] for g in report["games"]) == 2


@pytest.mark.parametrize("raw_from, raw_to, expected", [
    ("2026-09-01", "2026-09-30", (SEPT_1, date(2026, 9, 30))),
    ("2026-09-30", "2026-09-01", (SEPT_1, date(2026, 9, 30))),
    ("", "", (None, None)),
    ("yesterday", "2026-13-40", (None, None)),
    ("2026-09-01", "2027-01-01", (SEPT_1, TODAY)),
    ("2027-01-01", None, (TODAY, None)),
], ids=["range", "backwards", "empty", "not-dates", "future-end", "future-start"])
def test_the_date_boxes_are_read_forgivingly(raw_from, raw_to, expected):
    """A hand-edited URL gets the page without that end, never an error; a
    future end is today; a backwards range is turned round."""
    import rounds
    assert rounds._date_range(raw_from, raw_to, TODAY) == expected


def test_the_page_shows_a_range(user_client, learner):
    text = _text(user_client.get("/progress?from=2026-09-01&to=2026-09-01"))

    assert 'review-word">delegate<' in text and 'review-word">acquit<' not in text
    assert "Dates: 1 September 2026" in text
    assert "Activity, 1 September 2026" in text
    assert "practised 1 September 2026, each shown as you know it today" in text
    assert 'name="from" max="2026-10-02" value="2026-09-01"' in text
    assert "Answered then" in text


def test_the_pdf_heading_names_the_range(user_client, learner):
    text = _text(user_client.get("/progress?from=2026-09-01&to=2026-10-02"))
    head = text[text.index('progress-print-head'):][:600]

    assert "Answers 1 September 2026 &ndash; 2 October 2026" in head


def test_bad_dates_in_the_url_leave_the_page_whole(user_client, learner):
    response = user_client.get("/progress?from=soon&to=later")

    assert response.status_code == 200
    assert "Dates: all time" in _text(response)


def test_the_range_is_logged(user_client, learner, action_logs):
    user_client.get("/progress?from=2026-09-01&to=2026-09-30")
    line = next(l for l in (action_logs / "cards.log").read_text(encoding="utf-8").splitlines()
                if "PROGRESS" in l)

    assert "since=2026-09-01" in line and "until=2026-09-30" in line


def test_the_filter_is_open_with_nothing_chosen(user_client, learner):
    """Closed, nothing on the page said a date range was there to use
    (Anton's report, 2 Oct). Open from the start; its summary folds it."""
    text = _text(user_client.get("/progress"))

    assert '<details open>' in text
    assert 'name="from"' in text and 'name="to"' in text
