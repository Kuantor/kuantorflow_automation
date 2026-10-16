"""The daily activity email (kuantorflow#593): `scripts/daily_report.py`.

Once a day, for **the previous Kyiv day** (04:00 to 04:00, #447), email Anton a
short report of what learners **other than him** did, and **send nothing on a
day when nobody else did anything**. What must hold:

* the day's edges follow the 04:00 Kyiv rule (`recall.day_start`);
* an admin account (`ADMIN_EMAILS`) never appears and never triggers a send;
  his blocks and unblocks are reported but are not "activity" either;
* one block per learner, by id and **masked** address, with their counts;
  anonymous visitors as totals only;
* never a full address, a card's text or a chat message;
* rounds are counted from `games.log` (one line per round: *Fill the gap*'s
  second, `self-marked` line is the same round), rotated files included;
* `--dry-run` prints and sends nothing; an empty day logs
  `result=skipped reason=no-activity`.

The database side is stubbed here and run for real in
`test_daily_report_db.py`; the mailer is stubbed.
"""

import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import pytest

import daily_report
import notify
import recall
import utils

DAY = date(2026, 10, 14)
ADMIN = "anton@example.test"
LEARNER = "anna.kowalska@example.test"
LIMITS = {utils.CHAT: 40, utils.LOOKUP: 50, utils.GENERATE: 10,
          utils.RECAP: 5, utils.UPLOAD: 10}


def _db(**over):
    base = {
        "accounts": {13: {"email": LEARNER, "created_at": datetime(2026, 10, 3)},
                     1: {"email": ADMIN, "created_at": datetime(2026, 7, 1)}},
        "new": set(), "cards": {}, "answers": {}, "usage": {},
        "emails": {LEARNER: 13, ADMIN: 1},
    }
    base.update(over)
    return base


def _logs(**over):
    base = {"rounds": Counter(), "blocks": [], "unblocks": []}
    base.update(over)
    return base


def _report(db=None, logs=None):
    return daily_report.build(db or _db(), logs or _logs(), {ADMIN}, LIMITS)


# --- the day ----------------------------------------------------------------

def test_the_day_runs_from_4am_to_4am_in_kyiv():
    start, end = daily_report.day_window(DAY)

    assert start == recall.day_start(DAY)
    assert end == recall.day_start(DAY + timedelta(days=1))
    assert start == datetime(2026, 10, 14, 1, 0)      # 04:00 EEST is 01:00 UTC


def test_the_default_day_is_yesterday():
    assert daily_report.default_day() == recall.today() - timedelta(days=1)


# --- who and what -----------------------------------------------------------

def test_a_learners_day_is_one_block_of_counts():
    report = _report(_db(cards={13: 5}, answers={13: 24},
                         usage={(13, utils.CHAT): 12, (13, utils.LOOKUP): 8}),
                     _logs(rounds=Counter({LEARNER: 3})))

    (learner,) = report["learners"]
    assert learner["id"] == 13
    assert learner["masked"] == notify.mask_email(LEARNER)
    assert learner["counts"]["cards"] == 5
    assert learner["counts"]["rounds"] == 3
    assert learner["counts"]["answers"] == 24
    assert learner["counts"][utils.CHAT] == 12
    assert learner["counts"][utils.LOOKUP] == 8


def test_the_admin_never_appears():
    report = _report(_db(cards={1: 9}, answers={1: 30}, usage={(1, utils.CHAT): 20}),
                     _logs(rounds=Counter({ADMIN: 4})))

    assert report["learners"] == []
    assert not daily_report.has_activity(report)


def test_the_admin_is_matched_whatever_the_case():
    db = _db(accounts={1: {"email": ADMIN.upper(), "created_at": None}},
             emails={ADMIN: 1}, cards={1: 3})

    assert _report(db)["learners"] == []


def test_anonymous_visitors_are_totals():
    report = _report(_db(usage={(utils.ALL_ACCOUNTS, utils.LOOKUP_ANON): 12,
                                (utils.ALL_ACCOUNTS, utils.CHAT_ANON): 5,
                                (utils.ALL_ACCOUNTS, utils.LOOKUP_ALL): 40}),
                     _logs(rounds=Counter({"anonymous": 3})))

    assert report["anonymous"] == {"rounds": 3, utils.CHAT: 5, utils.LOOKUP: 12,
                                   utils.GENERATE: 0}
    assert daily_report.has_activity(report)


