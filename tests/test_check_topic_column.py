"""`scripts/check_topic_column.py`: is `flashcards.topic` safe to drop? (kuantorflow#210)

#207 gave topics their own table and kept the `topic` string beside
`topic_id` for the transition. Before #210 drops the string, every card's copy
is compared with the name its `topic_id` points at. Read-only: it reports and
writes nothing.

Two findings block the drop, and only those set the exit code: a card with a
topic string but **no `topic_id`** (dropping the column would lose its only
topic), and a `topic_id` with **no topics row**. A string that differs from its
topic's name is reported but does not block: the app already shows the topics
row's name, so the string is a stale copy and dropping it loses nothing shown.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

from conftest import KUANTORFLOW_PATH

SCRIPT = Path(KUANTORFLOW_PATH) / "scripts" / "check_topic_column.py"


@pytest.fixture(scope="module")
def check():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("check_topic_column", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# (id, word, topic string, topic_id, topics.name via the join)
ROWS = [
    (1, "resign", "Work and careers", 1, "Work and careers"),     # matches
    (2, "commute", "daily life ", 3, "Daily life"),               # case/spacing only
    (3, "promotion", "Old work topic", 1, "Work and careers"),    # differs
    (4, "orphan", "Lost topic", None, None),                      # string, no id: blocks
    (5, "ghost", "Gone", 99, None),                               # id, no row: blocks
    (6, "bare", None, 1, "Work and careers"),                     # id, no string: fine
    (7, "loose", "", None, None),                                 # neither: fine
]


def test_each_card_lands_in_exactly_one_case(check):
    found = check.classify(ROWS)

    ids = {case: [r[0] for r in rows] for case, rows in found.items()}
    assert ids == {"match": [1], "case_or_spacing": [2], "differs": [3],
                   "unlinked": [4], "missing_topic": [5], "id_only": [6],
                   "no_topic": [7]}


def test_only_the_cases_that_lose_data_block_the_drop(check):
    assert check.blocking(check.classify(ROWS)) == ["unlinked", "missing_topic"]
    clean = [r for r in ROWS if r[0] not in (4, 5)]
    assert check.blocking(check.classify(clean)) == []


class _Cursor:
    def __init__(self, rows, has_column=True):
        self.rows, self.sql, self.has_column = rows, [], has_column
        self._answer = []

    def execute(self, sql, params=()):
        self.sql.append(sql)
        if "information_schema" in sql:
            self._answer = [(1,)] if self.has_column else []
        else:
            self._answer = list(self.rows)

    def fetchall(self):
        return list(self._answer)

    def close(self):
        pass


class _Conn:
    def __init__(self, rows, has_column=True):
        self.cur = _Cursor(rows, has_column)

    def cursor(self):
        return self.cur

    def close(self):
        pass


def _run(check, monkeypatch, capsys, rows, *argv, has_column=True):
    conn = _Conn(rows, has_column)
    monkeypatch.setattr(check, "get_db_connection", lambda: conn)
    code = check.main(list(argv))
    return code, capsys.readouterr().out, conn.cur.sql


def test_it_exits_1_and_names_the_blocking_cards(check, monkeypatch, capsys):
    code, out, _sql = _run(check, monkeypatch, capsys, ROWS)

    assert code == 1
    assert "NOT safe to drop" in out
    assert "orphan" in out and "ghost" in out


def test_it_exits_0_when_nothing_would_be_lost(check, monkeypatch, capsys):
    clean = [r for r in ROWS if r[0] not in (4, 5)]
    code, out, _sql = _run(check, monkeypatch, capsys, clean)

    assert code == 0
    assert "safe to drop" in out and "NOT safe" not in out


def test_it_reports_a_stale_string_without_blocking(check, monkeypatch, capsys):
    code, out, _sql = _run(check, monkeypatch, capsys, [ROWS[2]])

    assert code == 0
    assert "promotion" in out and "Old work topic" in out and "Work and careers" in out


def test_it_only_reads(check, monkeypatch, capsys):
    _code, _out, sql = _run(check, monkeypatch, capsys, ROWS)

    assert sql and all(s.lstrip().upper().startswith("SELECT") for s in sql)


def test_it_prints_only_ascii(check, monkeypatch, capsys):
    # A Windows console is cp1252: Cyrillic topic names are escaped, not crashed on.
    rows = [(8, "word", "Побут", 4, "Побут і дім")]
    _code, out, _sql = _run(check, monkeypatch, capsys, rows)

    assert out.isascii()


def test_after_the_drop_it_says_so_instead_of_failing(check, monkeypatch, capsys):
    # kuantorflow#210 drops the column; the check is then simply done, and
    # must not crash on a column that no longer exists.
    code, out, sql = _run(check, monkeypatch, capsys, ROWS, has_column=False)

    assert code == 0
    assert "already gone" in out
    assert not any("flashcards f LEFT JOIN" in s for s in sql), "it asked about the column first"
