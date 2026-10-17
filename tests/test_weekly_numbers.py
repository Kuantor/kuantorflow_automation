"""Production's numbers for the weekly report, in one file (kuantorflow#607).

`scripts/weekly_numbers.py` replaces the five commands each edition used to
need run by hand on PythonAnywhere. What must hold:

* each section's figures come from the logs on or after `--since`, and the
  database section from `db_numbers()` (stubbed here);
* the requests section lists the paths that answered 404, which the
  17 October edition could only guess at;
* a section that cannot be read says so, and the others are still written;
* nothing in the file names a person.
"""

from datetime import date

import pytest

import weekly_numbers

SINCE = "2026-10-10"


def _write(directory, name, lines):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text("".join(line + "\n" for line in lines), encoding="utf-8")


@pytest.fixture()
def logs(tmp_path, monkeypatch):
    d = tmp_path / "logs"
    _write(d, "requests.log", [
        "2026-10-09 12:00:00 REQUEST method=GET path=/ endpoint=index status=200 ms=9999 db=9 user_id=anonymous",
        "2026-10-11 08:00:00 REQUEST method=GET path=/ endpoint=index status=200 ms=800 db=5 user_id=7 rid=a1",
        "2026-10-11 08:00:05 REQUEST method=GET path=/ endpoint=index status=200 ms=400 db=2 user_id=anonymous rid=a2",
        "2026-10-11 08:00:06 REQUEST method=GET path=/favicon.ico endpoint=- status=404 ms=0 db=0 user_id=anonymous rid=a3",
        "2026-10-12 09:00:00 REQUEST method=GET path=/wp-login.php endpoint=- status=404 ms=1 db=0 user_id=anonymous rid=a4",
        "2026-10-12 09:00:01 REQUEST method=GET path=/favicon.ico endpoint=- status=404 ms=0 db=0 user_id=anonymous rid=a5",
    ])
    _write(d, "requests.log.2026-10-11", [
        "2026-10-10 07:00:00 REQUEST method=POST path=/lookup.json endpoint=lookup_json status=200 ms=5301 db=3 user_id=7",
    ])
    _write(d, "model_usage.log", [
        "2026-10-09 10:00:00 MODEL-USAGE feature=translate model=claude-haiku-4-5 in=1 out=1 cache_write=0 cache_read=0 stop=end_turn ms=10",
        "2026-10-11 10:00:00 MODEL-USAGE feature=translate model=claude-haiku-4-5 in=432 out=43 cache_write=0 cache_read=0 stop=end_turn ms=1600",
    ])
    _write(d, "dict.log", [
        "2026-10-09 10:00:00 TRANSLATE-DROPPED word=a provider=claude lang=ukr pos=noun variant=x reason=latin",
        "2026-10-12 10:00:00 TRANSLATE-DROPPED word=b provider=claude lang=ukr pos=noun variant=y reason=latin",
        "2026-10-12 10:00:01 TRANSLATE word=b provider=claude",
    ])
    _write(d, "notify.log", [
        "2026-10-11 05:00:00 NOTIFY kind=test result=sent subject='KuantorFlow: test email' ms=1800",
        "2026-10-12 05:00:00 NOTIFY kind=daily result=skipped subject='x' reason=no-activity",
        "2026-10-13 05:00:00 NOTIFY kind=daily result=skipped subject='x' reason=no-activity",
        "2026-10-13 06:00:00 NOTIFY kind=new-account result=sent subject='KuantorFlow: new account #9 an***@gmail.com'",
    ])
    monkeypatch.setattr(weekly_numbers, "db_numbers", lambda since: {
        "visits": [(date(2026, 10, 12), 3, 2, 3, 600, 7)], "accounts": 14, "new": 1})
    return d


def _text(logs):
    return weekly_numbers.build(logs, SINCE)


def test_requests_are_counted_from_the_day_on(logs):
    text = _text(logs)

    assert "6 requests; status {'200': 3, '404': 3}" in text
    assert "{'anonymous': 4, 'signed-in': 2}" in text
    assert "9999" not in text, "a line before --since was counted"


def test_requests_have_a_row_per_endpoint(logs):
    row = next(line for line in _text(logs).splitlines() if line.startswith("index "))

    assert row.split()[:2] == ["index", "2"]
    assert row.split()[-2:] == ["2", "5"]           # db median and max


def test_rotated_logs_are_read(logs):
    assert "lookup_json" in _text(logs) and "5301 ms" in _text(logs)


def test_the_404_paths_are_listed(logs):
    text = _text(logs)

    assert "404s by path (3):" in text
    assert "   2  /favicon.ico" in text and "   1  /wp-login.php" in text


def test_ai_usage_is_the_usage_reports_table(logs):
    text = _text(logs)

    assert "translate" in text and "432" in text
    assert "2026-10-09" not in text.split("2. Requests")[0], "a day before --since"


def test_translations_dropped_are_counted(logs):
    assert "1 translation(s) dropped by the alphabet check." in _text(logs)


def test_admin_emails_by_kind_and_result(logs):
    text = _text(logs)

    assert "    2  kind=daily result=skipped" in text
    assert "    1  kind=new-account result=sent" in text
    assert "    1  kind=test result=sent" in text


def test_visits_and_accounts(logs):
    text = _text(logs)

    assert "14 accounts in all, 1 created since 2026-10-10." in text
    assert "2026-10-12      3     2        3       10.0      7" in text


def test_nothing_names_a_person(logs):
    assert "@" not in _text(logs)


def test_a_failing_section_does_not_cost_the_file(logs, monkeypatch):
    def down(since):
        raise RuntimeError("db unreachable")
    monkeypatch.setattr(weekly_numbers, "db_numbers", down)

    text = _text(logs)

    assert "(could not be read: RuntimeError: db unreachable)" in text
    assert "404s by path" in text and "dropped by the alphabet check" in text


def test_no_logs_at_all_is_said_plainly(tmp_path, monkeypatch):
    monkeypatch.setattr(weekly_numbers, "db_numbers",
                        lambda since: {"visits": [], "accounts": 0, "new": 0})

    text = weekly_numbers.build(tmp_path / "none", SINCE)

    for said in ("No model usage logged.", "No requests logged.",
                 "0 translation(s) dropped", "No admin emails attempted.", "No visits recorded."):
        assert said in text


def test_main_writes_the_file_and_says_where(logs, tmp_path, capsys):
    out = tmp_path / "numbers.txt"

    assert weekly_numbers.main(["--since", SINCE, "--logs", str(logs), "--out", str(out)]) == 0

    assert out.read_text(encoding="utf-8").startswith("KuantorFlow production numbers since 2026-10-10")
    assert str(out) in capsys.readouterr().out


def test_the_default_file_is_in_the_home_folder(logs, tmp_path, monkeypatch):
    monkeypatch.setattr(weekly_numbers.Path, "home", lambda: tmp_path)

    weekly_numbers.main(["--logs", str(logs)])

    assert (tmp_path / f"weekly-numbers-{date.today().isoformat()}.txt").exists()