def test_the_shared_all_pools_are_not_anyones_activity():
    """`lookup:all` counts everybody, Anton included; it is not a person."""
    report = _report(_db(usage={(utils.ALL_ACCOUNTS, utils.LOOKUP_ALL): 40}))

    assert not daily_report.has_activity(report)


def test_a_new_account_is_marked_even_with_nothing_done():
    report = _report(_db(new={13}))

    (learner,) = report["learners"]
    assert learner["new"] is True
    assert daily_report.has_activity(report)


def test_a_learner_at_a_limit_is_flagged():
    report = _report(_db(usage={(13, utils.CHAT): 40, (13, utils.LOOKUP): 49}))

    assert report["learners"][0]["limits"] == [(utils.CHAT, 40, 40)]


def test_blocks_are_reported_but_are_not_activity():
    report = _report(logs=_logs(blocks=[{"id": "13", "email": LEARNER, "reason": "spam"}],
                                unblocks=[{"id": "14", "email": "b@x.test"}]))

    assert not daily_report.has_activity(report)
    assert report["blocks"] == [(13, notify.mask_email(LEARNER), "spam")]
    assert report["unblocks"] == [(14, notify.mask_email("b@x.test"), None)]


def test_an_empty_day_has_no_activity():
    assert not daily_report.has_activity(_report())


# --- what it says -----------------------------------------------------------

def _rendered(**db):
    report = _report(_db(**db), _logs(rounds=Counter({LEARNER: 3, "anonymous": 2})))
    return daily_report.render(report, DAY)


def test_the_subject_names_the_day_and_the_learners():
    subject, _ = _rendered(cards={13: 1})

    assert subject == "KuantorFlow: activity on 14 Oct (1 learner)"


def test_the_body_never_holds_a_full_address():
    _, body = _rendered(cards={13: 5}, usage={(13, utils.CHAT): 12})

    assert notify.mask_email(LEARNER) in body
    assert LEARNER not in body and ADMIN not in body and "kowalska" not in body


def test_the_body_has_the_counts_and_the_anonymous_line():
    _, body = _rendered(cards={13: 5}, answers={13: 24}, usage={(13, utils.CHAT): 12})

    assert "#13" in body
    assert re.search(r"5 cards", body) and re.search(r"3 rounds", body)
    assert re.search(r"24 answers", body) and re.search(r"12 Mykola messages", body)
    assert re.search(r"Anonymous visitors:.*2 rounds", body)


def test_the_body_says_the_counters_are_server_days():
    """`action_usage` counts per CURDATE(), the server's (UTC) day."""
    _, body = _rendered(usage={(13, utils.CHAT): 1})

    assert "server" in body.lower() and "UTC" in body


# --- the logs ---------------------------------------------------------------

def _local(utc):
    """How applog stamps a UTC instant: this machine's local time."""
    return (utc.replace(tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S"))


def test_rounds_come_from_games_log_inside_the_day(action_logs):
    start, end = daily_report.day_window(DAY)
    action_logs.mkdir(parents=True, exist_ok=True)
    lines = [
        (start - timedelta(minutes=1), "ROUND game=quiz stage=graded asked=3 correct=1 user=" + LEARNER),
        (start, "ROUND game=quiz stage=graded asked=3 correct=2 user=" + LEARNER),
        (start + timedelta(hours=5), "ROUND game=fill_the_gap stage=dealt asked=5 user=anonymous"),
        (start + timedelta(hours=5, minutes=2), "ROUND game=fill_the_gap stage=self-marked asked=5 correct=4 user=anonymous"),
        (end - timedelta(seconds=1), "ROUND game=spell_it stage=graded asked=4 correct=4 user=" + ADMIN),
        (end, "ROUND game=quiz stage=graded asked=3 correct=3 user=" + LEARNER),
    ]
    (action_logs / "games.log").write_text(
        "".join(f"{_local(t)} {text}\n" for t, text in lines), encoding="utf-8")

    logs = daily_report.gather_logs(start, end, action_logs)

    assert logs["rounds"] == Counter({LEARNER: 1, "anonymous": 1, ADMIN: 1})


def test_rotated_logs_are_read_too(action_logs):
    start, end = daily_report.day_window(DAY)
    action_logs.mkdir(parents=True, exist_ok=True)
    stamp = _local(start + timedelta(hours=1))
    (action_logs / "games.log.2026-10-14").write_text(
        f"{stamp} ROUND game=quiz stage=graded asked=3 correct=1 user=anonymous\n", encoding="utf-8")
    (action_logs / "cards.log").write_text(
        f"{stamp} USER-BLOCK id=13 email={LEARNER} reason='spam in chat'\n"
        f"{stamp} USER-UNBLOCK id=13 email={LEARNER}\n", encoding="utf-8")

    logs = daily_report.gather_logs(start, end, action_logs)

    assert logs["rounds"] == Counter({"anonymous": 1})
    assert logs["blocks"] == [{"id": "13", "email": LEARNER, "reason": "spam in chat"}]
    assert logs["unblocks"] == [{"id": "13", "email": LEARNER}]


def test_no_logs_at_all_is_an_empty_day(action_logs):
    start, end = daily_report.day_window(DAY)

    assert daily_report.gather_logs(start, end, action_logs / "missing") == _logs()


# --- running it -------------------------------------------------------------

@pytest.fixture()
def wired(monkeypatch, action_logs):
    sent = []
    state = {"db": _db(), "logs": _logs()}
    monkeypatch.setattr(daily_report, "gather_db", lambda day, start, end, emails=(): state["db"])
    monkeypatch.setattr(daily_report, "gather_logs", lambda start, end, logs_dir=None: state["logs"])
    monkeypatch.setattr(daily_report, "user_limits", lambda: LIMITS)
    monkeypatch.setattr(notify, "send_admin_email",
                        lambda kind, subject, body: sent.append((kind, subject, body)) or "sent")
    monkeypatch.setenv("ADMIN_EMAILS", ADMIN)
    state["sent"] = sent
    return state


def test_a_day_with_activity_is_emailed(wired):
    wired["db"] = _db(cards={13: 2})

    assert daily_report.main(["--date", "2026-10-14"]) == 0

    (kind, subject, body), = wired["sent"]
    assert kind == notify.KIND_DAILY
    assert "14 Oct" in subject and "#13" in body


def test_an_empty_day_sends_nothing_and_says_so(wired, action_logs):
    assert daily_report.main(["--date", "2026-10-14"]) == 0

    assert wired["sent"] == []
    line = (action_logs / "notify.log").read_text(encoding="utf-8")
    assert "kind=daily" in line and "result=skipped" in line and "reason=no-activity" in line


def test_a_day_of_only_the_admin_sends_nothing(wired):
    wired["db"] = _db(cards={1: 9}, usage={(1, utils.CHAT): 30})

    daily_report.main(["--date", "2026-10-14"])

    assert wired["sent"] == []


def test_a_dry_run_prints_and_sends_nothing(wired, capsys):
    wired["db"] = _db(cards={13: 2})

    assert daily_report.main(["--date", "2026-10-14", "--dry-run"]) == 0

    assert wired["sent"] == []
    out = capsys.readouterr().out
    assert "KuantorFlow: activity on 14 Oct" in out and "#13" in out


def test_a_failed_send_is_a_failed_run(wired, monkeypatch):
    """A scheduled task shows its exit code; a failure should look like one."""
    wired["db"] = _db(cards={13: 2})
    monkeypatch.setattr(notify, "send_admin_email", lambda *a: "failed")

    assert daily_report.main(["--date", "2026-10-14"]) == 1


def test_a_bad_date_is_refused(wired):
    with pytest.raises(SystemExit):
        daily_report.main(["--date", "14.10.2026"])


def test_the_privacy_section_says_so():
    from pathlib import Path

    from conftest import KUANTORFLOW_PATH

    guide = (Path(KUANTORFLOW_PATH) / "docs" / "user-guide.md").read_text(encoding="utf-8")
    start = guide.index("## Privacy: what the site keeps")
    privacy = guide[start:guide.index("\n## ", start + 3)].lower()

    assert "once a day" in privacy and "summary" in privacy
    assert "nothing is sent on a day with no activity" in privacy
